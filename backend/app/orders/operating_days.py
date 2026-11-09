"""Fechas de apertura, sin intervalos ni escrituras en consultas analíticas."""
from datetime import datetime, timedelta
from sqlalchemy import func, select
from app.auth.service import as_utc
from app.db.models import DiaOperativo, Pedido, Restaurante
from app.orders.operational_date import OPERATIONAL_ZONE, operational_day_bounds

def local_today():
    return datetime.now(OPERATIONAL_ZONE).date()

def analysis_reference_date(db, restaurant_id):
    from app.orders.operational_date import operational_date
    order_day = operational_date(db, restaurant_id)
    today = local_today()
    last = db.scalar(select(func.max(DiaOperativo.fecha)).where(DiaOperativo.id_restaurante == restaurant_id,
                     DiaOperativo.fecha <= today))
    restaurant = db.get(Restaurante, restaurant_id)
    if last and restaurant and restaurant.abierto:
        last = today
    return max((day for day in (order_day, last) if day is not None), default=None)

def register_open_days(db, restaurant, today=None):
    """Con el restaurante bloqueado, completar los días desde la última apertura."""
    today = today or local_today()
    last = db.scalar(select(func.max(DiaOperativo.fecha)).where(
        DiaOperativo.id_restaurante == restaurant.id_restaurante, DiaOperativo.fecha <= today))
    start = last or today
    existing = set(db.scalars(select(DiaOperativo.fecha).where(DiaOperativo.id_restaurante == restaurant.id_restaurante,
        DiaOperativo.fecha >= start, DiaOperativo.fecha <= today)))
    for offset in range((today - start).days + 1):
        day = start + timedelta(days=offset)
        if day not in existing:
            db.add(DiaOperativo(id_restaurante=restaurant.id_restaurante, fecha=day))
    db.flush()

def operating_days(db, restaurant_id, start, end, *, today=None):
    """Incluye pedidos importados y apertura continua, sin modificar la base."""
    if start > end:
        return []
    today = today or local_today()
    days = set(db.scalars(select(DiaOperativo.fecha).where(DiaOperativo.id_restaurante == restaurant_id,
        DiaOperativo.fecha >= start, DiaOperativo.fecha <= end)))
    lower, _ = operational_day_bounds(start)
    _, upper = operational_day_bounds(end)
    for timestamp in db.scalars(select(Pedido.fecha_hora).where(Pedido.id_restaurante == restaurant_id,
            Pedido.fecha_hora >= lower, Pedido.fecha_hora < upper)):
        days.add(as_utc(timestamp).astimezone(OPERATIONAL_ZONE).date())
    restaurant = db.get(Restaurante, restaurant_id)
    if restaurant and restaurant.abierto:
        last = db.scalar(select(func.max(DiaOperativo.fecha)).where(DiaOperativo.id_restaurante == restaurant_id,
                         DiaOperativo.fecha <= today))
        if last:
            first, last_day = max(start, last), min(end, today)
            if first <= last_day:
                days.update(first + timedelta(days=i) for i in range((last_day - first).days + 1))
    return sorted(days)
