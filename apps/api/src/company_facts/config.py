from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Company Facts Research"
    database_url: str = "sqlite:///./company_facts.sqlite3"
    sec_user_agent: str = ""
    api_cors_origins: str = "http://localhost:3000"
    data_dir: Path = Path("./data/sec")
    sec_requests_per_second: float = 8.0
    sync_poll_seconds: int = 30

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def sec_is_configured(self) -> bool:
        value = self.sec_user_agent.strip()
        return "@" in value and "example.com" not in value and len(value.split()) >= 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
