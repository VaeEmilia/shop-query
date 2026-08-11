"""
session_turn ORM 模型

会话对话片段表，保存每轮对话的完整上下文（用户问题、改写问题、SQL、结果摘要、完整结果）。
用于问题改写时回溯历史，以及前端切换会话时恢复渲染。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SessionTurnMySQL(Base):
    """会话对话片段表对应的 ORM 模型"""

    __tablename__ = "session_turn"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="自增主键")
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("session.id", ondelete="CASCADE"), index=True, comment="所属会话 ID"
    )
    query: Mapped[str] = mapped_column(Text, comment="用户原始问题")
    rewritten_query: Mapped[str] = mapped_column(Text, comment="改写后的完整查询")
    sql: Mapped[str | None] = mapped_column(Text, nullable=True, comment="本轮生成的 SQL")
    result_summary: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="结果摘要"
    )
    # JSON 类型存储完整查询结果，供前端恢复表格渲染
    result: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="完整查询结果 (JSON)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, index=True, comment="创建时间"
    )
