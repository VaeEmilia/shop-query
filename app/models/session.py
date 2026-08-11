"""
session ORM 模型

会话元数据表，保存每个会话的基础信息，用于侧边栏展示和会话管理。
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SessionMySQL(Base):
    """会话元数据表对应的 ORM 模型"""

    __tablename__ = "session"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, comment="会话唯一 ID (UUID)"
    )
    name: Mapped[str] = mapped_column(String(128), default="新会话", comment="会话名称")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="最后更新时间"
    )
    last_summary: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="最后一条消息摘要"
    )
