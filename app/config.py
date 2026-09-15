from __future__ import annotations

import os
from dataclasses import dataclass


def _env(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key)
    return val if val is not None and val != "" else default


@dataclass(frozen=True)
class Settings:
    """Central configuration via environment variables."""

    app_name: str = _env("APP_NAME", "WerkstattAI Intake API") or "WerkstattAI Intake API"
    log_level: str = _env("LOG_LEVEL", "INFO") or "INFO"
    app_env: str = _env("APP_ENV", _env("RAILWAY_ENVIRONMENT_NAME", "development")) or "development"
    railway_environment: str = _env("RAILWAY_ENVIRONMENT_NAME", "") or ""
    cors_allowed_origins: str = _env("CORS_ALLOWED_ORIGINS", "") or ""
    trusted_proxy_cidrs: str = _env("TRUSTED_PROXY_CIDRS", "100.64.0.0/10" if _env("RAILWAY_ENVIRONMENT_NAME") else "") or ""
    rate_limit_requests_per_minute: int = int(_env("RATE_LIMIT_REQUESTS_PER_MINUTE", "300") or "300")
    rate_limit_chat_per_minute: int = int(_env("RATE_LIMIT_CHAT_PER_MINUTE", "30") or "30")
    rate_limit_login_per_minute: int = int(_env("RATE_LIMIT_LOGIN_PER_MINUTE", "5") or "5")
    rate_limit_webhook_per_minute: int = int(_env("RATE_LIMIT_WEBHOOK_PER_MINUTE", "600") or "600")
    default_workshop_id: str = _env("DEFAULT_WORKSHOP_ID", "demo-werkstatt") or "demo-werkstatt"
    demo_workshop_id: str = _env("DEMO_WORKSHOP_ID", "werkstattai-demo") or "werkstattai-demo"
    database_url: str | None = _env("DATABASE_URL", None)
    auth_secret: str = _env("AUTH_SECRET", "dev-change-me") or "dev-change-me"
    dashboard_admin_email: str = _env("DASHBOARD_ADMIN_EMAIL", "admin@werkstatt.local") or "admin@werkstatt.local"
    dashboard_admin_password: str = _env("DASHBOARD_ADMIN_PASSWORD", "werkstatt123") or "werkstatt123"
    dashboard_admin_role: str = _env("DASHBOARD_ADMIN_ROLE", "admin") or "admin"
    session_cookie_secure: str = _env("SESSION_COOKIE_SECURE", "auto") or "auto"
    trial_days: int = int(_env("TRIAL_DAYS", "14") or "14")
    whatsapp_verify_token: str | None = _env("WHATSAPP_VERIFY_TOKEN", None)
    whatsapp_app_secret: str | None = _env("WHATSAPP_APP_SECRET", None)
    whatsapp_default_phone_number_id: str | None = _env("WHATSAPP_DEFAULT_PHONE_NUMBER_ID", None)
    whatsapp_access_token: str | None = _env("WHATSAPP_ACCESS_TOKEN", None)
    whatsapp_graph_api_version: str = _env("WHATSAPP_GRAPH_API_VERSION", "v23.0") or "v23.0"
    whatsapp_webhook_public_url: str | None = _env("WHATSAPP_WEBHOOK_PUBLIC_URL", None)
    whatsapp_start_template_name: str | None = _env("WHATSAPP_START_TEMPLATE_NAME", None)
    whatsapp_start_template_language: str | None = _env(
        "WHATSAPP_START_TEMPLATE_LANGUAGE",
        None,
    )

    # Optional for later AI features.
    openai_api_key: str | None = _env("OPENAI_API_KEY", None)


settings = Settings()
