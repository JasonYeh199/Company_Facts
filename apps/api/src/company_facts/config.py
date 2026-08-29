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
    tiingo_api_token: str = ""
    tiingo_requests_per_hour: int = 45
    tiingo_history_years: int = 10
    tiingo_overlap_days: int = 10
    tiingo_base_url: str = "https://api.tiingo.com"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def sec_is_configured(self) -> bool:
        value = self.sec_user_agent.strip()
        return "@" in value and "example.com" not in value and len(value.split()) >= 2

    @property
    def tiingo_is_configured(self) -> bool:
        return len(self.tiingo_api_token.strip()) >= 16


@lru_cache
def get_settings() -> Settings:
    return Settings()
