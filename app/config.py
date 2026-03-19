from __future__ import annotations

import os
from dataclasses import dataclass


def _env(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key)
    return val if val is not None and val != "" else default


@dataclass(frozen=True)
class Settings:
    """Zentrale Konfiguration via Umgebungsvariablen."""
    app_name: str = _env("APP_NAME", "WerkstattAI Intake API") or "WerkstattAI Intake API"
    log_level: str = _env("LOG_LEVEL", "INFO") or "INFO"

    # Optional für später (AI):
    openai_api_key: str | None = _env("OPENAI_API_KEY", None)


settings = Settings()
