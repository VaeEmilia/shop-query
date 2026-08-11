"""
会话实体

定义多轮对话所需的会话元数据和单轮对话片段数据结构，
用于在 Redis 中持久化会话历史和上下文，支持问题改写（Query Rewriting）。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class SessionTurn:
    """一轮对话片段，包含用户问题、改写后的问题、生成的 SQL 和结果摘要"""

    # 用户原始输入（追问时可能是简短的上下文依赖语句）
    query: str
    # 经问题改写后包含完整上下文的独立查询语句
    rewritten_query: str
    # 本轮生成的 SQL（可能为空，如缓存命中场景）
    sql: Optional[str] = None
    # 结果摘要，用于后续轮次改写时提供上下文
    result_summary: Optional[str] = None
    # 该轮创建时间
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "rewritten_query": self.rewritten_query,
            "sql": self.sql,
            "result_summary": self.result_summary,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionTurn":
        return cls(
            query=data.get("query", ""),
            rewritten_query=data.get("rewritten_query", ""),
            sql=data.get("sql"),
            result_summary=data.get("result_summary"),
            created_at=data.get("created_at", datetime.now().isoformat()),
        )


@dataclass
class Session:
    """一次会话的元数据"""

    id: str
    # 会话展示名称，默认用首条问题截断生成
    name: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # 最后一条消息摘要，供侧边栏展示
    last_summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_summary": self.last_summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        return cls(
            id=data["id"],
            name=data.get("name", "新会话"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            last_summary=data.get("last_summary"),
        )
