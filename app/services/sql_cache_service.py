"""
SQL 缓存服务

基于 Redis 实现问题到 SQL 的缓存，通过向量相似度匹配支持模糊命中，
并维护命中率统计计数器。

存储结构：
  - sql_cache:data:<uuid>  -> 缓存条目 JSON（Hash）
  - sql_cache:embeddings   -> 所有缓存向量（Sorted Set，member=uuid, score=占位）
  - sql_cache:stats        -> 命中/未命中计数（Hash）
"""

import json
import math
import uuid
from typing import Any, List, Optional, Tuple

from app.conf.app_config import app_config
from app.core.log import logger
from app.entities.sql_cache_entry import SQLCacheEntry
from redis.asyncio import Redis


class SQLCacheService:
    """管理 SQL 缓存的读写、相似度匹配与统计"""

    KEY_PREFIX = "sql_cache:data"
    EMBEDDINGS_KEY = "sql_cache:embeddings"
    STATS_KEY = "sql_cache:stats"

    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.threshold = app_config.redis.similarity_threshold
        self.ttl = app_config.redis.ttl

    # ------------------------------------------------------------------
    #  向量工具
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """计算两向量的余弦相似度（结果范围 0.0 ~ 1.0）"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ------------------------------------------------------------------
    #  缓存读写
    # ------------------------------------------------------------------

    async def save(self, entry: SQLCacheEntry) -> str:
        """保存一条缓存，返回缓存 ID"""
        cache_id = str(uuid.uuid4())
        key = f"{self.KEY_PREFIX}:{cache_id}"
        data = json.dumps(entry.to_dict(), ensure_ascii=False, default=str)
        await self.redis.set(key, data, ex=self.ttl)

        # 同时把向量存入 embeddings 集合，方便后续全量扫描匹配
        # 用 uuid 作为 member，把向量拼接成字符串存到 score 不够精确，
        # 这里把 embedding 作为 value 另外存一个 Hash
        embedding_json = json.dumps(entry.embedding)
        await self.redis.hset(self.EMBEDDINGS_KEY, cache_id, embedding_json)

        logger.info(f"[SQLCache] 已保存缓存 {cache_id} for query: {entry.query[:40]}...")
        return cache_id

    async def get(self, cache_id: str) -> Optional[SQLCacheEntry]:
        """按 ID 读取缓存"""
        key = f"{self.KEY_PREFIX}:{cache_id}"
        data = await self.redis.get(key)
        if not data:
            return None
        return SQLCacheEntry.from_dict(json.loads(data))

    async def delete(self, cache_id: str) -> None:
        """删除缓存"""
        key = f"{self.KEY_PREFIX}:{cache_id}"
        await self.redis.delete(key)
        await self.redis.hdel(self.EMBEDDINGS_KEY, cache_id)

    # ------------------------------------------------------------------
    #  相似度匹配
    # ------------------------------------------------------------------

    async def match(self, query_embedding: List[float]) -> Optional[SQLCacheEntry]:
        """
        用余弦相似度在全量缓存中扫描最相似的条目，
        若超过阈值则返回并更新命中计数。
        """
        # 读取所有缓存向量
        embeddings_raw = await self.redis.hgetall(self.EMBEDDINGS_KEY)
        if not embeddings_raw:
            return None

        best_id: Optional[str] = None
        best_score = -1.0

        for cache_id, emb_json in embeddings_raw.items():
            stored_emb = json.loads(emb_json)
            score = self._cosine_similarity(query_embedding, stored_emb)
            if score > best_score:
                best_score = score
                best_id = cache_id

        if best_id is None or best_score < self.threshold:
            logger.info(f"[SQLCache] 未命中，最高相似度 {best_score:.4f} < 阈值 {self.threshold}")
            await self._incr_stat("miss")
            return None

        entry = await self.get(best_id)
        if entry is None:
            # 向量索引存在但数据已过期，清理残留索引
            await self.redis.hdel(self.EMBEDDINGS_KEY, best_id)
            await self._incr_stat("miss")
            return None

        # 更新命中次数并重置 TTL
        entry.hit_count += 1
        await self._update_entry(best_id, entry)
        await self._incr_stat("hit")

        logger.info(
            f"[SQLCache] 命中缓存 {best_id}，"
            f"相似度 {best_score:.4f}，原问题: {entry.query[:40]}..."
        )
        return entry

    # ------------------------------------------------------------------
    #  统计
    # ------------------------------------------------------------------

    async def get_stats(self) -> dict:
        """返回缓存命中率统计"""
        stats = await self.redis.hgetall(self.STATS_KEY)
        hit = int(stats.get("hit", 0))
        miss = int(stats.get("miss", 0))
        total = hit + miss
        return {
            "hit": hit,
            "miss": miss,
            "total": total,
            "hit_rate": round(hit / total, 4) if total > 0 else 0.0,
            "cache_count": len(await self.redis.hgetall(self.EMBEDDINGS_KEY)),
        }

    async def reset_stats(self) -> None:
        """重置统计计数器"""
        await self.redis.delete(self.STATS_KEY)

    # ------------------------------------------------------------------
    #  内部辅助
    # ------------------------------------------------------------------

    async def _incr_stat(self, field: str) -> None:
        await self.redis.hincrby(self.STATS_KEY, field, 1)

    async def _update_entry(self, cache_id: str, entry: SQLCacheEntry) -> None:
        key = f"{self.KEY_PREFIX}:{cache_id}"
        data = json.dumps(entry.to_dict(), ensure_ascii=False, default=str)
        await self.redis.set(key, data, ex=self.ttl)
