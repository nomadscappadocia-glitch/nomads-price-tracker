from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://hotelrate:hotelrate@localhost:5432/hotelrate"

    crawl_interval_minutes: int = Field(default=10, ge=1, le=120)
    crawl_concurrency: int = Field(default=4, ge=1, le=20)
    request_timeout_seconds: int = Field(default=25, ge=5, le=120)

    headless: bool = True
    demo_mode: bool = True
    playwright_user_data_dir: str = ""
    playwright_user_data_dir_trip: str = ""
    playwright_user_data_dir_booking: str = ""
    playwright_user_data_dir_agoda: str = ""
    playwright_user_data_dir_google_hotels: str = ""
    playwright_browser_channel: str = "chromium"
    playwright_disable_automation_flags: bool = True

    default_checkin_offset_days: int = Field(default=7, ge=0, le=365)
    default_length_of_stay: int = Field(default=1, ge=1, le=30)
    default_adults: int = Field(default=2, ge=1, le=8)
    default_children: int = Field(default=0, ge=0, le=6)

    target_city: str = ""
    firecrawl_base_url: str = "http://localhost:3002"
    firecrawl_timeout_seconds: int = Field(default=20, ge=3, le=120)
    firecrawl_enabled: bool = True
    firecrawl_api_key: str = ""
    firecrawl_fallback_for_live_quote: bool = True
    # Skip Google Hotels if Playwright keeps failing (Google often blocks automation)
    google_skip: bool = False
    url_mapping_cache_path: str = "reports/url_mapping_cache.json"
    # 当 Google 只拿到 fallback 时，是否把当前页面 HTML 存到 reports/ 便于对照选择器
    google_debug_save_html: bool = False
    booking_debug_save_json: bool = False
    agoda_debug_save_json: bool = False
    trip_debug_save_json: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
