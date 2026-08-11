"""SQLSafetyAuditor 单元测试

覆盖合法 SELECT、DDL/DML 拦截、多语句、危险函数/子句、表级白名单、
LIMIT 注入、边界情况和性能要求。
"""

import time

import sqlglot

from app.conf.app_config import SqlSafetyConfig
from app.core.sql_safety import SQLSafetyAuditor


def _limit_value(sql: str) -> int | None:
    """从 SQL 文本中解析 LIMIT 数值，无 LIMIT 返回 None"""
    stmt = sqlglot.parse_one(sql, dialect="mysql")
    limit = stmt.args.get("limit")
    if limit is None or limit.expression is None:
        return None
    try:
        return int(limit.expression.name)
    except (ValueError, TypeError):
        return None


# ---------------- 合法 SELECT ----------------


def test_simple_select(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM dim_region")
    assert r.passed
    assert _limit_value(r.transformed_sql) == 1000


def test_select_with_where(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM fact_order WHERE region='华北'")
    assert r.passed
    assert _limit_value(r.transformed_sql) == 1000


def test_join_query(auditor: SQLSafetyAuditor):
    sql = "SELECT a.*, b.region_name FROM fact_order a JOIN dim_region b ON a.region_id=b.region_id"
    r = auditor.audit(sql)
    assert r.passed
    assert _limit_value(r.transformed_sql) == 1000


def test_subquery(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM (SELECT * FROM dim_region) t")
    assert r.passed
    assert _limit_value(r.transformed_sql) == 1000


def test_cte(auditor: SQLSafetyAuditor):
    r = auditor.audit("WITH cte AS (SELECT * FROM dim_region) SELECT * FROM cte")
    assert r.passed
    assert _limit_value(r.transformed_sql) == 1000


def test_union(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM dim_region UNION SELECT * FROM dim_customer")
    assert r.passed
    assert _limit_value(r.transformed_sql) == 1000


def test_table_alias(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT t.* FROM dim_region t WHERE t.region_name='华北'")
    assert r.passed


def test_aggregation(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT region_name, COUNT(*) AS cnt FROM fact_order GROUP BY region_name")
    assert r.passed
    assert _limit_value(r.transformed_sql) == 1000


def test_uppercase_keywords(auditor: SQLSafetyAuditor):
    r = auditor.audit("select * from DIM_REGION")
    assert r.passed


def test_backtick_table(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM `dim_region`")
    assert r.passed


def test_db_prefixed_table(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM dw.dim_region")
    assert r.passed


# ---------------- LIMIT 处理 ----------------


def test_limit_below_max_kept(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM dim_region LIMIT 100")
    assert r.passed
    assert _limit_value(r.transformed_sql) == 100


def test_limit_equal_max_kept(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM dim_region LIMIT 1000")
    assert r.passed
    assert _limit_value(r.transformed_sql) == 1000


def test_limit_above_max_capped(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM dim_region LIMIT 5000")
    assert r.passed
    assert _limit_value(r.transformed_sql) == 1000


# ---------------- DDL/DML 拦截 ----------------


def test_drop_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("DROP TABLE dim_region")
    assert not r.passed
    assert "DROP" in r.reason or "Select" in r.reason or "SELECT" in r.reason


def test_delete_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("DELETE FROM dim_region WHERE region_id='R001'")
    assert not r.passed


def test_insert_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("INSERT INTO dim_region VALUES ('R999','test')")
    assert not r.passed


def test_update_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("UPDATE dim_region SET region_name='test' WHERE region_id='R001'")
    assert not r.passed


def test_truncate_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("TRUNCATE TABLE dim_region")
    assert not r.passed


def test_alter_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("ALTER TABLE dim_region ADD COLUMN test VARCHAR(50)")
    assert not r.passed


def test_create_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("CREATE TABLE test (id INT)")
    assert not r.passed


# ---------------- 多语句 ----------------


def test_multi_statement_with_drop(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM dim_region; DROP TABLE dim_region")
    assert not r.passed
    assert "多语句" in r.reason


def test_multi_statement_all_select(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM dim_region; SELECT * FROM dim_customer")
    assert not r.passed
    assert "多语句" in r.reason


# ---------------- 危险子句/函数 ----------------


def test_into_outfile_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM dim_region INTO OUTFILE '/tmp/x'")
    assert not r.passed
    assert "OUTFILE" in r.reason


def test_into_dumpfile_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM dim_region INTO DUMPFILE '/tmp/x'")
    assert not r.passed
    assert "DUMPFILE" in r.reason


def test_load_file_function_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT LOAD_FILE('/etc/passwd')")
    assert not r.passed
    assert "LOAD_FILE" in r.reason


def test_sleep_function_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT SLEEP(10) FROM dim_region")
    assert not r.passed
    assert "SLEEP" in r.reason


def test_benchmark_function_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT BENCHMARK(1000000, MD5('test'))")
    assert not r.passed
    assert "BENCHMARK" in r.reason


def test_database_function_blocked(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT DATABASE()")
    assert not r.passed
    assert "CURRENT_SCHEMA" in r.reason


# ---------------- 表级白名单 ----------------


def test_system_table_information_schema(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM information_schema.tables")
    assert not r.passed
    assert "系统库" in r.reason or "白名单" in r.reason


def test_system_table_mysql(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM mysql.user")
    assert not r.passed


def test_non_whitelisted_table(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELECT * FROM unknown_table")
    assert not r.passed
    assert "白名单" in r.reason


# ---------------- 边界情况 ----------------


def test_empty_sql(auditor: SQLSafetyAuditor):
    r = auditor.audit("")
    assert not r.passed
    assert "空" in r.reason


def test_semicolon_only(auditor: SQLSafetyAuditor):
    r = auditor.audit(";")
    assert not r.passed


def test_syntax_error(auditor: SQLSafetyAuditor):
    r = auditor.audit("SELEC * FROM dim_region")
    assert not r.passed
    assert "解析失败" in r.reason


def test_comment_injection_safe(auditor: SQLSafetyAuditor):
    # 注释里的 DROP 不应触发拦截，sqlglot 正确忽略注释
    r = auditor.audit("SELECT * FROM dim_region -- ; DROP TABLE x")
    assert r.passed


def test_disabled_config_passthrough(safety_config: SqlSafetyConfig):
    safety_config.enabled = False
    auditor = SQLSafetyAuditor(safety_config)
    # 即使是 DROP，关闭安全层后也直接放行（不改写）
    r = auditor.audit("DROP TABLE dim_region")
    assert r.passed
    assert r.transformed_sql == "DROP TABLE dim_region"


def test_explicit_allowed_table(safety_config: SqlSafetyConfig):
    # 显式白名单表名可命中，不依赖前缀模式
    safety_config.allowed_tables = ["special_table"]
    auditor = SQLSafetyAuditor(safety_config)
    r = auditor.audit("SELECT * FROM special_table")
    assert r.passed


# ---------------- 性能 ----------------


def test_performance_under_10ms(auditor: SQLSafetyAuditor):
    # 构造一个约 1000 字符的复杂 SELECT
    cols = ", ".join(f"a.col_{i}" for i in range(50))
    sql = f"SELECT {cols} FROM fact_order a JOIN dim_region b ON a.region_id=b.region_id WHERE a.amount>100"
    start = time.perf_counter()
    for _ in range(10):
        auditor.audit(sql)
    elapsed = (time.perf_counter() - start) / 10
    assert elapsed < 0.01, f"单次审计耗时 {elapsed*1000:.2f}ms 超过 10ms"
