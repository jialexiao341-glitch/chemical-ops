"""从项目 .env 文件加载应用配置。"""

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """API 服务运行时配置。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "ChemicalOps"
    app_env: str = "development"
    debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8888
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    slow_request_ms: int = 1000
    db_slow_query_ms: int = 500

    database_url: str | None = None
    database_sync_url: str | None = None
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "chemicalops"
    mysql_user: str = "chemicalops"
    mysql_password: str = ""
    mysql_charset: str = "utf8mb4"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800
    db_echo: bool = False
    file_storage_root: str = "storage"
    file_storage_backend: str = "local"
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_secure: bool = False
    minio_region: str = "us-east-1"
    minio_bucket: str = "chemicalops-files"
    minio_document_bucket: str = "chemicalops-documents"
    minio_result_bucket: str = "chemicalops-results"
    document_max_size_mb: int = 50
    document_allowed_extensions: str = "pdf,doc,docx,xls,xlsx,ppt,pptx,csv,txt,png,jpg,jpeg"
    # MinerU 远程文档解析配置；密钥只从本地环境变量读取，OCR 仍由业务开关关闭。
    mineru_enabled: bool = False
    mineru_api_key: str = ""
    mineru_base_url: str = "https://mineru.net/api/v4"
    mineru_model_version: str = "vlm"
    mineru_language: str = "ch"
    mineru_timeout_seconds: int = 300
    mineru_poll_interval_seconds: float = 2.0
    mineru_max_retries: int = 2
    file_parse_stale_after_seconds: int = 900
    file_scan_enabled: bool = False
    file_scan_command: str = "clamdscan"
    file_scan_timeout_seconds: int = 30
    overdue_scan_interval_seconds: int = 900
    idempotency_required: bool = False

    jwt_secret_key: str = "CHANGE_ME_TO_A_LONG_RANDOM_SECRET"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    admin_username: str = "system_admin"
    admin_password: str = ""
    admin_display_name: str = "系统管理员"
    demo_default_password: str = ""

    # 大语言模型配置；默认使用 DeepSeek OpenAI 兼容接口。
    llm_provider: str = "openai_compatible"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 65536
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2
    agent_enabled: bool = True
    agent_allow_write_tools: bool = False
    agent_save_input_content: bool = False
    agent_save_output_content: bool = False

    @property
    def resolved_database_url(self) -> str:
        """优先根据 MYSQL_* 配置拼接同步 SQLAlchemy 连接地址。

        这样可以避免修改 .env 中的账号后，旧的 DATABASE_URL 仍然悄悄使用其他账号。
        """

        if self.mysql_user and self.mysql_password:
            user = quote_plus(self.mysql_user)
            password = quote_plus(self.mysql_password)
            database = quote_plus(self.mysql_database)
            return (
                f"mysql+pymysql://{user}:{password}@{self.mysql_host}:"
                f"{self.mysql_port}/{database}?charset={self.mysql_charset}"
            )
        if self.database_sync_url:
            return self.database_sync_url
        if self.database_url:
            return self.database_url.replace("mysql+asyncmy://", "mysql+pymysql://", 1)
        raise ValueError("Database configuration is missing")


@lru_cache
def get_settings() -> Settings:
    """返回缓存的应用配置实例。"""

    return Settings()
