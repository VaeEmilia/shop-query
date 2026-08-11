"""
Redis 客户端管理器

负责按配置初始化 Redis 连接，为 SQL 缓存、命中率统计等提供统一访问入口。
"""

from typing import Optional

import redis.asyncio as redis

from app.conf.app_config import RedisConfig, app_config


class RedisClientManager:
    """管理 Redis 客户端的初始化与复用"""

    def __init__(self, config: RedisConfig):
        self.client: Optional[redis.Redis] = None
        self.config = config

    def init(self):
        """显式初始化客户端"""
        kwargs = {
            "host": self.config.host,
            "port": self.config.port,
            "db": self.config.db,
            "decode_responses": True,
        }
        if self.config.password:
            kwargs["password"] = self.config.password
        self.client = redis.Redis(**kwargs)

    async def close(self):
        """释放连接池"""
        if self.client is not None:
            await self.client.close()


# 模块级单例
redis_client_manager = RedisClientManager(app_config.redis)
