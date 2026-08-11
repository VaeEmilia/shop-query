# SQL 安全审计层

> 对应源码：[app/core/sql_safety.py](file:///f:/code/ai/shop-query/app/core/sql_safety.py) | [app/agent/nodes/sql_safety_check.py](file:///f:/code/ai/shop-query/app/agent/nodes/sql_safety_check.py) | [conf/app_config.yaml](file:///f:/code/ai/shop-query/conf/app_config.yaml)

## 1. 概述

在大模型生成 SQL 后、真正执行前，增加一道**纯内存 AST 静态审计**关卡，拦截 DDL/DML、危险函数、系统库访问和恶意多语句注入，并自动注入查询行数上限。审计失败时把明确的错误原因写回 `state["error"]`，由 `correct_sql` 节点指导 LLM 修正，形成「审计 → 修正 → 再审」的安全闭环。

## 2. 审计流程

```
generate_sql → sql_safety_check ──通过──→ validate_sql → run_sql
                     │
                     └─失败且未超限──→ correct_sql ──┘
                        (超限硬失败 → END)
```

**关键配置项**（在 `AppConfig.sql_safety` 中）：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | `bool` | `True` | 总开关，关闭时直接放行不改写 |
| `max_limit` | `int` | `1000` | 自动注入 LIMIT 上限，已有 LIMIT 超过则下调 |
| `query_timeout` | `int` | `30` | 查询执行超时（秒），DB 层 + asyncio 双保险 |
| `allowed_tables` | `list[str]` | `[]` | 表白名单（精确匹配） |
| `allowed_table_patterns` | `list[str]` | `[]` | 表名前缀模式，如 `dim_*` / `fact_*` |
| `blocked_system_schemas` | `list[str]` | `[]` | 禁止访问的系统库 |
| `blocked_functions` | `list[str]` | `[]` | 禁止的危险函数（大写存储） |
| `max_retry_count` | `int` | `3` | `correct_sql` 最大重试次数 |

## 3. 检查项（按危险程度短路返回）

| # | 检查项 | 实现方式 | 说明 |
|---|--------|----------|------|
| 1 | 空 SQL | 空串检查 | 直接失败 |
| 2 | 危险子句预检 | 正则关键词匹配 | `INTO OUTFILE` / `INTO DUMPFILE` / `LOAD DATA`（这些会让 sqlglot 解析失败，提前给出明确错误） |
| 3 | 语法正确性 | `sqlglot.parse()` | 语法错误走 `correct_sql` 修正 |
| 4 | 多语句执行 | `len(statements) > 1` | 即使都是 SELECT 也禁止，防止注入 |
| 5 | 语句类型白名单 | `isinstance(stmt, (Select, Union))` | 只允许查询，DDL/DML/Command 全拦截 |
| 6 | 危险函数 | `find_all(exp.Func)` | 遍历所有函数调用，命中 `blocked_functions` 即失败 |
| 7 | 表白名单 + 系统库 | `find_all(exp.Table)` | CTE 别名跳过白名单检查；系统库通过 `table.db` 或 `table.name` 双路径拦截 |
| 8 | LIMIT 注入 | AST 改写 `stmt.set("limit", ...)` | 无 LIMIT 注入 `max_limit`；已有超过则下调 |

## 4. 核心设计

### 4.1 审计器是纯同步纯函数

`SQLSafetyAuditor.audit(sql)` 全程**无 IO、无副作用**，输入输出均为字符串/数据类，典型耗时 <3ms。模块级单例 `sql_safety_auditor` 并发安全，无需加锁。

### 4.2 函数名提取的坑

`sqlglot` 把 `LOAD_FILE` / `SLEEP` / `BENCHMARK` 等不认识的函数解析成 `Anonymous`，此时 `sql_name()` 返回 `'ANONYMOUS'` 拿不到真实名字，必须回退用 `func.name` 属性。

```python
def _func_name(self, func: exp.Func) -> str:
    if isinstance(func, exp.Anonymous):
        return func.name.upper()
    return func.sql_name().upper()
```

### 4.3 CTE 别名不是真实表

WITH 子句定义的别名会被 `find_all(exp.Table)` 当成普通表引用，白名单校验前必须先收集 CTE 别名集合跳过。

```python
cte_names: set[str] = set()
for cte in stmt.find_all(exp.CTE):
    alias = cte.alias
    if alias:
        cte_names.add(str(alias).lower())
```

## 5. 在 LangGraph 工作流中的位置

> 源码：[app/agent/graph.py](file:///f:/code/ai/shop-query/app/agent/graph.py#L90-L122)

```python
graph_builder.add_edge("generate_sql", "sql_safety_check")

def _safety_route(state):
    if state["error"] is None:
        return "validate_sql"
    if state.get("retry_count", 0) < app_config.sql_safety.max_retry_count:
        return "correct_sql"
    return END

graph_builder.add_conditional_edges("sql_safety_check", _safety_route, ...)
graph_builder.add_edge("correct_sql", "sql_safety_check")  # 修正后重走安全校验
```

**注意事项：**
- `correct_sql` 节点必须在返回前**清空 `state["error"]`**，否则循环会被死锁在失败分支。
- 整张图设置 `recursion_limit=25` 作为兜底，防止极端情况下 validate ↔ correct ↔ safety 无限循环。
