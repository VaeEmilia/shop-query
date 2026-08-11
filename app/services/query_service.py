"""
问数查询服务

负责把 API 层传入的自然语言问题转换成一次 LangGraph 工作流执行：
创建初始 State、组装 Runtime Context、消费 graph.astream 的流式输出，
并统一包装成 SSE 文本返回给路由层。

新增能力：
  - 通过 Redis 向量缓存实现相似问题 SQL 直接命中，避免重复走 LLM 生成
  - 缓存未命中时正常执行 LangGraph 工作流，并在完成后自动写入缓存
"""

import json

from langchain_huggingface import HuggingFaceEndpointEmbeddings
from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.sql_cache_entry import SQLCacheEntry
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.services.sql_cache_service import SQLCacheService


class QueryService:
    """封装一次问数查询所需的业务编排逻辑，含缓存层"""

    def __init__(
        self,
        meta_mysql_repository: MetaMySQLRepository,
        embedding_client: HuggingFaceEndpointEmbeddings,
        dw_mysql_repository: DWMySQLRepository,
        column_qdrant_repository: ColumnQdrantRepository,
        metric_qdrant_repository: MetricQdrantRepository,
        value_es_repository: ValueESRepository,
        sql_cache_service: SQLCacheService,
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

    async def query(self, query: str):
        """执行一次问数工作流，并逐段产出 SSE 消息；优先命中缓存"""

        # 1. 先尝试缓存命中
        cached = await self._try_cache(query)
        if cached:
            # 缓存命中：直接返回结果，不再走 LangGraph
            logger.info(f"[QueryService] 缓存命中，直接返回结果: {cached.sql[:80]}...")
            yield f"data: {json.dumps({'type': 'progress', 'step': 'cache_hit', 'status': 'running', 'message': '命中相似问题缓存，直接返回结果'}, ensure_ascii=False, default=str)}\n\n"
            yield f"data: {json.dumps({'type': 'progress', 'step': 'cache_hit', 'status': 'completed'}, ensure_ascii=False, default=str)}\n\n"
            yield f"data: {json.dumps({'type': 'result', 'data': cached.result, 'sql': cached.sql}, ensure_ascii=False, default=str)}\n\n"
            return

        # 2. 缓存未命中：执行完整 LangGraph 工作流
        state = DataAgentState(query=query)
        context = DataAgentContext(
            column_qdrant_repository=self.column_qdrant_repository,
            embedding_client=self.embedding_client,
            metric_qdrant_repository=self.metric_qdrant_repository,
            value_es_repository=self.value_es_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository,
        )

        final_sql: str | None = None
        final_result: any = None

        try:
            async for chunk in graph.astream(
                input=state,
                context=context,
                stream_mode="custom",
                # recursion_limit 兜底防止 correct_sql ↔ sql_safety_check 循环无限执行，
                # 配合 sql_safety_check 节点的 max_retry_count 双保险
                config={"recursion_limit": 20},
            ):
                # 在流式过程中尝试捕获最终 SQL 和结果，用于后续缓存
                if isinstance(chunk, dict):
                    if chunk.get("type") == "result":
                        final_result = chunk.get("data")
                        final_sql = chunk.get("sql")
                yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:
            error = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error, ensure_ascii=False, default=str)}\n\n"
            return

        # 3. 工作流完成后，如果拿到了有效 SQL 和结果，写入缓存
        if final_sql and final_result is not None:
            try:
                embedding = await self._embed_query(query)
                await self._save_cache(query, embedding, final_sql, final_result)
                logger.info(f"[QueryService] 结果已写入缓存: {final_sql[:80]}...")
            except Exception as e:
                logger.warning(f"[QueryService] 缓存写入失败（不影响主流程）: {e}")
