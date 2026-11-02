"""Procedencia de distancias importadas: los antiguos sorteos no son mediciones."""
from sqlalchemy import select
from app.db.models import HistorialPedido

PENDING_DISTANCE = 'Distancia pendiente de verificaci\u00f3n.'


def unconfirmed_distances(db, order_ids):
    if not order_ids:
        return set()
    return unconfirmed_events(db.execute(select(HistorialPedido.id_pedido, HistorialPedido.tipo_evento, HistorialPedido.detalle)
        .where(HistorialPedido.id_pedido.in_(order_ids), HistorialPedido.tipo_evento.in_(['registro', 'distancia']))
        .order_by(HistorialPedido.fecha_hora, HistorialPedido.id_historial)))


def unconfirmed_events(events):
    """Misma regla para eventos ya leídos y ordenados en esta solicitud."""
    unknown = set()
    for oid, kind, detail in events:
        if kind == 'registro' and (detail == 'Registro del pedido.' or PENDING_DISTANCE in (detail or '')):
            unknown.add(oid)
        elif kind == 'distancia':
            unknown.discard(oid)
    return unknown
