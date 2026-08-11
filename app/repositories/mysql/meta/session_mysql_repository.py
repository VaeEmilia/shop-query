"""
会话 MySQL 仓储

负责把 Session / SessionTurn 业务实体持久化到 Meta MySQL，
基于 SQLAlchemy async session 实现，支持完整的 CRUD 操作。
所有写操作在 flush 后必须 commit，否则数据在 session 关闭时会被回滚。
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.session import Session, SessionTurn
from app.models.session import SessionMySQL
from app.models.session_turn import SessionTurnMySQL


class SessionMySQLRepository:
    """负责把会话业务实体持久化到 Meta MySQL"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    #  Session CRUD
    # ------------------------------------------------------------------

    async def create_session(self, session_entity: Session) -> Session:
        """创建新会话"""
        model = SessionMySQL(
            id=session_entity.id,
            name=session_entity.name,
            created_at=datetime.fromisoformat(session_entity.created_at),
            updated_at=datetime.fromisoformat(session_entity.updated_at),
            last_summary=session_entity.last_summary,
        )
        self.session.add(model)
        await self.session.commit()
        return self._to_entity(model)

    async def get_session(self, session_id: str) -> Optional[Session]:
        """按 ID 读取会话"""
        stmt = select(SessionMySQL).where(SessionMySQL.id == session_id)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_sessions(self, limit: int = 20) -> List[Session]:
        """按更新时间倒序返回全部会话"""
        stmt = (
            select(SessionMySQL)
            .order_by(SessionMySQL.updated_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def rename_session(self, session_id: str, name: str) -> Optional[Session]:
        """重命名会话"""
        stmt = select(SessionMySQL).where(SessionMySQL.id == session_id)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        model.name = name
        model.updated_at = datetime.now()
        await self.session.commit()
        return self._to_entity(model)

    async def delete_session(self, session_id: str) -> bool:
        """删除会话及其全部对话历史"""
        await self.session.execute(
            delete(SessionTurnMySQL).where(SessionTurnMySQL.session_id == session_id)
        )
        result = await self.session.execute(
            delete(SessionMySQL).where(SessionMySQL.id == session_id)
        )
        await self.session.commit()
        return result.rowcount > 0

    # ------------------------------------------------------------------
    #  SessionTurn CRUD
    # ------------------------------------------------------------------

    async def add_turn(self, session_id: str, turn: SessionTurn) -> None:
        """追加一轮对话到历史，并更新会话元数据的摘要和时间"""
        result_data = turn.result
        if isinstance(result_data, list) and len(result_data) > 200:
            result_data = result_data[:200]

        model = SessionTurnMySQL(
            session_id=session_id,
            query=turn.query,
            rewritten_query=turn.rewritten_query,
            sql=turn.sql,
            result_summary=turn.result_summary,
            result=result_data if result_data is not None else None,
            created_at=datetime.fromisoformat(turn.created_at),
        )
        self.session.add(model)

        stmt = select(SessionMySQL).where(SessionMySQL.id == session_id)
        sess_result = await self.session.execute(stmt)
        session_model = sess_result.scalar_one_or_none()
        if session_model is not None:
            session_model.last_summary = turn.result_summary or turn.query[:40]
            session_model.updated_at = datetime.now()

        await self.session.commit()

    async def get_history(
        self, session_id: str, limit: int = 20
    ) -> List[SessionTurn]:
        """读取最近 N 轮对话历史，按时间正序返回（旧 -> 新）"""
        stmt = (
            select(SessionTurnMySQL)
            .where(SessionTurnMySQL.session_id == session_id)
            .order_by(SessionTurnMySQL.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        models.reverse()
        return [self._turn_to_entity(m) for m in models]

    # ------------------------------------------------------------------
    #  Entity / Model 转换
    # ------------------------------------------------------------------

    @staticmethod
    def _to_entity(model: SessionMySQL) -> Session:
        return Session(
            id=model.id,
            name=model.name,
            created_at=_dt_to_iso(model.created_at),
            updated_at=_dt_to_iso(model.updated_at),
            last_summary=model.last_summary,
        )

    @staticmethod
    def _turn_to_entity(model: SessionTurnMySQL) -> SessionTurn:
        return SessionTurn(
            query=model.query,
            rewritten_query=model.rewritten_query,
            sql=model.sql,
            result_summary=model.result_summary,
            result=model.result,
            created_at=_dt_to_iso(model.created_at),
        )


def _dt_to_iso(val) -> str:
    """把 datetime 转 ISO 字符串，已有时直接返回"""
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)
