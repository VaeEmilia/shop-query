"""
SQL 安全审计

在 SQL 真正执行前做静态安全分析，基于 sqlglot AST 解析实现：
1. 只允许 SELECT（拦截 DROP/DELETE/INSERT/UPDATE/TRUNCATE/ALTER/CREATE 等所有 DDL/DML）
2. 拦截多语句执行，防止 SQL 注入
3. 拦截危险子句（INTO OUTFILE / INTO DUMPFILE / LOAD DATA）和危险函数（LOAD_FILE/SLEEP/...）
4. 表级白名单：只允许数仓事实表和维度表，禁止访问系统表（information_schema 等）
5. 自动注入 LIMIT 上限，已有 LIMIT 超过上限会被下调

审计器是纯内存无 IO 的同步函数，单次审计耗时不随数据量变化，典型 <3ms。
被 sql_safety_check 节点调用，失败时把原因写入 state["error"] 走 correct_sql 重试。
"""

import fnmatch
import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from app.conf.app_config import SqlSafetyConfig, app_config

# sqlglot 解析后允许作为顶层语句的类型：普通 SELECT 和 UNION
# CTE 的外层仍然是 Select，子查询的外层也是 Select，因此无需额外列举
_ALLOWED_STMT_TYPES = (exp.Select, exp.Union)

# 这些危险子句会让 sqlglot 直接抛 ParseError，提前用关键词预检给出明确错误
_DANGEROUS_CLAUSE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\binto\s+outfile\b", re.IGNORECASE), "INTO OUTFILE"),
    (re.compile(r"\binto\s+dumpfile\b", re.IGNORECASE), "INTO DUMPFILE"),
    (re.compile(r"\bload\s+data\b", re.IGNORECASE), "LOAD DATA"),
]


@dataclass
class SqlSafetyResult:
    """SQL 安全审计结果"""

    passed: bool
    # 面向 LLM 的简洁失败原因，通过时为空串，供 correct_sql 节点指导模型修正
    reason: str
    # LIMIT 注入后的 SQL；审计失败时为原始 SQL（未改写）
    transformed_sql: str
    # 详细违规列表，仅供日志和调试
    violations: list[str] = field(default_factory=list)


class SQLSafetyAuditor:
    """SQL 安全审计器：纯内存 AST 分析，无 IO，无副作用，并发安全"""

    def __init__(self, config: SqlSafetyConfig):
        self.config = config
        self._dialect = "mysql"
        # 配置中的表名/库名/函数名统一转小写，审计时比较也用小写，避免大小写差异漏判
        self._allowed_tables = {t.lower() for t in config.allowed_tables}
        self._allowed_patterns = [p.lower() for p in config.allowed_table_patterns]
        self._blocked_schemas = {s.lower() for s in config.blocked_system_schemas}
        self._blocked_functions = {f.lower() for f in config.blocked_functions}

    def audit(self, sql: str) -> SqlSafetyResult:
        """审计一条 SQL 的安全性，检查项按危险程度短路返回"""
        original = sql or ""

        # 配置开关关闭时直接放行，不改写 SQL
        if not self.config.enabled:
            return SqlSafetyResult(
                passed=True, reason="", transformed_sql=original
            )

        # 1. 空 SQL
        if not original.strip():
            return self._fail("SQL为空", original)

        # 2. 危险子句预检：这些子句会让 sqlglot 解析失败，提前给出明确错误
        for pattern, name in _DANGEROUS_CLAUSE_PATTERNS:
            if pattern.search(original):
                return self._fail(f"检测到危险子句 {name}，禁止导出文件或加载数据", original)

        # 3. 解析 SQL，语法错误走 correct_sql 让模型修正
        try:
            statements = sqlglot.parse(original, dialect=self._dialect)
        except sqlglot.errors.ParseError as e:
            return self._fail(f"SQL解析失败：{e}", original)

        # parse("") 返回 [None]，纯分号也返回 [None]
        if not statements or statements[0] is None:
            return self._fail("SQL为空", original)

        # 4. 多语句检测：parse 返回多个语句即拦截，即使都是 SELECT 也禁止
        if len(statements) > 1:
            return self._fail("检测到多语句执行，只允许单条 SELECT", original)

        stmt = statements[0]

        # 5. 语句类型白名单：只允许 SELECT/UNION，DDL/DML/Command 全部拦截
        if not isinstance(stmt, _ALLOWED_STMT_TYPES):
            stmt_type = type(stmt).__name__
            return self._fail(
                f"只允许 SELECT 查询，检测到 {stmt_type} 语句", original
            )

        # 6. 危险函数检测
        func_violation = self._check_dangerous_functions(stmt)
        if func_violation:
            return self._fail(func_violation, original)

        # 7. 表级白名单检测（含系统表拦截）
        table_violation = self._check_table_whitelist(stmt)
        if table_violation:
            return self._fail(table_violation, original)

        # 8. LIMIT 注入/调整（AST 改写）
        transformed = self._inject_limit(stmt)

        return SqlSafetyResult(
            passed=True, reason="", transformed_sql=transformed
        )

    def _fail(self, reason: str, original: str) -> SqlSafetyResult:
        """构造失败结果，reason 统一加前缀方便日志和前端识别"""
        return SqlSafetyResult(
            passed=False,
            reason=f"SQL安全校验失败：{reason}",
            transformed_sql=original,
            violations=[reason],
        )

    def _func_name(self, func: exp.Func) -> str:
        """提取函数名：Anonymous 函数用 name 属性，已知函数用 sql_name()

        sqlglot 把 LOAD_FILE/SLEEP/BENCHMARK 等不认识的函数解析成 Anonymous，
        此时 sql_name() 返回 'ANONYMOUS' 拿不到真实名字，需要用 name 属性。
        DATABASE() 会被解析成 CurrentSchema，sql_name() 返回 'CURRENT_SCHEMA'。
        """
        if isinstance(func, exp.Anonymous):
            return func.name.upper()
        return func.sql_name().upper()

    def _check_dangerous_functions(self, stmt: exp.Expression) -> str | None:
        """遍历所有函数调用，命中 blocked_functions 即返回违规原因"""
        hit = []
        for func in stmt.find_all(exp.Func):
            name = self._func_name(func)
            if name.lower() in self._blocked_functions:
                hit.append(name)
        if hit:
            return f"检测到危险函数 {','.join(sorted(set(hit)))}"
        return None

    def _check_table_whitelist(self, stmt: exp.Expression) -> str | None:
        """检测表引用是否在白名单内，是否命中系统库

        CTE 定义的别名（WITH cte AS ...）不是真实表，需要排除避免误拦。
        系统库通过 table.db 或 table.name 命中 blocked_system_schemas 拦截。
        """
        # 收集 CTE 别名，引用 CTE 的地方会被解析成 exp.Table，需跳过
        # sqlglot 30.x 把 WITH 子句存在 args["with_"]，CTE 节点挂在整棵树上
        cte_names: set[str] = set()
        for cte in stmt.find_all(exp.CTE):
            alias = cte.alias
            if alias:
                cte_names.add(str(alias).lower())

        for table in stmt.find_all(exp.Table):
            name = table.name
            db = table.db

            # 命中系统库（information_schema.tables 的 db=information_schema）
            if db and db.lower() in self._blocked_schemas:
                return f"禁止访问系统库 {db}"
            # 把系统库名当表名用的情况（SELECT * FROM information_schema）
            if name and name.lower() in self._blocked_schemas:
                return f"禁止访问系统库 {name}"

            # CTE 别名跳过白名单检查
            if name.lower() in cte_names:
                continue

            if not self._is_table_allowed(name):
                return f"表 {name} 不在白名单内，只允许查询数仓事实表和维度表"

        return None

    def _is_table_allowed(self, name: str) -> bool:
        """表名是否在显式白名单或匹配前缀模式"""
        if not name:
            return False
        lower = name.lower()
        if lower in self._allowed_tables:
            return True
        for pattern in self._allowed_patterns:
            # fnmatch 跨平台大小写行为不一致，手动转小写保证一致
            if fnmatch.fnmatch(lower, pattern):
                return True
        return False

    def _inject_limit(self, stmt: exp.Expression) -> str:
        """注入或调整 LIMIT（AST 改写），返回改写后的 SQL 文本

        - 无 LIMIT：注入 max_limit
        - 已有 LIMIT 且数值 > max_limit：下调为 max_limit
        - 已有 LIMIT 且 <= max_limit：保持不变
        UNION 查询的 LIMIT 在最外层，sqlglot 正确处理；子查询内的 LIMIT 不受影响。
        """
        max_limit = self.config.max_limit
        limit_node = stmt.args.get("limit")

        if limit_node is None:
            stmt.set("limit", exp.Limit(expression=exp.Literal.number(max_limit)))
        else:
            inner = limit_node.expression
            if inner is not None and isinstance(inner, exp.Literal):
                try:
                    current = int(inner.name)
                except (ValueError, TypeError):
                    current = None
                if current is not None and current > max_limit:
                    limit_node.set("expression", exp.Literal.number(max_limit))

        return stmt.sql(dialect=self._dialect)


# 模块级单例，供 sql_safety_check 节点直接导入使用
# auditor 只读不可变 config，audit 是纯函数，并发安全无需加锁
sql_safety_auditor = SQLSafetyAuditor(app_config.sql_safety)
