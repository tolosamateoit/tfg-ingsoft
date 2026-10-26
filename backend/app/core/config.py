"""Configuración privada de PostgreSQL, sin conexiones al importar el módulo."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


class DatabaseConfigurationError(ValueError):
    """Configuración ausente o inválida, sin incluir valores sensibles."""


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    dbname: str
    user: str
    password: str = field(repr=False)
    sslrootcert: str
    connect_timeout: int


def get_database_settings() -> DatabaseSettings:
    # El entorno del proceso tiene prioridad. Sin interpolación para no alterar
    # contraseñas que contengan expresiones como ${...}.
    values = {**dotenv_values(ENV_FILE, interpolate=False, encoding="utf-8"), **os.environ}
    required = ("PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGSSLROOTCERT")
    if any(not values.get(name) or not values[name].strip() for name in required):
        raise DatabaseConfigurationError("Falta completar la configuración de PostgreSQL.")

    try:
        port = int(values.get("PGPORT", "5432"))
        timeout = int(values.get("PGCONNECT_TIMEOUT", "5"))
    except (TypeError, ValueError):
        raise DatabaseConfigurationError("Puerto o tiempo de conexión inválido.") from None
    if not 1 <= port <= 65535 or not 1 <= timeout <= 30:
        raise DatabaseConfigurationError("Puerto o tiempo de conexión fuera de rango.")

    if values.get("PGSSLMODE", "verify-full") != "verify-full":
        raise DatabaseConfigurationError("La conexión requiere PGSSLMODE=verify-full.")

    certificate = Path(values["PGSSLROOTCERT"])
    if not certificate.is_absolute():
        certificate = BACKEND_DIR / certificate
    if not certificate.is_file():
        raise DatabaseConfigurationError("No se encuentra el certificado raíz de PostgreSQL.")

    return DatabaseSettings(
        host=values["PGHOST"].strip(),
        port=port,
        dbname=values["PGDATABASE"].strip(),
        user=values["PGUSER"].strip(),
        password=values["PGPASSWORD"],
        sslrootcert=str(certificate.resolve()),
        connect_timeout=timeout,
    )
