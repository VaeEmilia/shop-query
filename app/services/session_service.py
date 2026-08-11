"""
会话管理服务

基于 MySQL 持久化多轮对话的会话元数据和对话历史片段，
为问题改写（Query Rewriting）提供上下文回溯能力，并管理会话生命周期。
"""

from datetime import datetime
from typing import List, Optional

from loguru import logger

from app.conf.app_config import app_config
from app.entities.session import Session, SessionTurn
from app.repositories.mysql.meta.session_mysql_repository import SessionMySQLRepository


class SessionService:
    """管理多轮会话的创建、查询、历史回溯与生命周期清理"""

    def __init__(self, repository: SessionMySQLRepository):
        self.repo = repository
        self.max_sessions = app_config.session.max_sessions
        self.history_turns = app_config.session.history_turns

    # ------------------------------------------------------------------
    #  会话 CRUD
    # ------------------------------------------------------------------

    async def create_session(self, name: Optional[str] = None) -> Session:
        """创建新会话，返回 Session 元数据；自动维护会话数量上限"""
        now = datetime.now().isoformat()
        session = Session(
            id=_new_id(),
            name=name or "新会话",
            created_at=now,
            updated_at=now,
        )
        session = await self.repo.create_session(session)
        await self._enforce_limit()
        logger.info(f"[Session] 创建会话 {session.id}: {session.name}")
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """按 ID 读取会话元数据"""
        return await self.repo.get_session(session_id)

    async def list_sessions(self) -> List[Session]:
        """按更新时间倒序返回全部会话"""
        return await self.repo.list_sessions(limit=self.max_sessions)

    async def rename_session(self, session_id: str, name: str) -> Optional[Session]:
        """重命名会话"""
        session = await self.repo.rename_session(session_id, name)
        if session is not None:
            logger.info(f"[Session] 重命名会话 {session_id} -> {name}")
        return session

    async def delete_session(self, session_id: str) -> bool:
        """删除会话及其全部历史"""
        deleted = await self.repo.delete_session(session_id)
        if deleted:
            logger.info(f"[Session] 删除会话 {session_id}")
        return deleted

    # ------------------------------------------------------------------
    #  对话历史
    # ------------------------------------------------------------------

    async def add_turn(self, session_id: str, turn: SessionTurn) -> None:
        """追加一轮对话到历史，并更新会话元数据的摘要和时间"""
        await self.repo.add_turn(session_id, turn)

    async def get_history(
        self, session_id: str, limit: Optional[int] = None
    ) -> List[SessionTurn]:
        """读取最近 N 轮对话历史，按时间正序返回（旧 -> 新）"""
        limit = limit or self.history_turns
        return await self.repo.get_history(session_id, limit=limit)

    # ------------------------------------------------------------------
    #  内部辅助
    # ------------------------------------------------------------------

    async def _enforce_limit(self) -> None:
        """会话数量超过上限时，清理最旧的会话"""
        sessions = await self.repo.list_sessions(limit=self.max_sessions + 1)
        if len(sessions) <= self.max_sessions:
            return
        # 列表已按 updated_at 倒序，最后一条是最旧的
        oldest = sessions[-1]
        await self.repo.delete_session(oldest.id)
        logger.info(f"[Session] 清理过期会话 {oldest.id}")


def _new_id() -> str:
    """生成 UUID"""
    import uuid

    return str(uuid.uuid4())
