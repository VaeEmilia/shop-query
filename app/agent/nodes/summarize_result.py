"""
查询结果自然语言总结节点

放在 run_sql 之后执行：调用 LLM 把用户问题、SQL 和查询结果
总结成 1~3 句中文自然语言，并以 SSE 流式方式逐 token 推给前端。
总结失败（模型异常 / 超时 / 未开启）会自动降级，不影响主流程。
"""

import json

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.conf.app_config import app_config
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt


async def summarize_result(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """基于 SQL 执行结果生成自然语言总结；配置关闭或异常时降级跳过"""

    writer = runtime.stream_writer
    step = "总结结果"

    # 1. 全局开关：未开启时直接跳过，不影响主流程
    summary_cfg = getattr(app_config, "summary", None)
    summary_enabled = bool(summary_cfg and getattr(summary_cfg, "enable", False))
    if not summary_enabled:
        logger.debug("[summarize_result] 总结功能未开启，跳过")
        return

    # 2. 没有结果或为空也直接跳过
    sql_result = state.get("sql_result")
    if sql_result is None:
        logger.debug("[summarize_result] sql_result 为空，跳过总结")
        return

    writer({"type": "progress", "step": step, "status": "running"})

    try:
        query = state["query"]
        sql = state.get("sql", "")

        prompt = PromptTemplate(
            template=load_prompt("summarize_result"),
            input_variables=["query", "sql", "result"],
        )
        output_parser = StrOutputParser()
        chain = prompt | llm | output_parser

        # 3. 流式调用 LLM，边生成边通过 SSE 推送 chunk 给前端
        summary_chunks: list[str] = []
        input_data = {
            "query": query,
            "sql": sql,
            "result": json.dumps(sql_result, ensure_ascii=False, default=str),
        }

        # 先发送一个 summary_start 事件，让前端清空/准备展示区
        writer({"type": "summary", "status": "start"})

        async for chunk in chain.astream(input_data):
            if chunk:
                summary_chunks.append(chunk)
                writer({"type": "summary", "status": "streaming", "chunk": chunk})

        summary_text = "".join(summary_chunks).strip()

        # 4. 发送完成事件，并把完整总结也发一次，方便前端刷新显示
        writer(
            {
                "type": "summary",
                "status": "done",
                "text": summary_text,
            }
        )
        writer({"type": "progress", "step": step, "status": "success"})

        logger.info(f"总结结果：{summary_text}")
        return {"summary": summary_text}

    except Exception as e:
        # 5. 降级处理：总结失败不能影响主流程，只记录日志并发送 fail 事件
        logger.warning(f"[summarize_result] 总结失败（降级跳过）: {e}")
        writer({"type": "summary", "status": "error", "message": str(e)})
        writer({"type": "progress", "step": step, "status": "error"})
        # 不 raise，让图能正常走到 END
        return None
