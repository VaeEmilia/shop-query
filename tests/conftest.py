"""pytest 公共 fixture

顶部先设置 LLM_API_KEY 环境变量，确保后续 import app.* 时
app_config 里 ${oc.env:LLM_API_KEY} 能正常解析（worktree 无 .env）。
"""

import os

# 必须在任何 app.* 导入之前设置，否则 OmegaConf 的 oc.env 解析会失败
os.environ.setdefault("LLM_API_KEY", "test")

import pytest  # noqa: E402

from app.conf.app_config import SqlSafetyConfig  # noqa: E402
from app.core.sql_safety import SQLSafetyAuditor  # noqa: E402


@pytest.fixture
def safety_config() -> SqlSafetyConfig:
    """独立的安全配置，不依赖 app_config 单例，测试可自由调整"""
    return SqlSafetyConfig(
        enabled=True,
        max_limit=1000,
        query_timeout=30,
        allowed_tables=[],
        allowed_table_patterns=["dim_*", "fact_*", "dwd_*", "dws_*"],
        blocked_system_schemas=[
            "information_schema",
            "mysql",
            "performance_schema",
            "sys",
        ],
        blocked_functions=[
            "LOAD_FILE",
            "SLEEP",
            "BENCHMARK",
            "USER",
            "CURRENT_SCHEMA",
            "CURRENT_USER",
            "CONNECTION_ID",
        ],
        max_retry_count=3,
    )


@pytest.fixture
def auditor(safety_config: SqlSafetyConfig) -> SQLSafetyAuditor:
    """用独立 config 构造的审计器实例，与模块级单例隔离"""
    return SQLSafetyAuditor(safety_config)
