"""
FastAPI 应用生命周期管理

负责在服务启动时初始化外部客户端，在服务关闭时释放连接资源。
这些客户端是应用级资源，适合在 lifespan 中创建一次并复用，而不是每个请求
重复初始化。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.clients.redis_client_manager import redis_client_manager
from app.models.base import Base
from app.models.session import SessionMySQL  # noqa: F401
from app.models.session_turn import SessionTurnMySQL  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用启动和关闭两个阶段的外部资源"""

    # 启动阶段：先建立各类外部服务客户端，后续依赖函数会从 manager 中取已初始化对象
    qdrant_client_manager.init()
    embedding_client_manager.init()
    es_client_manager.init()
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()
    redis_client_manager.init()

    # 自动创建会话相关的数据表（仅在不存在时创建，已有表不受影响）
    async with meta_mysql_client_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # yield 之前是启动逻辑，yield 之后是关闭逻辑；中间阶段由 FastAPI 正常处理请求
    yield

    # 关闭阶段：按应用级资源统一释放连接，避免进程退出前留下未关闭的网络连接
    await qdrant_client_manager.close()
    await es_client_manager.close()
    await meta_mysql_client_manager.close()
    await dw_mysql_client_manager.close()
    await redis_client_manager.close()
