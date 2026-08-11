"""
会话管理接口路由

提供多轮会话的 CRUD 端点，支持前端侧边栏的会话列表展示与管理。
所有持久化逻辑由 SessionService 承载，路由层只负责请求解析和响应组装。
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_session_service
from app.api.schemas.session_schema import (
    SessionCreateSchema,
    SessionRenameSchema,
)
from app.services.session_service import SessionService

session_router = APIRouter()


@session_router.get("/api/sessions")
async def list_sessions(
    session_service: Annotated[SessionService, Depends(get_session_service)],
):
    """返回全部会话列表，按最后更新时间倒序排列"""

    sessions = await session_service.list_sessions()
    return {
        "code": 0,
        "message": "success",
        "data": [s.to_dict() for s in sessions],
    }


@session_router.post("/api/sessions")
async def create_session(
    body: SessionCreateSchema,
    session_service: Annotated[SessionService, Depends(get_session_service)],
):
    """创建新会话，返回会话 ID 和元数据"""

    session = await session_service.create_session(name=body.name)
    return {
        "code": 0,
        "message": "success",
        "data": session.to_dict(),
    }


@session_router.patch("/api/sessions/{session_id}")
async def rename_session(
    session_id: str,
    body: SessionRenameSchema,
    session_service: Annotated[SessionService, Depends(get_session_service)],
):
    """重命名指定会话"""

    session = await session_service.rename_session(session_id, body.name)
    if session is None:
        return {"code": 404, "message": "会话不存在", "data": None}
    return {
        "code": 0,
        "message": "success",
        "data": session.to_dict(),
    }


@session_router.get("/api/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    session_service: Annotated[SessionService, Depends(get_session_service)],
):
    """获取指定会话的全部对话历史，按时间正序返回 user/assistant 消息序列

    每轮对话拆分为两条消息：
      - role=user：用户原始问题
      - role=assistant：查询结果 + 摘要 + 步骤信息
    供前端切换会话时完整恢复渲染。
    """

    session = await session_service.get_session(session_id)
    if session is None:
        return {"code": 404, "message": "会话不存在", "data": None}

    turns = await session_service.get_history(session_id, limit=200)
    messages = []
    for turn in turns:
        turn_dict = turn.to_dict()
        messages.append(
            {
                "id": f"{turn.created_at}-user",
                "role": "user",
                "content": turn.query,
                "createdAt": _to_ts(turn.created_at),
            }
        )
        messages.append(
            {
                "id": f"{turn.created_at}-assistant",
                "role": "assistant",
                "content": turn.result_summary or turn.query[:40],
                "createdAt": _to_ts(turn.created_at),
                "status": "done",
                "steps": [],
                "result": turn_dict.get("result"),
                "summary": turn.result_summary,
                "summaryStreaming": False,
            }
        )

    return {
        "code": 0,
        "message": "success",
        "data": messages,
    }


@session_router.delete("/api/sessions/{session_id}")
async def delete_session(
    session_id: str,
    session_service: Annotated[SessionService, Depends(get_session_service)],
):
    """删除指定会话及其全部对话历史"""

    deleted = await session_service.delete_session(session_id)
    if not deleted:
        return {"code": 404, "message": "会话不存在", "data": None}
    return {
        "code": 0,
        "message": "会话已删除",
    }


def _to_ts(iso_str: str) -> int:
    """把 ISO 时间字符串转为毫秒时间戳"""
    from datetime import datetime

    try:
        return int(datetime.fromisoformat(iso_str).timestamp() * 1000)
    except (ValueError, OSError):
        return 0
