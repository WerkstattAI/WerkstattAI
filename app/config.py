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
    default_workshop_id: str = _env("DEFAULT_WORKSHOP_ID", "demo-werkstatt") or "demo-werkstatt"
    database_url: str | None = _env("DATABASE_URL", None)
    auth_secret: str = _env("AUTH_SECRET", "dev-change-me") or "dev-change-me"
    dashboard_admin_email: str = _env("DASHBOARD_ADMIN_EMAIL", "admin@werkstatt.local") or "admin@werkstatt.local"
    dashboard_admin_password: str = _env("DASHBOARD_ADMIN_PASSWORD", "werkstatt123") or "werkstatt123"
    dashboard_admin_role: str = _env("DASHBOARD_ADMIN_ROLE", "admin") or "admin"
    trial_days: int = int(_env("TRIAL_DAYS", "14") or "14")
    whatsapp_verify_token: str | None = _env("WHATSAPP_VERIFY_TOKEN", None)
    whatsapp_app_secret: str | None = _env("WHATSAPP_APP_SECRET", None)
    whatsapp_default_phone_number_id: str | None = _env("WHATSAPP_DEFAULT_PHONE_NUMBER_ID", None)
    whatsapp_access_token: str | None = _env("WHATSAPP_ACCESS_TOKEN", None)
    whatsapp_graph_api_version: str = _env("WHATSAPP_GRAPH_API_VERSION", "v23.0") or "v23.0"

    # Optional for later AI features.
    openai_api_key: str | None = _env("OPENAI_API_KEY", None)


settings = Settings()
