"""Construcción diferida del engine, sin credenciales en archivos Alembic."""

from sqlalchemy import URL, create_engine
from sqlalchemy.pool import NullPool

from app.core.config import DatabaseSettings, get_database_settings


def build_engine(settings: DatabaseSettings | None = None):
    settings = settings or get_database_settings()
    # URL.create evita concatenar o codificar manualmente la contraseña.
    url = URL.create(
        "postgresql+psycopg",
        username=settings.user,
        password=settings.password,
        host=settings.host,
        port=settings.port,
        database=settings.dbname,
    )
    return create_engine(
        url,
        connect_args={
            "sslmode": "verify-full",
            "sslrootcert": settings.sslrootcert,
            "connect_timeout": settings.connect_timeout,
        },
        poolclass=NullPool,
        echo=False,
        hide_parameters=True,
    )
