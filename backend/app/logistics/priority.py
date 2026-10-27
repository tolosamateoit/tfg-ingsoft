"""Fórmula aprobada; valores decimales exactos y un único instante por recálculo."""

from datetime import datetime
from decimal import Decimal, localcontext

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.service import as_utc
from app.db.models import Pedido
from app.logistics.schemas import PriorityOutput, PriorityPage
from app.orders.service import lock_order_relations

ACTIVE = ("Nuevo", "En preparación", "Listo", "Asignado", "En camino")


def calculate(order: Pedido, now: datetime):
    age = as_utc(now) - as_utc(order.fecha_hora)
    minutes = max(0, (age.days * 86400 + age.seconds) // 60)
    with localcontext() as context:
        context.prec = 40
        distance = max(Decimal(0), Decimal(10) - order.distancia_km)
        gain = max(Decimal(0), (order.importe_total - order.costo_total) / Decimal(1000))
        order.puntaje_prioridad = Decimal(minutes) + distance + gain
    # JSON conserva decimales como texto; no convertir los cálculos a float.
    order.factores_prioridad = {"T": minutes, "D": format(distance, "f"), "G": format(gain, "f")}


def priority_output(order: Pedido) -> PriorityOutput:
    return PriorityOutput(id_pedido=order.id_pedido, fecha_hora=order.fecha_hora, estado=order.estado,
                          distancia_km=order.distancia_km, puntaje_prioridad=order.puntaje_prioridad,
                          factores_prioridad=order.factores_prioridad)


def refresh_priorities(db: Session, restaurant_id: int):
    lock_order_relations(db)
    orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == restaurant_id, Pedido.estado.in_(ACTIVE))
                        .order_by(Pedido.id_pedido).with_for_update()).all()
    now = as_utc(db.scalar(select(func.now())))
    for order in orders:
        calculate(order, now)
    orders.sort(key=lambda order: (-order.puntaje_prioridad, as_utc(order.fecha_hora), order.id_pedido))
    db.flush()
    return now, orders


def priorities(db: Session, restaurant_id: int) -> PriorityPage:
    now, orders = refresh_priorities(db, restaurant_id)
    result = PriorityPage(calculada_en=now, pedidos=[priority_output(order) for order in orders])
    db.commit()
    return result
