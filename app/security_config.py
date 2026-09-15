from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from app.config import Settings

MAX_MESSAGE_LENGTH = 4096
MAX_ID_LENGTH = 128
MAX_PHONE_LENGTH = 32
MAX_PASSWORD_LENGTH = 128
MAX_BODY_BYTES = 64 * 1024
MAX_CHAT_BODY_BYTES = 32 * 1024
MAX_WEBHOOK_BODY_BYTES = 256 * 1024


def is_production(config: Settings) -> bool:
    return config.app_env.lower() in {"production", "staging"} or config.railway_environment.lower() == "production"


def allowed_origins(config: Settings) -> list[str]:
    origins = [value.strip() for value in config.cors_allowed_origins.split(",") if value.strip()]
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment or "*" in origin):
            raise ValueError("CORS_ALLOWED_ORIGINS muss konkrete Origins ohne Pfad oder Wildcard enthalten.")
        if is_production(config) and parsed.scheme != "https":
            raise ValueError("CORS_ALLOWED_ORIGINS muss in Produktion HTTPS verwenden.")
    return origins


def trusted_proxies(config: Settings) -> list:
    networks = [ipaddress.ip_network(value.strip()) for value in config.trusted_proxy_cidrs.split(",") if value.strip()]
    if any(network.prefixlen == 0 for network in networks):
        raise ValueError("TRUSTED_PROXY_CIDRS darf nicht das gesamte Internet freigeben.")
    return networks


def validate_security_settings(config: Settings) -> None:
    if config.app_env.lower() not in {"development", "test", "staging", "production"}:
        raise ValueError("APP_ENV muss development, test, staging oder production sein.")
    allowed_origins(config)
    trusted_proxies(config)
    for name in ("requests", "chat", "login", "webhook"):
        if getattr(config, f"rate_limit_{name}_per_minute") < 1:
            raise ValueError("Rate-Limits müssen größer als null sein.")
    if not is_production(config):
        return
    secret = config.auth_secret.strip()
    placeholders = ("change-me", "change-this", "changeme", "dev-change", "replace-me", "your-secret")
    if len(secret) < 32 or len(set(secret)) < 8 or any(value in secret.lower() for value in placeholders):
        raise ValueError("AUTH_SECRET muss in Produktion ein eigenes zufälliges Secret mit mindestens 32 Zeichen sein.")
    if config.session_cookie_secure.lower() not in {"auto", "true", "1", "yes", "on"}:
        raise ValueError("SESSION_COOKIE_SECURE darf in Produktion nicht deaktiviert sein.")
    if config.whatsapp_access_token and not config.whatsapp_app_secret:
        raise ValueError("WHATSAPP_APP_SECRET ist bei aktivierter WhatsApp-Anbindung erforderlich.")
    if config.whatsapp_app_secret and (len(config.whatsapp_app_secret) < 16 or "change" in config.whatsapp_app_secret.lower()):
        raise ValueError("WHATSAPP_APP_SECRET muss das eigene App-Secret von Meta sein.")


def validate_new_admin_password(config: Settings) -> None:
    if is_production(config) and (
        len(config.dashboard_admin_password) < 12
        or config.dashboard_admin_password.lower() in {"change-this-password", "werkstatt123"}
    ):
        raise ValueError("Ein neues Produktionskonto benötigt ein eigenes Admin-Passwort mit mindestens 12 Zeichen.")
