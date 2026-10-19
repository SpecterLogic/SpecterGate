from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict, EnvSettingsSource, DotEnvSettingsSource
from pydantic import model_validator


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BASE_DIR / "data" / "spectergate.db"
if not DEFAULT_DB.exists() and (BASE_DIR / "data" / "hamgara.db").exists():
    DEFAULT_DB = BASE_DIR / "data" / "hamgara.db"


class Settings(BaseSettings):
    """Runtime configuration, overridable with SPECTERGATE_* environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_prefix="SPECTERGATE_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "SpecterGate"
    version: str = "0.1.0"
    debug: bool = False
    api_prefix: str = "/api"

    secret_key: str = ""
    access_token_expire_minutes: int = 720
    algorithm: str = "HS256"

    database_url: str = f"sqlite:///{DEFAULT_DB.as_posix()}"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    admin_username: str = "admin"
    admin_password: str = ""
    session_cookie_secure: bool = True
    public_host: str = "127.0.0.1"
    subscription_base_url: str = ""

    xray_enabled: bool = True
    xray_binary: str = "xray"
    xray_config_path: str = str(BASE_DIR / "data" / "xray" / "config.json")
    xray_log_path: str = str(BASE_DIR / "data" / "xray" / "xray.log")
    xray_api_address: str = "127.0.0.1:10085"

    demo_data: bool = False
    node_heartbeat_timeout: int = 180

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        return (
            init_settings, env_settings, EnvSettingsSource(settings_cls, env_prefix="HAMGARA_"),
            dotenv_settings, DotEnvSettingsSource(settings_cls, env_file=str(BASE_DIR / ".env"), env_prefix="HAMGARA_"),
            file_secret_settings,
        )

    @model_validator(mode="after")
    def validate_secrets(self):
        weak = ("change-me", "replace-with", "change-this", "admin123")
        if len(self.secret_key) < 32 or any(value in self.secret_key.lower() for value in weak):
            raise ValueError("Set SPECTERGATE_SECRET_KEY to a random secret of at least 32 characters.")
        if len(self.admin_password) < 12 or any(value in self.admin_password.lower() for value in weak):
            raise ValueError("Set SPECTERGATE_ADMIN_PASSWORD to a unique password of at least 12 characters.")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def database_path(self) -> Path | None:
        if self.database_url.startswith("sqlite:///"):
            return Path(self.database_url.removeprefix("sqlite:///"))
        return None

    def ensure_directories(self) -> None:
        db_path = self.database_path
        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        Path(self.xray_config_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.xray_log_path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
