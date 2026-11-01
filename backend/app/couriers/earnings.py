"""Estimaciones diarias basadas en entregas finalizadas, no en fecha del pedido."""

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.auth.service import as_utc
from app.db.models import Entrega, HistorialPedido, Pedido, Repartidor

BUENOS_AIRES = timezone(timedelta(hours=-3))


def daily_earnings(db, user):
    today = as_utc(db.scalar(select(func.now()))).astimezone(BUENOS_AIRES).date()
    start = as_utc(datetime.combine(today, time.min, BUENOS_AIRES))
    end = start + timedelta(days=1)
    completed = select(HistorialPedido.id_pedido).where(
        HistorialPedido.tipo_evento == "entrega", HistorialPedido.estado == "Entregado",
        HistorialPedido.fecha_hora >= start, HistorialPedido.fecha_hora < end,
    )
    count, amount = db.execute(select(func.count(Entrega.id_entrega), func.sum(Entrega.costo_repartidor))
        .join(Pedido, Pedido.id_pedido == Entrega.id_pedido)
        .join(Repartidor, Repartidor.id_repartidor == Entrega.id_repartidor)
        .where(Repartidor.id_usuario == user.id_usuario, Pedido.id_restaurante == user.id_restaurante,
               Entrega.estado == "Entregado", Entrega.id_pedido.in_(completed))).one()
    return {"fecha": today, "zona_horaria": "America/Argentina/Buenos_Aires", "entregas_completadas": count,
            "importe_estimado": format(amount or Decimal(0), ".2f")}
