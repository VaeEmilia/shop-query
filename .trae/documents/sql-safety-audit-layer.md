# SQL 安全审计层实现方案

## Context（背景）

当前项目的 SQL 执行链路存在安全隐患：`generate_sql` 节点用 LLM 生成 SQL 后，`validate_sql` 只用 `EXPLAIN` 校验语法/表名/字段名，`run_sql` + `DWMySQLRepository.run()` 直接执行裸 SQL。**没有任何安全校验**——LLM 若生成 `DROP TABLE`、`DELETE`、`INTO OUTFILE`、多语句或访问系统表的 SQL，都会被直接执行，造成数据泄露或破坏。

此外发现一个现有 graph 缺陷：[graph.py](file:///f:/code/ai/shop-query/app/agent/graph.py) 第 88 行 `correct_sql → run_sql` 直连，**correct_sql 修正后的 SQL 不经过任何重新校验就直接执行**，若 LLM 修正后仍有问题会直接抛异常。

本方案在 graph 链路中新增 `sql_safety_check` 节点，用 sqlglot 做 AST 级静态安全分析，并顺带修复上述校验循环缺陷。分支 `feature/sql-safety`，worktree 路径 `f:\code\ai\shop-query-sql-safety`。

## 已确认的设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| SQL 解析器 | **sqlglot** | 完整 AST、支持 MySQL 方言、原生检测多语句、可 AST 改写注入 LIMIT；sqlparse 仅 token 级，无法可靠区分 DDL |
| 节点位置 | **validate_sql 之前** | 纯内存校验（<10ms）快速失败，避免对 `DROP` 等 DDL 执行 `EXPLAIN`（行为未定义）；注入 LIMIT 后再 explain 更准确 |
| 重试机制 | **correct_sql → sql_safety_check 循环**，带 3 次重试上限 + recursion_limit 双保险 | 修复现有"correct_sql 不重新校验"缺陷；安全错误信息传给 LLM 修正 |
| 分层范围 | **只做 graph 节点**；repository 仅加超时控制，不加安全审计兜底 | 改动集中；执行超时属执行层职责，仍放 repository |
| 表白名单来源 | **配置文件**（显式表名 + 前缀模式），不从 meta 库读 | 安全层无 IO、无外部依赖、性能可控 |
| LIMIT 注入 | **AST 改写**，非字符串拼接 | 精确处理 UNION/CTE/子查询/已有 LIMIT，避免语法错误 |

## 改造后的执行链路

```
... → generate_sql → sql_safety_check →(error)→ correct_sql → sql_safety_check（循环）
                              →(ok)→ validate_sql →(error)→ correct_sql → sql_safety_check（循环）
                                                  →(ok)→ run_sql → END
```
- `sql_safety_check` 失败时把 `result.reason` 写入 `state["error"]`，条件边走 `correct_sql`
- `retry_count >= max_retry_count` 时硬失败，条件边走 END 并通过 stream_writer 推送 error 事件

## 文件清单

### 新增
| 文件 | 职责 |
|------|------|
| `app/core/sql_safety.py` | `SQLSafetyAuditor` 类（纯内存 AST 审计，无 IO）+ `SqlSafetyResult` dataclass + 模块级 `sql_safety_auditor` 单例 |
| `app/agent/nodes/sql_safety_check.py` | LangGraph 节点，调 auditor，写 `state["error"]`/`state["sql"]`(改写后)/`state["retry_count"]` |
| `tests/__init__.py` `tests/conftest.py` `tests/test_sql_safety.py` | 单元测试，fixture 用独立 config 不依赖 app_config 单例 |

### 修改
| 文件 | 修改内容 |
|------|----------|
| `app/conf/app_config.py` | 新增 `SqlSafetyConfig` dataclass，加到 `AppConfig` 聚合 |
| `conf/app_config.yaml` | 新增 `sql_safety` 配置段 |
| `app/agent/graph.py` | 注册 `sql_safety_check` 节点；边改造：`generate_sql→sql_safety_check`、`sql_safety_check` 条件边、`correct_sql→sql_safety_check`(替换原 `→run_sql`)、`compile(recursion_limit=20)` |
| `app/agent/state.py` | `DataAgentState` 新增 `retry_count: int` |
| `app/agent/nodes/correct_sql.py` | 返回值递增 `retry_count` |
| `app/repositories/mysql/dw/dw_mysql_repository.py` | `run()` 加查询超时（`execution_options(timeout=)` + `asyncio.wait_for` 兜底）；**不加安全审计** |
| `prompts/correct_sql.prompt` | 补充安全规则提示，降低 LLM 生成不安全 SQL 概率 |
| `pyproject.toml` | dependencies 加 `sqlglot>=26.0.0`；dev 组加 `pytest>=8.0.0` |

## 关键代码设计

### SqlSafetyConfig（app/conf/app_config.py）

```python
@dataclass
class SqlSafetyConfig:
    enabled: bool = True
    max_limit: int = 1000
    query_timeout: int = 30
    allowed_tables: list[str] = field(default_factory=list)          # 显式表名
    allowed_table_patterns: list[str] = field(default_factory=list)  # 前缀模式 dim_*/fact_*
    blocked_system_schemas: list[str] = field(default_factory=list)  # information_schema 等
    blocked_functions: list[str] = field(default_factory=list)       # LOAD_FILE/SLEEP/BENCHMARK
    max_retry_count: int = 3
```
yaml 段对应字段。前缀模式默认 `["dim_*", "fact_*", "dwd_*", "dws_*"]`（dw.sql 实际表为 `dim_region`/`fact_order` 等）。

### SQLSafetyAuditor（app/core/sql_safety.py）

```python
@dataclass
class SqlSafetyResult:
    passed: bool
    reason: str              # 面向 LLM 的简洁错误（通过时空串）
    transformed_sql: str     # LIMIT 注入后 SQL（失败时为原始 SQL）
    violations: list[str]    # 详细违规列表（日志/调试用）

class SQLSafetyAuditor:
    def __init__(self, config: SqlSafetyConfig): ...
    def audit(self, sql: str) -> SqlSafetyResult:
        # 顺序短路：空串 → 多语句(parse 返回多 stmt) → 语句类型(只 SELECT)
        # → 危险子句(INTO OUTFILE/LOAD DATA) → 危险函数 → 表白名单 → LIMIT 注入(AST 改写)
        ...
```
- 纯函数，无 IO，无副作用，并发安全（只读不可变 config）
- 模块级 `sql_safety_auditor = SQLSafetyAuditor(app_config.sql_safety)` 单例

### sql_safety_check 节点（app/agent/nodes/sql_safety_check.py）

- `enabled=False` 时直接放行
- 调 `auditor.audit(sql)`，通过则用 `transformed_sql` 覆盖 `state["sql"]`、清空 error
- 失败且 `retry_count >= max_retry_count`：写硬错误，stream_writer 推 `{"type":"error","message":...}`，条件边走 END
- 失败未超限：写 `result.reason` 到 error，走 correct_sql

### graph.py 边改造

```python
graph_builder.add_edge("generate_sql", "sql_safety_check")  # 替换原 →validate_sql
graph_builder.add_conditional_edges(
    "sql_safety_check",
    path=lambda s: ("validate_sql" if s["error"] is None
                    else ("correct_sql" if s.get("retry_count",0) < app_config.sql_safety.max_retry_count
                          else END)),
    path_map={"validate_sql":"validate_sql","correct_sql":"correct_sql", END:END},
)
# validate_sql 条件边保持（→run_sql 或 →correct_sql）
graph_builder.add_edge("correct_sql", "sql_safety_check")  # 替换原 →run_sql
graph = graph_builder.compile(recursion_limit=20)
```

### repository 超时（dw_mysql_repository.py run）

```python
import asyncio
async def run(self, sql: str) -> list[dict]:
    timeout = app_config.sql_safety.query_timeout
    result = await asyncio.wait_for(
        self.session.execute(text(sql), execution_options={"timeout": timeout}),
        timeout=timeout + 5,  # 让数据库 MAX_EXECUTION_TIME 先生效
    )
    return [dict(row) for row in result.mappings().fetchall()]
```

## 单元测试（tests/test_sql_safety.py）

覆盖场景（40 用例，分类）：
- **合法 SELECT**：单表/JOIN/子查询/CTE/UNION/聚合/表别名/大小写/反引号 → passed=True，验证 LIMIT 注入
- **LIMIT 处理**：无 LIMIT→注入 1000；已有 <max→保持；已有 >max→调整为 1000
- **DDL/DML 拦截**：DROP/DELETE/INSERT/UPDATE/TRUNCATE/ALTER/CREATE → passed=False
- **多语句**：`SELECT...; DROP...`、`SELECT...; SELECT...` → passed=False
- **危险子句/函数**：INTO OUTFILE/INTO DUMPFILE/LOAD_FILE/SLEEP/BENCHMARK/DATABASE → passed=False
- **表白名单**：系统表(information_schema/mysql/sys)、非白名单表 → passed=False；带库名前缀 `dw.dim_region` → passed=True
- **边界**：空串、纯分号、语法错误、注释注入（`-- ; DROP` 应通过）、enabled=False
- **性能**：1000 字符复杂 SELECT 断言 <10ms（`time.perf_counter`）

## 验证方式

1. **单测**：`cd f:\code\ai\shop-query-sql-safety && uv run pytest tests/test_sql_safety.py -v`（需先 `uv sync` 装依赖，worktree 写 .venv 需禁用沙箱）
2. **端到端**：启动后端（`start.bat` 或 `uv run python main.py`），通过前端问数界面测试：
   - 正常查询（"统计华北地区销售总额"）→ 应正常返回结果，日志显示"SQL安全校验通过"
   - 危险 SQL（构造 LLM 生成 DROP 的场景，或临时改 prompt）→ 应被拦截，前端展示安全错误
3. **配置开关**：`conf/app_config.yaml` 设 `sql_safety.enabled: false`，验证安全层可关闭
4. **超时**：构造慢查询（如对大表笛卡尔积）验证 30s 超时生效

## 风险与边界

- **sqlglot 解析失败**：catch `ParseError` 返回失败走 correct_sql；必要时调 `error_level=IGNORE`
- **LLM 生成 Markdown 代码块**：节点层做轻量 strip 预处理（去 ` ```sql ` 标记），auditor 保持纯函数
- **缓存命中绕过**：`QueryService` 缓存命中直接返回历史结果不重新执行，无执行风险；配置变更后需手动刷新 Redis 缓存
- **LIMIT 语义**：聚合查询(COUNT/SUM)不受影响；`SELECT *` 加 LIMIT 是安全护栏，前端提示"仅显示前 N 条"
- **性能**：sqlglot 解析典型 SELECT 1-3ms，复杂 3-6ms，AST 遍历 <0.5ms，<10ms 目标 99% 场景可达
- **重试耗尽**：hard-fail 走 END，stream_writer 推 error 事件，不写缓存

## 实施顺序

1. `pyproject.toml` 加依赖 → `uv sync`（禁用沙箱）
2. `app_config.py` + `app_config.yaml` 加 SqlSafetyConfig，验证加载
3. `app/core/sql_safety.py` 实现 auditor
4. `tests/` 写单测并跑通
5. `state.py` 加 retry_count
6. `sql_safety_check.py` 节点 + `correct_sql.py` 递增 retry
7. `graph.py` 注册节点 + 改造边
8. `dw_mysql_repository.py` 加超时
9. `correct_sql.prompt` 补安全提示
10. 端到端验证
