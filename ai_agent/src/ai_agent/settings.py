import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ai_agent"
    host: str = "0.0.0.0"
    port: int = 8088

    db_host: str = "db"
    db_port: int = 5432
    db_name: str = "ucp"
    db_user: str = "ucp_app"
    db_password: str = ""

    openai_api_key: str | None = None
    openai_model: str = "gpt-5.1"
    openai_timeout: int = 120
    ga_sos_timeout_ms: int = 30000

    google_cse_api_key: str | None = Field(default=None, alias="GOOGLE_CSE_API_KEY")
    google_cse_cx: str | None = Field(default=None, alias="GOOGLE_CSE_CX")
    google_cse_timeout: int = 15

    google_places_api_key: str | None = Field(default=None, alias="GOOGLE_PLACES_API_KEY")
    google_places_timeout: int = 10
    gsa_site_scanning_api_key: str = Field(default="DEMO_KEY", alias="GSA_SITE_SCANNING_API_KEY")

    web_scrape_enabled: bool = True
    web_scrape_timeout: int = 15
    web_scrape_max_pages: int = 3
    web_scrape_max_chars: int = 12000
    web_search_max_queries: int = 6

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        if not _settings.google_cse_api_key:
            _settings.google_cse_api_key = os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
        if not _settings.google_cse_cx:
            _settings.google_cse_cx = os.getenv("GOOGLE_CUSTOM_SEARCH_ENGINE_ID")
    return _settings
