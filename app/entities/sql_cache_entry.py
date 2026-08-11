"""
SQL 缓存实体

定义存入 Redis 的缓存数据结构，包含问题向量、生成的 SQL 与查询结果。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SQLCacheEntry:
    """一条 SQL 缓存记录"""

    # 原始用户问题（用于展示和调试）
    query: str
    # 问题向量（list[float]），用于后续相似度匹配
    embedding: List[float]
    # LangGraph 工作流最终生成的 SQL
    sql: str
    # SQL 执行后的结果（列表或字典）
    result: Any
    # 缓存创建时间
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # 命中次数
    hit_count: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可存入 Redis 的字典"""
        return {
            "query": self.query,
            "embedding": self.embedding,
            "sql": self.sql,
            "result": self.result,
            "created_at": self.created_at,
            "hit_count": self.hit_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SQLCacheEntry":
        """从 Redis 取出的字典反序列化"""
        return cls(
            query=data["query"],
            embedding=data["embedding"],
            sql=data["sql"],
            result=data["result"],
            created_at=data.get("created_at", datetime.now().isoformat()),
            hit_count=data.get("hit_count", 1),
        )
