"""Construcción diferida del engine, sin credenciales en archivos Alembic."""

from sqlalchemy import URL, create_engine

from app.core.config import DatabaseSettings, get_database_settings

# Por proceso: nunca más de tres conexiones, incluso ante una ráfaga de pedidos.
# pre_ping recupera conexiones cerradas por el pooler; recycle renueva las antiguas.
POOL_OPTIONS = dict(pool_size=3, max_overflow=0, pool_timeout=5,
                    pool_pre_ping=True, pool_recycle=240, pool_use_lifo=True)


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
            "sslmode": settings.sslmode,
            "sslrootcert": settings.sslrootcert or "",
            "connect_timeout": settings.connect_timeout,
        },
        **POOL_OPTIONS,
        echo=False,
        hide_parameters=True,
    )
