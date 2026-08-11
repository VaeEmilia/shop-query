"""
问数查询服务

负责把 API 层传入的自然语言问题转换成一次 LangGraph 工作流执行：
创建初始 State、组装 Runtime Context、消费 graph.astream 的流式输出，
并统一包装成 SSE 文本返回给路由层。

新增能力：
  - 通过 Redis 向量缓存实现相似问题 SQL 直接命中，避免重复走 LLM 生成
  - 缓存未命中时正常执行 LangGraph 工作流，并在完成后自动写入缓存
  - 多轮对话：携带 session_id 时拉取会话历史，通过 LLM 改写追问为完整查询，
    并在每轮结束后把对话片段写入会话历史，供后续轮次回溯
"""

import json
import uuid

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from loguru import logger

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.entities.session import SessionTurn
from app.entities.sql_cache_entry import SQLCacheEntry
from app.prompt.prompt_loader import load_prompt
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.services.session_service import SessionService
from app.services.sql_cache_service import SQLCacheService


class QueryService:
    """封装一次问数查询所需的业务编排逻辑，含缓存层和多轮会话上下文"""

    def __init__(
        self,
        meta_mysql_repository: MetaMySQLRepository,
        embedding_client: HuggingFaceEndpointEmbeddings,
        dw_mysql_repository: DWMySQLRepository,
        column_qdrant_repository: ColumnQdrantRepository,
        metric_qdrant_repository: MetricQdrantRepository,
        value_es_repository: ValueESRepository,
        sql_cache_service: SQLCacheService,
        session_service: SessionService,
    ):
        # MySQL 仓储分别负责元数据补全和真实数仓环境信息读取
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository

        # 召回链路依赖的向量检索、Embedding 和全文检索能力由依赖层注入
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.value_es_repository = value_es_repository

        # SQL 缓存服务（Redis 向量相似度匹配）
        self.sql_cache_service = sql_cache_service

        # 多轮会话管理服务（Redis 存储会话历史和元数据）
        self.session_service = session_service

    async def _embed_query(self, query: str) -> list:
        """把用户问题转成向量"""
        return await self.embedding_client.aembed_query(query)

    async def _try_cache(self, query: str) -> SQLCacheEntry | None:
        """尝试命中缓存，返回缓存条目或 None"""
        embedding = await self._embed_query(query)
        return await self.sql_cache_service.match(embedding)

    async def _save_cache(
        self, query: str, embedding: list, sql: str, result: any
    ) -> None:
        """把生成结果写入缓存"""
        entry = SQLCacheEntry(
            query=query,
            embedding=embedding,
            sql=sql,
            result=result,
        )
        await self.sql_cache_service.save(entry)

    # ------------------------------------------------------------------
    #  多轮对话：问题改写
    # ------------------------------------------------------------------

    async def _rewrite_query(self, query: str, session_id: str) -> str:
        """基于会话历史改写用户追问，返回包含完整上下文的独立查询

        首轮对话（无历史）直接返回原始查询；有历史时调用 LLM 融合上下文。
        改写失败时降级为原始查询，不影响主流程。
        """
        history = await self.session_service.get_history(session_id)
        if not history:
            # 首轮无需改写
            return query

        history_text = self._format_history(history)

        prompt = PromptTemplate(
            template=load_prompt("rewrite_query"),
            input_variables=["history", "query"],
        )
        chain = prompt | llm | StrOutputParser()
        rewritten = await chain.ainvoke({"history": history_text, "query": query})
        rewritten = rewritten.strip()

        # 模型可能偶发返回空串，兜底使用原始查询
        return rewritten or query

    @staticmethod
    def _format_history(turns: list[SessionTurn]) -> str:
        """把会话历史格式化为改写提示词可消费的文本块"""
        lines: list[str] = []
        for idx, turn in enumerate(turns, 1):
            lines.append(f"第{idx}轮：")
            lines.append(f"  用户问题：{turn.query}")
            lines.append(f"  完整查询：{turn.rewritten_query}")
            if turn.sql:
                lines.append(f"  生成SQL：{turn.sql}")
            if turn.result_summary:
                lines.append(f"  结果摘要：{turn.result_summary}")
        return "\n".join(lines)

    @staticmethod
    def _fallback_summary(result: any) -> str:
        """缓存命中或总结未开启时，用结果行数生成简短摘要"""
        if isinstance(result, list):
            return f"查询完成，共 {len(result)} 行结果"
        if result is not None:
            return "查询完成，已返回结果"
        return "查询完成"

    async def _record_turn(
        self,
        session_id: str | None,
        original_query: str,
        rewritten_query: str,
        sql: str | None,
        result: any,
        summary: str | None,
    ) -> None:
        """把本轮对话片段写入会话历史，供后续轮次改写时回溯

        同时保存完整 result 数据，供前端切换会话时恢复表格渲染。
        """
        if not session_id:
            return
        turn = SessionTurn(
            query=original_query,
            rewritten_query=rewritten_query,
            sql=sql,
            result_summary=summary or self._fallback_summary(result),
            result=result,
        )
        try:
            await self.session_service.add_turn(session_id, turn)
        except Exception as e:
            # 历史写入失败不影响主流程
            logger.warning(f"[QueryService] 会话历史写入失败: {e}")

    # ------------------------------------------------------------------
    #  主流程
    # ------------------------------------------------------------------

    async def query(self, query: str, session_id: str | None = None):
        """执行一次问数工作流，并逐段产出 SSE 消息

        携带 session_id 时先基于会话历史改写追问，使模糊的上下文依赖语句
        变成包含完整语义的独立查询，再进入缓存检测和 LangGraph 执行。
        """

        original_query = query
        rewritten_query = query

        # 1. 多轮上下文改写：把简短追问补全为独立查询
        if session_id:
            try:
                rewritten_query = await self._rewrite_query(query, session_id)
                if rewritten_query != query:
                    logger.info(
                        f"[QueryService] 问题改写: {query} -> {rewritten_query}"
                    )
            except Exception as e:
                logger.warning(f"[QueryService] 问题改写失败，使用原始查询: {e}")

        # 2. 先尝试缓存命中（基于改写后的查询，保证语义一致）
        cached = await self._try_cache(rewritten_query)
        if cached:
            logger.info(f"[QueryService] 缓存命中: {cached.sql[:80]}...")
            yield f"data: {json.dumps({'type': 'progress', 'step': 'cache_hit', 'status': 'running', 'message': '命中相似问题缓存，直接返回结果'}, ensure_ascii=False, default=str)}\n\n"
            yield f"data: {json.dumps({'type': 'progress', 'step': 'cache_hit', 'status': 'completed'}, ensure_ascii=False, default=str)}\n\n"
            yield f"data: {json.dumps({'type': 'result', 'data': cached.result, 'sql': cached.sql}, ensure_ascii=False, default=str)}\n\n"

            # 缓存命中也记录会话历史，保留追问上下文
            await self._record_turn(
                session_id, original_query, rewritten_query, cached.sql, cached.result, None
            )
            return

        # 3. 缓存未命中：执行完整 LangGraph 工作流
        state = DataAgentState(query=rewritten_query, session_id=session_id)
        context = DataAgentContext(
            column_qdrant_repository=self.column_qdrant_repository,
            embedding_client=self.embedding_client,
            metric_qdrant_repository=self.metric_qdrant_repository,
            value_es_repository=self.value_es_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository,
        )

        # 挂载了 MemorySaver 后必须提供 thread_id，多轮场景用 session_id 隔离检查点
        thread_id = session_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        final_sql: str | None = None
        final_result: any = None
        summary_text: str | None = None

        try:
            async for chunk in graph.astream(
                input=state, config=config, context=context, stream_mode="custom"
            ):
                # 在流式过程中尝试捕获最终 SQL、结果和总结，用于缓存和会话历史
                if isinstance(chunk, dict):
                    if chunk.get("type") == "result":
                        final_result = chunk.get("data")
                        final_sql = chunk.get("sql")
                    elif chunk.get("type") == "summary" and chunk.get("status") == "done":
                        summary_text = chunk.get("text")
                yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:
            error = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error, ensure_ascii=False, default=str)}\n\n"
            return

        # 4. 记录会话历史（多轮上下文回溯的依据）
        await self._record_turn(
            session_id, original_query, rewritten_query, final_sql, final_result, summary_text
        )

        # 5. 工作流完成后，如果拿到了有效 SQL 和结果，写入缓存
        if final_sql and final_result is not None:
            try:
                embedding = await self._embed_query(rewritten_query)
                await self._save_cache(rewritten_query, embedding, final_sql, final_result)
                logger.info(f"[QueryService] 结果已写入缓存: {final_sql[:80]}...")
            except Exception as e:
                logger.warning(f"[QueryService] 缓存写入失败（不影响主流程）: {e}")
