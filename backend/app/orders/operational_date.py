"""Referencia de negocio por restaurante; nunca sustituye relojes de seguridad."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Pedido, Restaurante

OPERATIONAL_ZONE = ZoneInfo("America/Argentina/Buenos_Aires")


def operational_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Intervalo UTC semiabierto para filtrar un día local sin truncar la columna."""
    return (datetime.combine(day, time.min, OPERATIONAL_ZONE).astimezone(UTC),
            datetime.combine(day + timedelta(days=1), time.min, OPERATIONAL_ZONE).astimezone(UTC))


def operational_date(db: Session, restaurant_id: int) -> date | None:
    """Máxima fecha local persistida (Buenos Aires); sin pedidos devuelve None.

    Un restaurante inexistente es un error. El llamador debe pasar el ID del
    contexto autorizado; esta función interna no concede permisos ni usa hoy
    como sustituto silencioso de una historia vacía.
    """
    if isinstance(restaurant_id, bool) or not isinstance(restaurant_id, int) or restaurant_id <= 0:
        raise ValueError("Identificador de restaurante inválido.")
    if db.get(Restaurante, restaurant_id) is None:
        raise ValueError("Restaurante inexistente.")
    latest = db.scalar(select(func.max(Pedido.fecha_hora)).where(Pedido.id_restaurante == restaurant_id))
    if latest is None:
        return None
    if latest.tzinfo is None:  # Fixtures SQLite; PostgreSQL devuelve TIMESTAMPTZ.
        latest = latest.replace(tzinfo=UTC)
    return latest.astimezone(OPERATIONAL_ZONE).date()
