"""Fórmula aprobada; valores decimales exactos y un único instante por recálculo."""

from datetime import datetime
from decimal import Decimal, localcontext

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.service import as_utc
from app.db.models import Pedido
from app.logistics.schemas import PriorityFactor, PriorityOutput, PriorityPage
from app.orders.service import lock_order_relations
from app.orders.summaries import summary_data
from app.orders.distance import unconfirmed_distances

ACTIVE = ("Nuevo", "En preparación", "Listo", "Asignado", "En camino")
PENDING = ('Nuevo', 'En preparación')


def priority_time(db):
    return as_utc(db.scalar(select(func.now())))


def calculate(order: Pedido, now: datetime, *, distance_known=True):
    age = as_utc(now) - as_utc(order.fecha_hora)
    minutes = max(0, (age.days * 86400 + age.seconds) // 60)
    with localcontext() as context:
        context.prec = 40
        distance = max(Decimal(0), Decimal(10) - order.distancia_km) if distance_known else None
        gain = max(Decimal(0), (order.importe_total - order.costo_total) / Decimal(1000))
        order.puntaje_prioridad = Decimal(minutes) + (distance or Decimal(0)) + gain
    # JSON conserva decimales como texto; no convertir los cálculos a float.
    order.factores_prioridad = {"T": minutes, "D": format(distance, "f") if distance is not None else None, "G": format(gain, "f")}


def priority_output(order: Pedido) -> PriorityOutput:
    values = order.factores_prioridad
    total = order.puntaje_prioridad
    factors = []
    margin = f'{order.importe_total - order.costo_total:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    descriptions = {
        'T': ('Tiempo de espera', f"{values['T']} min"),
        'D': ('Cercanía', f'{order.distancia_km} km registrados' if values['D'] is not None else 'Distancia no disponible'),
        'G': ('Margen estimado', f'$ {margin}'),
    }
    for code, (label, detail) in descriptions.items():
        amount = Decimal(values[code]) if values[code] is not None else None
        factors.append(PriorityFactor(codigo=code, nombre=label, aporte=amount,
            barra=(amount / total * 100).quantize(Decimal('.000001')) if amount and total else Decimal(0), detalle=detail))
    factors.sort(key=lambda f: -(f.aporte or Decimal(0)))
    largest = factors[0].aporte
    leading = [dict(T='su tiempo de espera', D='su cercanía', G='su margen estimado')[f.codigo]
               for f in factors if f.aporte == largest and largest and largest > 0]
    reason = ('Se priorizó principalmente por ' + ' y '.join(leading) + '.') if leading else 'Se ordenó por antigüedad del pedido.'
    return PriorityOutput(id_pedido=order.id_pedido, fecha_hora=order.fecha_hora, estado=order.estado,
                          distancia_km=order.distancia_km if values['D'] is not None else None, puntaje_prioridad=order.puntaje_prioridad,
                          factores_prioridad=values, factores=factors, explicacion=reason)


def page_output(db, now, orders):
    summaries = summary_data(db, [order.id_pedido for order in orders])
    return PriorityPage(calculada_en=now, pedidos=[priority_output(order).model_copy(update={
        'posicion': index + 1, 'resumen_productos': summaries[order.id_pedido]['resumen_productos'],
        'repartidor': summaries[order.id_pedido]['repartidor']}) for index, order in enumerate(orders)])


def ranked_snapshots(rows, now, unknown=()):
    # Instancias transitorias: calculate reutiliza la fórmula sin ensuciar filas persistidas.
    snapshots = [Pedido(id_pedido=o.id_pedido, fecha_hora=o.fecha_hora, estado=o.estado,
        distancia_km=o.distancia_km, importe_total=o.importe_total, costo_total=o.costo_total) for o in rows]
    for order in snapshots:
        calculate(order, now, distance_known=order.id_pedido not in unknown)
    snapshots.sort(key=lambda o: (-o.puntaje_prioridad, as_utc(o.fecha_hora), o.id_pedido))
    return snapshots


def priority_preview(db: Session, restaurant_id: int) -> PriorityPage:
    """Ranking de consulta: ni posiciones ni puntajes se escriben al leerlo."""
    rows = db.scalars(select(Pedido).where(Pedido.id_restaurante == restaurant_id, Pedido.estado.in_(PENDING))).all()
    now = priority_time(db)
    unknown = unconfirmed_distances(db, [o.id_pedido for o in rows])
    return page_output(db, now, ranked_snapshots(rows, now, unknown))


def refresh_priorities(db: Session, restaurant_id: int):
    lock_order_relations(db)
    orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == restaurant_id, Pedido.estado.in_(PENDING))
                        .order_by(Pedido.id_pedido).with_for_update()).all()
    now = priority_time(db)
    unknown = unconfirmed_distances(db, [o.id_pedido for o in orders])
    for order in orders:
        calculate(order, now, distance_known=order.id_pedido not in unknown)
    orders.sort(key=lambda order: (-order.puntaje_prioridad, as_utc(order.fecha_hora), order.id_pedido))
    db.flush()
    return now, orders


def priorities(db: Session, restaurant_id: int) -> PriorityPage:
    now, orders = refresh_priorities(db, restaurant_id)
    result = page_output(db, now, orders)
    db.commit()
    return result
