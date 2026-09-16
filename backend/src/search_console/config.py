from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    app_secret: str = "local-development-only"
    system_owner_username: str = "wulihongfeng"
    trust_proxy_auth: bool = False
    web_login_enabled: bool = True
    auth_htpasswd_path: Path = Path("/run/search-console-secrets/htpasswd")
    system_owner_username_path: Path = Path("/run/search-console-secrets/system-owner.username")
    auth_session_hours: int = Field(default=12, ge=1, le=168)
    auth_login_max_attempts: int = Field(default=8, ge=3, le=30)
    auth_login_window_seconds: int = Field(default=300, ge=60, le=3600)
    database_url: str = "postgresql+psycopg://search_app:search_app@localhost:5432/baidu_platform"
    redis_url: str = "redis://localhost:6379/0"
    search_schema: str = "search_marketing"
    platform_schema: str = "platform_core"
    baidu_application_code: str = "baidu_primary"
    baidu_app_code: str = "search"
    baidu_app_id: str = ""
    baidu_app_secret: str = ""
    baidu_oauth_callback_url: str = ""
    baidu_oauth_scope: str = ""
    baidu_oauth_platform_id: str = "4960345965958561794"
    baidu_oauth_authorize_url: str = "https://u.baidu.com/oauth/page/index"
    baidu_oauth_access_token_url: str = "https://u.baidu.com/oauth/accessToken"
    baidu_oauth_refresh_token_url: str = "https://u.baidu.com/oauth/refreshToken"
    baidu_oauth_user_info_url: str = "https://u.baidu.com/oauth/getUserInfo"
    frontend_base_url: str = "http://127.0.0.1:8280"
    baidu_writes_enabled: bool = False
    baidu_api_base_url: str = "https://api.baidu.com"
    baidu_write_timeout_seconds: float = Field(default=90, ge=20, le=300)
    platform_token_encryption_key: str = ""
    duckdb_path: Path = Path("data/search_analytics.duckdb")
    storage_root: Path = Path("storage")
    hduofen_username: str | None = None
    hduofen_password: str | None = None
    hduofen_session_encryption_key: str | None = None
    hduofen_capture_enabled: bool = False
    account_auto_elimination_enabled: bool = False
    creative_auto_rebuild_enabled: bool = False
    code_sync_enabled: bool = True
    code_sync_repository_path: Path = Path("/workspace")
    code_sync_repository_https_url: str = "https://github.com/whf6688/baidusembdx.git"
    code_sync_repository_ssh_url: str = "git@github.com:whf6688/baidusembdx.git"
    code_sync_remote: str = "origin"
    code_sync_branch: str = "main"
    code_sync_daily_time: str = "02:00"
    code_sync_ssh_key_path: Path = Path("/run/git-sync/id_ed25519")
    code_sync_known_hosts_path: Path = Path("/run/git-sync/known_hosts")
    code_sync_max_retries: int = Field(default=5, ge=0, le=10)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @property
    def effective_platform_database_url(self) -> str:
        # Search authorization is deliberately colocated in this project's
        # PostgreSQL instance. Never honor an external/e-commerce database URL.
        return self.database_url

    @field_validator("baidu_app_code")
    @classmethod
    def app_code_is_search(cls, value: str) -> str:
        if value != "search":
            raise ValueError("搜索项目必须使用 app_code=search")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
