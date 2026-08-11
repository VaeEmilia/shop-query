"""
会话管理服务

基于 Redis 持久化多轮对话的会话元数据和对话历史片段，
为问题改写（Query Rewriting）提供上下文回溯能力，并管理会话生命周期。

存储结构：
  - session:meta:{id}   -> 会话元数据 JSON（String）
  - session:turns:{id}  -> 对话历史片段列表（List，左新右旧）
  - session:index       -> 全部会话 ID 索引（Sorted Set，score=updated_at）
"""

import json
import time
import uuid
from typing import List, Optional

from loguru import logger
from redis.asyncio import Redis

from app.conf.app_config import app_config
from app.entities.session import Session, SessionTurn


class SessionService:
    """管理多轮会话的创建、查询、历史回溯与生命周期清理"""

    META_PREFIX = "session:meta"
    TURNS_PREFIX = "session:turns"
    INDEX_KEY = "session:index"

    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.max_sessions = app_config.session.max_sessions
        self.history_turns = app_config.session.history_turns
        self.ttl = app_config.session.ttl

    # ------------------------------------------------------------------
    #  会话 CRUD
    # ------------------------------------------------------------------

    async def create_session(self, name: Optional[str] = None) -> Session:
        """创建新会话，返回 Session 元数据；自动维护会话数量上限"""
        session_id = str(uuid.uuid4())
        now = time.time()
        iso_now = _isoformat(now)

        session = Session(
            id=session_id,
            name=name or "新会话",
            created_at=iso_now,
            updated_at=iso_now,
        )
        await self._save_meta(session)
        await self.redis.zadd(self.INDEX_KEY, {session_id: now})
        await self._enforce_limit()
        logger.info(f"[Session] 创建会话 {session_id}: {session.name}")
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """按 ID 读取会话元数据"""
        data = await self.redis.get(f"{self.META_PREFIX}:{session_id}")
        if not data:
            return None
        return Session.from_dict(json.loads(data))

    async def list_sessions(self) -> List[Session]:
        """按更新时间倒序返回全部会话"""
        # ZREVRANGE 按 score 倒序取出全部 session_id
        session_ids = await self.redis.zrevrange(self.INDEX_KEY, 0, -1)
        if not session_ids:
            return []
        sessions: List[Session] = []
        for sid in session_ids:
            data = await self.redis.get(f"{self.META_PREFIX}:{sid}")
            if data:
                sessions.append(Session.from_dict(json.loads(data)))
        return sessions

    async def rename_session(self, session_id: str, name: str) -> Optional[Session]:
        """重命名会话"""
        session = await self.get_session(session_id)
        if session is None:
            return None
        session.name = name
        await self._save_meta(session)
        logger.info(f"[Session] 重命名会话 {session_id} -> {name}")
        return session

    async def delete_session(self, session_id: str) -> bool:
        """删除会话及其全部历史"""
        existed = await self.redis.delete(f"{self.META_PREFIX}:{session_id}")
        await self.redis.delete(f"{self.TURNS_PREFIX}:{session_id}")
        await self.redis.zrem(self.INDEX_KEY, session_id)
        deleted = existed > 0
        if deleted:
            logger.info(f"[Session] 删除会话 {session_id}")
        return deleted

    # ------------------------------------------------------------------
    #  对话历史
    # ------------------------------------------------------------------

    async def add_turn(self, session_id: str, turn: SessionTurn) -> None:
        """追加一轮对话到历史，并更新会话元数据的摘要和时间"""
        key = f"{self.TURNS_PREFIX}:{session_id}"
        await self.redis.lpush(key, json.dumps(turn.to_dict(), ensure_ascii=False))
        # 历史列表也设置过期，避免孤立数据长期残留
        await self.redis.expire(key, self.ttl)

        session = await self.get_session(session_id)
        if session is not None:
            session.last_summary = turn.result_summary or turn.query[:40]
            session.updated_at = _isoformat(time.time())
            await self._save_meta(session)
            await self.redis.zadd(self.INDEX_KEY, {session_id: time.time()})

    async def get_history(
        self, session_id: str, limit: Optional[int] = None
    ) -> List[SessionTurn]:
        """读取最近 N 轮对话历史，按时间正序返回（旧 -> 新）"""
        limit = limit or self.history_turns
        key = f"{self.TURNS_PREFIX}:{session_id}"
        # LPUSH 写入后顺序是 新 -> 旧，LRANGE 0..limit-1 取最近 limit 条，再反转成正序
        raw = await self.redis.lrange(key, 0, limit - 1)
        if not raw:
            return []
        turns = [SessionTurn.from_dict(json.loads(item)) for item in raw]
        turns.reverse()
        return turns

    # ------------------------------------------------------------------
    #  内部辅助
    # ------------------------------------------------------------------

    async def _save_meta(self, session: Session) -> None:
        """写入会话元数据，带 TTL"""
        key = f"{self.META_PREFIX}:{session.id}"
        data = json.dumps(session.to_dict(), ensure_ascii=False)
        await self.redis.set(key, data, ex=self.ttl)

    async def _enforce_limit(self) -> None:
        """会话数量超过上限时，清理最旧的会话"""
        count = await self.redis.zcard(self.INDEX_KEY)
        if count <= self.max_sessions:
            return
        # 按升序取出需要清理的旧会话（score 最小 = 最旧）
        excess = count - self.max_sessions
        old_ids = await self.redis.zrange(self.INDEX_KEY, 0, excess - 1)
        for sid in old_ids:
            await self.redis.delete(f"{self.META_PREFIX}:{sid}")
            await self.redis.delete(f"{self.TURNS_PREFIX}:{sid}")
            await self.redis.zrem(self.INDEX_KEY, sid)
        logger.info(f"[Session] 清理 {len(old_ids)} 个过期会话")


def _isoformat(ts: float) -> str:
    """把 Unix 时间戳转成 ISO 格式字符串"""
    from datetime import datetime

    return datetime.fromtimestamp(ts).isoformat()
