"""
会话管理接口请求/响应体定义

集中声明会话 CRUD 相关的 Pydantic 模型，
让路由函数只处理业务流程，校验和文档生成交给 Pydantic。
"""

from pydantic import BaseModel, Field


class SessionCreateSchema(BaseModel):
    """创建会话请求体"""

    # 可选的会话名称，不传时后端默认使用 "新会话"
    name: str | None = None


class SessionRenameSchema(BaseModel):
    """重命名会话请求体"""

    name: str = Field(..., min_length=1, max_length=50)


class SessionSchema(BaseModel):
    """会话元数据响应体"""

    id: str
    name: str
    created_at: str
    updated_at: str
    last_summary: str | None = None
