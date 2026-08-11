# SQL 向量缓存

> 对应源码：[app/services/sql_cache_service.py](file:///f:/code/ai/shop-query/app/services/sql_cache_service.py) | [app/entities/sql_cache_entry.py](file:///f:/code/ai/shop-query/app/entities/sql_cache_entry.py) | [app/api/routers/cache_router.py](file:///f:/code/ai/shop-query/app/api/routers/cache_router.py) | [frontend/src/App.tsx](file:///f:/code/ai/shop-query/frontend/src/App.tsx#L97-L113)

## 1. 概述

重复或高度相似的问题（如「统计华北销售额」vs「查一下华北的销售额」）不需要每次都走 LLM 生成 SQL。通过 Redis + 向量余弦相似度，对每次查询先尝试模糊命中缓存，命中时直接从缓存返回 SQL 和结果数据，**跳过整个 LangGraph 工作流**，响应时间从数秒降到 ~50ms。

## 2. 缓存命中流程

```
用户问题
   │
   ▼
QueryService.query()
   │
   ├─► step 1: _rewrite_query()  (多轮场景改写追问)
   │        │
   │        ▼
   │     rewritten_query  ← 用改写后的查询做语义匹配，保证一致性
   │
   ├─► step 2: _try_cache(rewritten_query)
   │        │
   │        ├─ 计算查询 embedding
   │        ├─ 扫描 Redis 中所有缓存向量，求余弦相似度
   │        ├─ 最高相似度 ≥ threshold?
   │        │     │
   │        │     ├─ 是 → 返回缓存条目，发送 cache_hit progress 事件，结束
   │        │     │       · 命中计数 +1
   │        │     │       · 重置 TTL
   │        │     │
   │        │     └─ 否 → 未命中计数 +1，继续走 LangGraph
   │        │
   └─► step 3: graph.astream() 正常执行工作流
            │
            ▼
         工作流完成，拿到 final_sql + final_result
            │
            └─► _save_cache() 写入缓存
                  · 查询 → embedding
                  · SQL + result + 元数据 → JSON
                  · TTL = redis.ttl（默认 86400 秒 = 1 天）
```

## 3. Redis 存储结构

使用三类 Key，前缀统一为 `sql_cache:`：

| Key 模式 | 类型 | 存储内容 |
|----------|------|----------|
| `sql_cache:data:<cache_id>` | String (JSON) | 缓存条目：query / sql / result / hit_count / created_at |
| `sql_cache:embeddings` | Hash | `field=cache_id`, `value=embedding JSON`（全量缓存向量索引） |
| `sql_cache:stats` | Hash | `hit` 命中次数 / `miss` 未命中次数 |

为什么不使用 Redis 原生 Vector Similarity Search (VSS)：
- 需要 Redis Stack + RediSearch 模块，部署复杂度上升
- 项目已有 Embedding 客户端和余弦相似度实现，缓存量不会极大（~千条级），O(n) 扫描可接受
- 后续如量涨起来，平滑迁移到 Qdrant / Redis VSS 即可（接口不变）

## 4. 相似度算法

**余弦相似度**（Cosine Similarity），结果范围 [0.0, 1.0]：

```python
@staticmethod
def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
```

**阈值配置**（`AppConfig.redis.similarity_threshold`）：
- 默认 `0.92`：语义基本一致才命中，避免误把不同问题命中
- 可根据业务严格度调：更高阈值（0.95+）更保守，更低阈值（0.85）更激进

## 5. 配置项

`AppConfig.redis`：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `host` | `localhost` | Redis 地址 |
| `port` | `6379` | 端口 |
| `db` | `0` | DB 编号 |
| `password` | `None` | 密码（可选） |
| `ttl` | `86400` | 缓存过期时间（秒），1 天 |
| `similarity_threshold` | `0.92` | 命中阈值，≥ 该值才返回 |

## 6. 前端缓存统计面板

侧边栏底部实时展示缓存运营数据，每 5 秒轮询一次 `/api/cache/stats`：

```
┌─ SQL 缓存 ────────────────────────┐
│  [命中率]  67.3%    [缓存条数]  45 │
│  [命中]      78    [未命中]     38 │
└───────────────────────────────────┘
   ↖ 小按钮可重置统计计数器
```

对应接口：
- `GET /api/cache/stats` → 返回 `{hit, miss, total, hit_rate, cache_count}`
- `POST /api/cache/stats/reset` → 清空 hit / miss 计数器

## 7. 与多轮会话的协作

- 缓存命中**也记录会话历史**（`_record_turn`），保证追问时上一轮的上下文完整
- 缓存命中后前端 `ChatMessage.cached = true`，StepRail 里显示「命中相似问题缓存」特殊步骤
- 用**改写后**的查询（rewritten_query）做匹配，避免同一会话里追问变形后匹配不到同一缓存
