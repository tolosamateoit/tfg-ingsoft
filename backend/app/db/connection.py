"""Comprobación de PostgreSQL sin leer ni modificar tablas."""

import logging
import re
from urllib.parse import quote, quote_plus

import psycopg

from app.core.config import DatabaseSettings, get_database_settings

logger = logging.getLogger("uvicorn.error")


def _safe_connection_error(error: psycopg.Error, settings: DatabaseSettings) -> str:
    """Conservar el motivo técnico sin imprimir identificadores o credenciales."""
    message = str(error)
    sensitive_values = (
        settings.password, quote(settings.password, safe=""),
        quote_plus(settings.password), settings.host, settings.user,
        settings.dbname, settings.sslrootcert or "",
    )
    for value in sorted(set(sensitive_values), key=len, reverse=True):
        if value:
            message = message.replace(value, "[REDACTADO]")
    message = re.sub(r"postgres(?:ql)?://[^\s]+", "[CONEXION REDACTADA]", message)
    # libpq incluye IP, host, usuario y rutas entre comillas en sus diagnósticos.
    message = re.sub(r"\"[^\"\r\n]*\"|'[^'\r\n]*'", "[REDACTADO]", message)
    message = re.sub(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", "[IP]", message)
    return message


def check_database_connection() -> bool:
    settings = get_database_settings()
    # Una conexión por comprobación, cerrada al terminar. Los límites evitan
    # mantener solicitudes abiertas indefinidamente durante conexión o consulta.
    try:
        with psycopg.connect(
            host=settings.host,
            port=settings.port,
            dbname=settings.dbname,
            user=settings.user,
            password=settings.password,
            sslmode=settings.sslmode,
            sslrootcert=settings.sslrootcert or "",
            connect_timeout=settings.connect_timeout,
            options="-c statement_timeout=5000 -c default_transaction_read_only=on",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
    except psycopg.Error as error:
        # Sin traceback ni error crudo: únicamente el diagnóstico sanitizado
        # en la terminal de Uvicorn. La API mantiene su respuesta genérica.
        logger.error("PostgreSQL: %s: %s", type(error).__name__, _safe_connection_error(error, settings))
        raise
