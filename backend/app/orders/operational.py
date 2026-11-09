"""Vista operativa del día: lotes de lectura y ranking transitorio, sin escribir pedidos."""
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from app.auth.service import as_utc
from app.analytics.operational import owner_order_warnings
from app.couriers.schemas import CourierOutput
from app.couriers.service import list_couriers
from app.db.models import Cliente, HistorialPedido, Pedido, Restaurante
from app.logistics import priority as engine
from app.logistics.schemas import PriorityOutput
from app.orders.distance import unconfirmed_distances
from app.orders.operational_date import operational_date, operational_day_bounds
from app.orders.schemas import OrderSummary
from app.orders.service import order_summary, scoped_orders, state_since_query
from app.orders.summaries import summary_data


class OperatingOrder(OrderSummary):
    version: int
    distancia_km: Decimal | None
    direccion_entrega: str
    referencia_local: str | None
    prioridad: PriorityOutput | None = None


class OperatingDay(BaseModel):
    fecha_operativa: date | None = None
    abierto: bool = False
    actualizada_en: datetime
    activos: list[OperatingOrder] = []
    listos: list[OperatingOrder] = []
    en_entrega: list[OperatingOrder] = []
    finalizados: list[OperatingOrder] = []
    total_finalizados: int = 0
    limit: int = 20
    offset: int = 0
    repartidores: list[CourierOutput] = []


def operating_day(db, user, restaurant_id, limit=20, offset=0):
    if user.rol not in {'personal', 'propietario'} or user.id_restaurante != restaurant_id:
        raise HTTPException(403, 'No tenés permiso para gestionar estos pedidos.')
    day = operational_date(db, restaurant_id)
    now = engine.priority_time(db)
    result = OperatingDay(fecha_operativa=day, actualizada_en=now, limit=limit, offset=offset)
    courier_page = list_couriers(db, user)
    result.repartidores = courier_page.repartidores
    result.abierto = courier_page.abierto
    if day is None:
        return result
    start, end = operational_day_bounds(day)
    query = scoped_orders(user).where(Pedido.fecha_hora >= start, Pedido.fecha_hora < end)
    result.total_finalizados = db.scalar(select(func.count()).select_from(query.where(~Pedido.estado.in_(engine.ACTIVE)).subquery()))
    extended = query.add_columns(Restaurante.nombre, Cliente.nombre, state_since_query()).join(Restaurante)
    active = db.execute(extended.where(Pedido.estado.in_(engine.ACTIVE)).order_by(Pedido.fecha_hora, Pedido.id_pedido)).all()
    closed = db.execute(extended.where(~Pedido.estado.in_(engine.ACTIVE)).order_by(Pedido.fecha_hora.desc(), Pedido.id_pedido.desc())
                        .limit(limit).offset(offset)).all()
    rows = [*active, *closed]
    ids = [r[0].id_pedido for r in rows]
    details = summary_data(db, ids)
    warnings = owner_order_warnings(db, user, ids, reference_day=day, target_orders=[r[0] for r in rows])
    versions = dict(db.execute(select(HistorialPedido.id_pedido, func.max(HistorialPedido.id_historial))
                              .where(HistorialPedido.id_pedido.in_(ids)).group_by(HistorialPedido.id_pedido)).all()) if ids else {}
    unknown = unconfirmed_distances(db, ids)
    ranking = engine.ranked_snapshots([r[0] for r in active if r[0].estado in engine.PENDING], now, unknown)
    by_id = {o.id_pedido: engine.priority_output(o).model_copy(update={'posicion': i + 1}) for i, o in enumerate(ranking)}
    ready_ranking = engine.ranked_snapshots([r[0] for r in active if r[0].estado == 'Listo'], now, unknown)
    by_id.update({o.id_pedido: engine.priority_output(o).model_copy(update={'posicion': i + 1})
                  for i, o in enumerate(ready_ranking)})
    by_order = {}
    for order, restaurant, client, since in rows:
        summary = order_summary(order, restaurant, client, since).model_dump()
        summary.update(details[order.id_pedido])
        summary.update(warnings.get(order.id_pedido, {}))
        by_order[order.id_pedido] = OperatingOrder(**summary, version=versions.get(order.id_pedido, 0),
            distancia_km=order.distancia_km if order.id_pedido not in unknown else None, prioridad=by_id.get(order.id_pedido),
            direccion_entrega=order.direccion_entrega, referencia_local=order.referencia_local)
    result.activos = [by_order[o.id_pedido] for o in ranking]
    result.listos = [by_order[o.id_pedido] for o in ready_ranking]
    result.en_entrega = [by_order[r[0].id_pedido] for r in active if r[0].estado in {'Asignado', 'En camino'}]
    result.finalizados = [by_order[r[0].id_pedido] for r in closed]
    return result
