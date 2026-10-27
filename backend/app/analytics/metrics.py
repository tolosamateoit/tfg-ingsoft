"""Períodos UTC explícitos; referencias anteriores y alertas identificadas por observación."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.forecast import utc_today
from app.analytics.schemas import AlertOutput, MetricsOutput, PeriodInput
from app.auth.service import as_utc
from app.couriers.service import list_couriers
from app.db.models import Alerta, HistorialPedido, Pedido, Usuario
from app.orders.service import lock_order_relations
from app.preparation.service import stock


def average(values):
    return sum(values, Decimal(0)) / len(values) if values else None


def minutes(start, end):
    delta = end - start
    return (Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / Decimal(1000000)) / 60


def observations(db: Session, restaurant_id: int, start: datetime, end: datetime):
    result = {"importe": [], "preparacion": [], "entrega": []}
    orders = db.execute(select(Pedido.id_pedido, Pedido.fecha_hora, Pedido.importe_total)
                        .where(Pedido.id_restaurante == restaurant_id, Pedido.fecha_hora >= start, Pedido.fecha_hora < end)).all()
    for id, timestamp, amount in orders:
        result["importe"].append((f"pedido:{id}", amount, as_utc(timestamp), f"Pedido #{id}, importe"))
    history = db.scalars(select(HistorialPedido).join(Pedido, Pedido.id_pedido == HistorialPedido.id_pedido)
                         .where(Pedido.id_restaurante == restaurant_id, HistorialPedido.fecha_hora < end)
                         .order_by(HistorialPedido.id_pedido, HistorialPedido.fecha_hora, HistorialPedido.id_historial)).all()
    preparation_start, delivery_start = {}, {}
    for event in history:
        timestamp = as_utc(event.fecha_hora)
        id = event.id_pedido
        if event.tipo_evento in {"preparacion", "nueva_preparacion"} and event.estado == "En preparación":
            preparation_start[id] = timestamp
        elif event.estado == "Listo" and id in preparation_start:
            duration = minutes(preparation_start.pop(id), timestamp)
            if timestamp >= start:
                result["preparacion"].append((f"evento:{event.id_historial}", duration, timestamp, f"Pedido #{id}, preparación #{event.id_historial}"))
        if event.tipo_evento == "entrega":
            if event.estado == "En camino":
                delivery_start[id] = timestamp
            elif event.estado in {"Entregado", "No entregado"} and id in delivery_start:
                began = delivery_start.pop(id)
                if event.estado == "Entregado" and timestamp >= start:
                    result["entrega"].append((f"evento:{event.id_historial}", minutes(began, timestamp), timestamp, f"Pedido #{id}, entrega #{event.id_historial}"))
    return result


def list_alerts(db: Session, restaurant_id: int) -> list[AlertOutput]:
    rows = db.scalars(select(Alerta).where(Alerta.id_restaurante == restaurant_id)
                      .order_by(Alerta.fecha_hora.desc(), Alerta.id_alerta.desc()).limit(100)).all()
    return [AlertOutput(id_alerta=row.id_alerta, tipo=row.tipo, descripcion=row.descripcion.partition(" | ")[2] or row.descripcion,
                        valor_observado=row.valor_observado, valor_referencia=row.valor_referencia,
                        fecha_hora=row.fecha_hora, estado=row.estado) for row in rows]


def metrics(db: Session, user: Usuario, restaurant_id: int, period: PeriodInput) -> MetricsOutput:
    if period.fin > utc_today(db):
        raise HTTPException(422, "El período no puede incluir días futuros.")
    length = (period.fin - period.inicio).days + 1
    try:
        reference_start = period.inicio - timedelta(days=length)
        reference_end = period.inicio - timedelta(days=1)
    except OverflowError:
        raise HTTPException(422, "El período no permite calcular una referencia anterior.") from None
    start = datetime.combine(period.inicio, datetime.min.time(), UTC)
    end = datetime.combine(period.fin + timedelta(days=1), datetime.min.time(), UTC)
    baseline_start = datetime.combine(reference_start, datetime.min.time(), UTC)
    lock_order_relations(db)
    samples = observations(db, restaurant_id, baseline_start, end)
    current, baseline = {}, {}
    for type, rows in samples.items():
        current[type] = [row for row in rows if row[2] >= start]
        baseline[type] = [row for row in rows if row[2] < start]
    means = {type: average([row[1] for row in rows]) for type, rows in current.items()}
    references = {type: average([row[1] for row in rows]) for type, rows in baseline.items()}
    stored = db.scalars(select(Alerta).where(Alerta.id_restaurante == restaurant_id).with_for_update()).all()
    by_key = {row.descripcion.partition(" | ")[0]: row for row in stored}

    def record(type, identity, value, threshold, label, anomalous):
        key = f"HU09:{type}:{identity}"
        alert = by_key.get(key)
        if not anomalous:
            if alert is not None:
                alert.estado = "Resuelta"
            return
        if alert is None:
            alert = Alerta(id_restaurante=restaurant_id, tipo=type, descripcion="", valor_observado=value,
                           valor_referencia=threshold, estado="Activa")
            db.add(alert)
            by_key[key] = alert
        alert.descripcion = f"{key} | {label}. Referencia: {reference_start} a {reference_end} UTC." if type != "stock" else f"{key} | {label}. Stock actual negativo."
        alert.valor_observado = value
        alert.valor_referencia = threshold
        alert.estado = "Activa"

    for type, rows in current.items():
        if references[type] is None:
            continue  # Sin referencia: no inventar umbrales ni resolver alertas anteriores.
        threshold = references[type] * Decimal("1.10")
        for identity, value, timestamp, label in rows:
            record(type, identity, value, threshold, f"{label}, observado {timestamp.isoformat()}", value > threshold)
    inventory = stock(db, restaurant_id)
    for row in inventory:
        record("stock", f"insumo:{row.id_insumo}", row.stock_actual, Decimal(0), row.nombre, row.stock_actual < 0)
    db.flush()
    result = MetricsOutput(inicio=period.inicio, fin=period.fin, referencia_inicio=reference_start, referencia_fin=reference_end,
                           promedios=means, muestras={type: len(rows) for type, rows in current.items()},
                           promedios_referencia=references, muestras_referencia={type: len(rows) for type, rows in baseline.items()},
                           stock=inventory, repartidores=list_couriers(db, user), alertas=list_alerts(db, restaurant_id))
    db.commit()
    return result
