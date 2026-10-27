"""Configuración segura por defecto; HTTP permitido solo para loopback."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from dotenv import dotenv_values

from app.core.config import ENV_FILE


@dataclass(frozen=True)
class AuthSettings:
    allowed_origins: frozenset[str]
    cookie_secure: bool = True


def get_auth_settings() -> AuthSettings:
    values = {**dotenv_values(ENV_FILE, interpolate=False, encoding="utf-8"), **os.environ}
    secure = values.get("AUTH_COOKIE_SECURE", "true")
    origins = frozenset(s.strip() for s in values.get("AUTH_ALLOWED_ORIGINS", "").split(",") if s.strip())
    if secure not in {"true", "false"} or not origins:
        raise ValueError("Configuración de autenticación incompleta o inválida.")
    for origin in origins:
        parsed = urlsplit(origin)
        try:
            parsed.port
        except ValueError:
            raise ValueError("Origen de autenticación inválido.") from None
        if (not parsed.hostname or parsed.username or parsed.password or parsed.path
                or parsed.query or parsed.fragment or parsed.scheme not in {"http", "https"}):
            raise ValueError("Origen de autenticación inválido.")
        if secure == "false" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Las cookies sin Secure solo se permiten en desarrollo local.")
        if secure == "true" and parsed.scheme != "https":
            raise ValueError("Los orígenes de producción requieren HTTPS.")
    return AuthSettings(origins, secure == "true")
