"""
SQL 安全审计节点

在 validate_sql 之前做静态安全分析，基于 sqlglot AST 拦截 DDL/DML、多语句、
危险函数、系统表访问，并自动注入 LIMIT 上限。
校验失败时把原因写入 state["error"]，由条件边进入 correct_sql 重试；
超过 max_retry_count 后硬失败走 END，避免无限循环。
"""

import re

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.conf.app_config import app_config
from app.core.log import logger
from app.core.sql_safety import sql_safety_auditor

# 匹配首尾的 Markdown 代码块标记（```sql ... ```），LLM 偶尔会带上
_CODE_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def _strip_code_fence(sql: str) -> str:
    """去除 LLM 偶尔生成的 Markdown 代码块标记，auditor 只处理纯 SQL"""
    m = _CODE_FENCE_RE.match(sql)
    return m.group(1).strip() if m else sql.strip()


async def sql_safety_check(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """SQL 安全审计：在语法校验前做静态安全分析"""

    writer = runtime.stream_writer
    step = "安全校验"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        # 节点层做轻量预处理：去除 Markdown 代码块标记和首尾空白
        sql = _strip_code_fence(state["sql"])
        retry_count = state.get("retry_count", 0)
        safety_config = app_config.sql_safety

        # 配置开关关闭时直接放行，不校验也不改写
        if not safety_config.enabled:
            writer({"type": "progress", "step": step, "status": "success"})
            return {"error": None}

        result = sql_safety_auditor.audit(sql)

        if result.passed:
            logger.info("SQL安全校验通过")
            writer({"type": "progress", "step": step, "status": "success"})
            # 用改写后的 SQL（含 LIMIT 注入）覆盖 state["sql"]，清空 error
            return {"sql": result.transformed_sql, "error": None}

        # 超过最大重试次数，硬失败：推 error 事件让前端展示，条件边走 END
        if retry_count >= safety_config.max_retry_count:
            hard_error = (
                f"SQL安全校验失败（已重试{retry_count}次达到上限）: {result.reason}"
            )
            logger.error(hard_error)
            writer({"type": "progress", "step": step, "status": "error"})
            writer({"type": "error", "message": hard_error})
            return {"error": hard_error}

        # 未超限：写原因到 error，条件边走 correct_sql 让模型修正
        logger.info(f"SQL安全校验失败：{result.reason}")
        writer({"type": "progress", "step": step, "status": "success"})
        return {"error": result.reason}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
