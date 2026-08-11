# 多轮对话与会话管理

> 对应源码：[app/services/session_service.py](file:///f:/code/ai/shop-query/app/services/session_service.py) | [app/services/query_service.py](file:///f:/code/ai/shop-query/app/services/query_service.py#L92-L167) | [app/repositories/mysql/meta/session_mysql_repository.py](file:///f:/code/ai/shop-query/app/repositories/mysql/meta/session_mysql_repository.py) | [frontend/src/App.tsx](file:///f:/code/ai/shop-query/frontend/src/App.tsx) | [frontend/src/components/SessionList.tsx](file:///f:/code/ai/shop-query/frontend/src/components/SessionList.tsx)

## 1. 概述

在单轮 Text-to-SQL 基础上，增加**按会话隔离的多轮问数**能力：
- 追问（如「那华东呢？」「按会员等级再拆一下」）通过 LLM 基于上下文自动改写为独立完整查询
- 每轮对话持久化到 MySQL，刷新页面 / 重启后端不丢失
- LangGraph 原生 MemorySaver 用 `thread_id=session_id` 实现按会话的检查点隔离
- 前端提供会话列表（新建/切换/重命名/删除），localStorage 缓存作为后端不可用时的降级

## 2. 整体架构

```
┌─────────────┐     session_id      ┌────────────────────┐    rewrite_query.prompt
│  前端 App   │ ──────────────────► │  QueryService      │ ──────────────────────► LLM
│  (React)    │                     │  _rewrite_query()  │   融合历史 + 当前追问
│             │ ◄────────────────── │                    │ ◄──────────────────────
│  · 会话列表 │     SSE 流 + 结果   │  graph.astream()   │   完整独立查询
│  · localStorage │                  │  _record_turn()   │
└─────────────┘                     └────────┬───────────┘
                                             │
                              ┌──────────────┴───────────────┐
                              ▼                              ▼
                    SessionService              LangGraph MemorySaver
                    (MySQL 持久化)              (thread_id=session_id)
                    session / session_turn      进程内检查点
```

## 3. 核心流程

### 3.1 问题改写（Query Rewriting）

**位置**：`QueryService._rewrite_query()`，在进入 LangGraph 工作流**之前**执行（不是图节点）。

```python
async def _rewrite_query(self, query: str, session_id: str) -> str:
    history = await self.session_service.get_history(session_id)
    if not history:
        return query  # 首轮无需改写
    history_text = self._format_history(history)
    # 调用 LLM 融合上下文
    chain = rewrite_prompt | llm | StrOutputParser()
    rewritten = await chain.ainvoke({"history": history_text, "query": query})
    return rewritten or query  # 空串兜底
```

**降级策略**：改写失败（任何异常）直接使用原始查询，不影响主流程，记录 warning 日志。

### 3.2 会话懒创建

首条问题提交时才调用后端创建会话，会话名取问题前 30 字，**避免产生空会话**。

```typescript
// frontend/src/App.tsx  startQuery()
let sessionId = currentSessionId;
if (!sessionId) {
  const session = await createSession(query.slice(0, 30));
  sessionId = session.id;
  // ... 更新列表和当前 ID
}
```

### 3.3 对话历史持久化

每轮结束后调用 `_record_turn()` 写入 MySQL，同时保存完整 `result` 数据，供切换会话时恢复表格渲染。

```python
turn = SessionTurn(
    query=original_query,
    rewritten_query=rewritten_query,
    sql=sql,
    result_summary=summary or self._fallback_summary(result),
    result=result,  # 完整结果 JSON
)
await self.session_service.add_turn(session_id, turn)
```

> **坑点提醒**：SQLAlchemy 的 `flush()` 只把 SQL 发到事务缓冲区，必须显式 `commit()` 才能真正落盘到 MySQL，否则重启后端会话就丢失。参见 [app/repositories/mysql/meta/session_mysql_repository.py](file:///f:/code/ai/shop-query/app/repositories/mysql/meta/session_mysql_repository.py) 中所有写操作都使用 `commit()`。

### 3.4 LangGraph MemorySaver 集成

```python
# graph.py 编译时挂载
memory_saver = MemorySaver()
graph = graph_builder.compile(checkpointer=memory_saver)

# query_service.py 调用时传 thread_id
thread_id = session_id or str(uuid.uuid4())
config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 25}
async for chunk in graph.astream(input=state, config=config, ...):
    ...
```

- 有 `session_id` → 按会话隔离检查点，多轮之间可以回溯状态
- 无 `session_id`（单轮查询）→ 生成临时 UUID，性能不受影响
- MemorySaver 是**进程内**存储，重启后清空；跨重启的历史回溯靠 MySQL 的 `session_turn` 表

## 4. 前端数据策略

采用「**localStorage 优先 + 后端权威兜底**」的双层策略，兼顾首屏速度和数据一致性：

| 场景 | 数据源 | 说明 |
|------|--------|------|
| 页面加载 | localStorage → 后端异步拉取 | 先立即显示缓存，再用后端权威数据覆盖 |
| 切换会话 | localStorage 立即显示 → 后端拉取完整 result | localStorage 可能缺 result，但渲染快 |
| 新消息写入 | state → useEffect 持久化到 localStorage | 每次 `messages` 变化同步写入 |
| 会话 CRUD | 后端 API 成功 → 同步更新 localStorage | 后端失败也清理本地，保证 UI 一致 |

## 5. 配置项

`AppConfig.session`：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `max_sessions` | `20` | 会话数量上限，超过自动清理最旧会话 |
| `history_turns` | `4` | 问题改写时取最近 N 轮历史（窗口不要太大，避免 prompt 超限） |
| `ttl` | `604800` | 会话过期时间（秒），7 天 |

## 6. 数据库表结构

```sql
-- 会话元数据
CREATE TABLE IF NOT EXISTS session (
    id            VARCHAR(64)  PRIMARY KEY,
    name          VARCHAR(255) NOT NULL,
    last_summary  TEXT,
    created_at    DATETIME     NOT NULL,
    updated_at    DATETIME     NOT NULL,
    INDEX idx_session_updated (updated_at DESC)
);

-- 会话轮次明细
CREATE TABLE IF NOT EXISTS session_turn (
    id              BIGINT       PRIMARY KEY AUTO_INCREMENT,
    session_id      VARCHAR(64)  NOT NULL,
    query           TEXT         NOT NULL,
    rewritten_query TEXT         NOT NULL,
    sql             TEXT,
    result_summary  TEXT,
    result          JSON,
    created_at      DATETIME     NOT NULL,
    INDEX idx_turn_session (session_id, created_at DESC),
    FOREIGN KEY (session_id) REFERENCES session(id) ON DELETE CASCADE
);
```

删除会话时，`ON DELETE CASCADE` 自动清理关联的所有轮次记录。
