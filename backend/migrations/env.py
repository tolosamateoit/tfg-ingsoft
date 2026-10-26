"""Alembic: revisión offline sin conexión; acceso online requiere aprobación."""

from alembic import context
from alembic.util import CommandError

from app.db.base import Base
from app.db import models  # noqa: F401 - registrar las entidades del DER


def run_migrations_offline():
    # No leer el .env ni construir un engine para generar SQL de revisión.
    context.configure(
        dialect_name="postgresql",
        target_metadata=Base.metadata,
        version_table_schema="public",
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    if context.get_x_argument(as_dictionary=True).get("approved") != "true":
        raise CommandError(
            "Acceso online bloqueado. Revisar el esquema y obtener aprobación "
            "antes de usar -x approved=true. No se abrió ninguna conexión."
        )
    def migrate(connection):
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True, version_table_schema="public")
        with context.begin_transaction():
            context.run_migrations()

    # Permite pruebas con una conexión local descartable suministrada por el
    # runner; no necesita ni lee la configuración privada de Supabase.
    provided_connection = context.config.attributes.get("connection")
    if provided_connection is not None:
        migrate(provided_connection)
        return

    from app.db.engine import build_engine

    engine = build_engine()
    try:
        with engine.connect() as connection:
            migrate(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
