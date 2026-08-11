# LangGraph 工作流优化

> 对应源码：[app/agent/graph.py](file:///f:/code/ai/shop-query/app/agent/graph.py) | [app/agent/nodes/correct_sql.py](file:///f:/code/ai/shop-query/app/agent/nodes/correct_sql.py) | [app/agent/state.py](file:///f:/code/ai/shop-query/app/agent/state.py)

## 1. 概述

原项目的 SQL 闭环是 `generate_sql → validate_sql → correct_sql → run_sql`，存在两个关键缺陷：
1. **缺少安全审计**：校验只看 SQL 语法，不检查 DDL/DML/系统库/危险函数，直接执行有风险
2. **循环方向错误**：`correct_sql` 后直接到 `run_sql`，修正后的 SQL 跳过了语法校验，可能把错误 SQL 送进数据库

本优化补齐安全层，重构 SQL 校验循环方向，并设置递归上限防止死循环。

## 2. 优化后的完整工作流图

```
START
  │
  ▼
extract_keywords  ──► 三路并行召回
  │                   ├─ recall_column  (Qdrant 向量：字段)
  │                   ├─ recall_value   (ES 全文：字段取值)
  │                   └─ recall_metric  (Qdrant 向量：指标)
  │                         │
  ▼                         ▼
merge_retrieved_info ◄──────┘
  │
  ├───────────────┐
  ▼               ▼
filter_table   filter_metric   (并行过滤)
  │               │
  └───────┬───────┘
          ▼
    add_extra_context   (补充日期/数据库/方言上下文)
          │
          ▼
    generate_sql  ──────────────────────────┐
          │                                  │
          ▼                                  │
  sql_safety_check  ◄──────────────────┐    │
     │    │                             │    │
     │    │  通过                       │    │
     │    └────────────────► validate_sql    │
     │                                  │    │
     │  失败未超限                     │ 通过 │ 失败
     │            correct_sql ◄────────┘    │
     │                  │                    │
     └──────────────────┘                    │
        (失败超限 → END)                     │
                                             ▼
                                          run_sql
                                             │
                                             ▼
                                     summarize_result
                                             │
                                             ▼
                                            END
```

## 3. SQL 安全 + 校验双循环

原流程有 **SQL 修正后直接执行** 的安全漏洞。优化后形成两层环路：

### 外层：安全校验循环（sql_safety ↔ correct_sql）

```
generate_sql → sql_safety_check
                     │
          ┌──────────┴──────────┐
          │ 通过                │ 失败且重试 < max_retry_count
          ▼                     ▼
     validate_sql          correct_sql
          │                     │
          │                     └──── 回到 sql_safety_check（重审修正结果）
          │
          ▼ （通过）
       run_sql
```

### 内层：语法校验循环（validate_sql ↔ correct_sql）

```
sql_safety_check (通过)
          │
          ▼
    validate_sql ──失败──► correct_sql
          │                    │
          │ 通过               └──► 回到 sql_safety_check
          ▼
       run_sql
```

**注意**：`correct_sql` 的出口统一回到 `sql_safety_check`（不是直接到 validate_sql 或 run_sql），保证修正结果**必须先过安全关**。

### 递归上限兜底

```python
# query_service.py
config = {
    "configurable": {"thread_id": thread_id},
    "recursion_limit": 25,   # 整张图最大节点跳转数
}
```

设置 `recursion_limit=25` 作为硬上限。正常场景（generate → safety → validate → run）只需 4 跳，25 的上限能容纳 5~7 次修正循环，足以覆盖 99.9% 情况，同时杜绝极端错误导致的图无限循环。

## 4. correct_sql 必须清空 error

> 源码：[app/agent/nodes/correct_sql.py](file:///f:/code/ai/shop-query/app/agent/nodes/correct_sql.py)

这是踩过的坑：`correct_sql` 节点修正 SQL 返回前，如果不把 `state["error"]` 清空，即使 SQL 已经对了，下一轮 `_safety_route` 看到 `error` 仍然非空，会判断为「失败且未超限 → 继续 correct_sql」，进入**死循环直到触发 recursion_limit**。

正确写法：
```python
async def correct_sql(state: DataAgentState, runtime: Runtime):
    error = state["error"]  # 先取错误原因，用于 Prompt
    sql = state["sql"]
    # ... 调用 LLM 修正 SQL ...
    corrected = ...

    # 关键：返回前清掉 error，同时 retry_count +1
    return {
        "sql": corrected,
        "error": None,          # ← 必须清空
        "retry_count": state.get("retry_count", 0) + 1,
    }
```

## 5. DataAgentState 新增字段

> 源码：[app/agent/state.py](file:///f:/code/ai/shop-query/app/agent/state.py)

```python
class DataAgentState(TypedDict):
    # ... 原有字段：query / sql / sql_result / error / 召回 / 过滤 等 ...
    session_id: str | None            # 新增：多轮会话 ID，MemorySaver thread_id
    retry_count: int                  # 新增：correct_sql 重试次数，超限硬失败
    summary: str | None               # 新增：自然语言总结文本（非流式版）
```

## 6. MemorySaver + thread_id

> 源码：[app/agent/graph.py](file:///f:/code/ai/shop-query/app/agent/graph.py#L46-L48)

```python
memory_saver = MemorySaver()                    # 模块级单例
graph = graph_builder.compile(checkpointer=memory_saver)

# 调用方必须传 thread_id
config = {"configurable": {"thread_id": session_id or uuid4()}}
async for chunk in graph.astream(input=state, config=config, context=context, ...):
    ...
```

- 有 `session_id` 时，LangGraph 按会话保存检查点，多轮之间状态可以回溯
- 无 `session_id`（单轮查询）时，临时生成 UUID，**性能与未挂载 MemorySaver 相当**，不会拖慢原流程
- **重要**：`graph.astream()` 的参数是 `(input=, config=, context=)` 三个关键字参数，不能位置传参；config 里的 `configurable.thread_id` 是必填项（只要编译时挂了 checkpointer）
