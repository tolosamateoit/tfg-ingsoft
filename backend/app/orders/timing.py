"""Tiempos derivados del historial persistido, sin escribir nuevos eventos."""

from decimal import Decimal

from app.auth.service import as_utc


def elapsed_minutes(start, end):
    return Decimal(str((as_utc(end) - as_utc(start)).total_seconds())) / 60


def order_times(order, history):
    since = order.fecha_hora
    preparation_start = delivery_start = None
    preparation_time = delivery_time = None
    for event in history:
        if event.tipo_evento == "distancia":
            continue
        if event.estado == order.estado:
            since = event.fecha_hora
        if event.tipo_evento in {"preparacion", "nueva_preparacion"} and event.estado == "En preparación":
            preparation_start = event.fecha_hora
            preparation_time = None
        elif event.estado == "Listo" and preparation_start:
            preparation_time = elapsed_minutes(preparation_start, event.fecha_hora)
            preparation_start = None
        if event.tipo_evento == "entrega":
            if event.estado == "En camino":
                delivery_start = event.fecha_hora
            elif event.estado in {"Entregado", "No entregado"} and delivery_start:
                delivery_time = elapsed_minutes(delivery_start, event.fecha_hora)
                delivery_start = None
    return since, preparation_time, delivery_time
