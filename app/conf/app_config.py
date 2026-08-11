"""
应用主配置

定义 conf/app_config.yaml 在程序中的结构化配置对象
项目启动后会在这里一次性完成配置文件加载和类型化转换，其他模块只需要导入 app_config
就可以按属性方式读取日志 MySQL Qdrant Embedding Elasticsearch 和 LLM 配置
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from omegaconf import OmegaConf


@dataclass
class File:
    """文件日志配置"""

    enable: bool
    level: str
    path: str
    rotation: str
    retention: str


@dataclass
class Console:
    """控制台日志配置"""

    enable: bool
    level: str


@dataclass
class LoggingConfig:
    """日志总配置"""

    file: File
    console: Console


@dataclass
class DBConfig:
    """MySQL 连接配置"""

    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass
class QdrantConfig:
    """Qdrant 连接与向量维度配置"""

    host: str
    port: int
    embedding_size: int


@dataclass
class EmbeddingConfig:
    """Embedding 服务配置"""

    host: str
    port: int
    model: str


@dataclass
class ESConfig:
    """Elasticsearch 配置"""

    host: str
    port: int
    index_name: str


@dataclass
class RedisConfig:
    """Redis 连接与缓存策略配置"""

    host: str
    port: int
    db: int
    password: Optional[str] = None
    ttl: int = 86400
    similarity_threshold: float = 0.92


@dataclass
class LLMConfig:
    """大模型调用配置"""

    model_name: str
    api_key: str
    base_url: str


@dataclass
class SqlSafetyConfig:
    """SQL 安全审计配置

    控制 sql_safety_check 节点和 DWMySQLRepository.run 的查询限制
    所有字段都有默认值，conf/app_config.yaml 缺失时也能安全回退
    """

    enabled: bool = True
    # 自动注入的 LIMIT 上限，已有 LIMIT 超过该值会被下调
    max_limit: int = 1000
    # 查询执行超时（秒），数据库层 MAX_EXECUTION_TIME + asyncio.wait_for 双保险
    query_timeout: int = 30
    # 显式白名单表名（精确匹配，大小写不敏感）
    allowed_tables: list[str] = field(default_factory=list)
    # 表名前缀模式，如 dim_* / fact_* / dwd_* / dws_*
    allowed_table_patterns: list[str] = field(default_factory=list)
    # 禁止访问的系统库，命中即拦截（information_schema / mysql / sys / performance_schema）
    blocked_system_schemas: list[str] = field(default_factory=list)
    # 禁止的危险函数名（大写存储，审计时函数名统一转大写比较）
    blocked_functions: list[str] = field(default_factory=list)
    # correct_sql 最大重试次数，超过后硬失败走 END
    max_retry_count: int = 3


@dataclass
class AppConfig:
    """项目级总配置入口"""

    logging: LoggingConfig
    db_meta: DBConfig
    db_dw: DBConfig
    qdrant: QdrantConfig
    embedding: EmbeddingConfig
    es: ESConfig
    redis: RedisConfig
    llm: LLMConfig
    sql_safety: SqlSafetyConfig = field(default_factory=SqlSafetyConfig)


# 从当前文件位置回到项目根目录，再定位到 conf/app_config.yaml
project_root = Path(__file__).parents[2]
config_file = project_root / "conf" / "app_config.yaml"

# 先读取本地 .env，让 YAML 中的 ${oc.env:...} 可以解析到敏感配置
load_dotenv(project_root / ".env")

# 读取 YAML 配置内容
context = OmegaConf.load(config_file)

# 根据 AppConfig 生成结构化配置 schema
schema = OmegaConf.structured(AppConfig)

# 把配置结构和配置值合并，再转换成可以直接按属性访问的对象
app_config: AppConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))

if __name__ == "__main__":
    # 简单测试：验证配置是否能正常读取
    print(app_config.es.host)
