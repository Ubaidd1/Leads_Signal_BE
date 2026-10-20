from functools import lru_cache
from typing import Annotated, Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "Hiring Intelligence API"
    log_level: str = "INFO"

    database_url: str
    test_database_url: str | None = None
    database_pool_size: int = 5
    database_max_overflow: int = 10

    frontend_base_url: str = "http://localhost:3000"
    trusted_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    session_cookie_name: str = "hi_session"
    csrf_cookie_name: str = "hi_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None
    session_idle_timeout_minutes: int = 720
    session_absolute_timeout_hours: int = 24
    session_remember_me_days: int = 30

    password_reset_ttl_minutes: int = 30
    invitation_ttl_days: int = 7
    password_min_length: int = 10

    allow_registration: bool = True
    email_backend: Literal["console"] = "console"

    login_rate_limit: int = 10
    login_rate_window_seconds: int = 300
    reset_rate_limit: int = 5
    reset_rate_window_seconds: int = 900

    max_page_size: int = 100
    default_page_size: int = 25

    @model_validator(mode="before")
    @classmethod
    def split_origins(cls, data):
        value = data.get("trusted_origins") if isinstance(data, dict) else None
        if isinstance(value, str):
            data["trusted_origins"] = [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
        return data

    @model_validator(mode="after")
    def check_production(self):
        if self.environment == "production":
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if self.email_backend == "console":
                raise ValueError("EMAIL_BACKEND=console is a development-only adapter; configure a real provider")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
