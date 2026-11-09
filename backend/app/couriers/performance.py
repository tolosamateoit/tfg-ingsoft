"""Indicadores agregados, sin exponer historial de pedidos al propietario."""
from datetime import timedelta
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import exists, select
from app.auth.service import as_utc
from app.db.models import Entrega, HistorialPedido, Pedido, Repartidor, Usuario
from app.orders.operational_date import OPERATIONAL_ZONE, operational_day_bounds
from app.orders.operating_days import analysis_reference_date, operating_days

def performance(db, user, courier_id, selected=None):
    courier = db.execute(select(Repartidor, Usuario).join(Usuario).where(
        Repartidor.id_repartidor == courier_id, Usuario.id_restaurante == user.id_restaurante,
        Usuario.rol == 'repartidor')).first()
    if courier is None or (user.rol == 'repartidor' and courier[1].id_usuario != user.id_usuario):
        raise HTTPException(404, 'Repartidor no disponible.')
    from datetime import datetime
    today = datetime.now(OPERATIONAL_ZONE).date()
    selected = selected or analysis_reference_date(db, user.id_restaurante) or today
    start, _ = operational_day_bounds(min(today - timedelta(days=29), selected))
    rows = db.execute(select(Entrega, Pedido).join(Pedido).where(
        Entrega.id_repartidor == courier_id, Pedido.id_restaurante == user.id_restaurante,
        (Entrega.fecha_asignacion >= start) | (Pedido.fecha_hora >= start) |
        exists(select(HistorialPedido.id_historial).where(HistorialPedido.id_pedido == Pedido.id_pedido,
            HistorialPedido.tipo_evento == 'entrega', HistorialPedido.fecha_hora >= start)))).all()
    ids = [order.id_pedido for _, order in rows]
    events = db.execute(select(HistorialPedido.id_pedido, HistorialPedido.estado, HistorialPedido.fecha_hora)
        .where(HistorialPedido.id_pedido.in_(ids), HistorialPedido.tipo_evento == 'entrega')
        .order_by(HistorialPedido.fecha_hora, HistorialPedido.id_historial)).all() if ids else []
    history = {}
    for oid, state, when in events:
        history.setdefault(oid, {})[state] = as_utc(when)
    days = {today - timedelta(days=i): {'ganancias': Decimal(0), 'tiempos': []} for i in range(7)}
    open_days = set(operating_days(db, user.id_restaurante, today - timedelta(days=29), today))
    times, completed, finished = [], 0, 0
    assigned = delivered = 0
    earnings = Decimal(0)
    for delivery, order in rows:
        events_for_order = history.get(order.id_pedido, {})
        finish = events_for_order.get(delivery.estado) if delivery.estado in ('Entregado', 'No entregado') else None
        finish_day = finish.astimezone(OPERATIONAL_ZONE).date() if finish else None
        departure = events_for_order.get('En camino')
        minutes = (finish - departure).total_seconds() / 60 if finish and departure and delivery.estado == 'Entregado' and finish >= departure else None
        if finish_day in open_days and today - timedelta(days=29) <= finish_day <= today:
            finished += 1
            if delivery.estado == 'Entregado':
                completed += 1
                if minutes is not None: times.append(minutes)
        if finish_day in days and delivery.estado == 'Entregado':
            days[finish_day]['ganancias'] += delivery.costo_repartidor
            if minutes is not None and finish_day in open_days: days[finish_day]['tiempos'].append(minutes)
        if as_utc(order.fecha_hora).astimezone(OPERATIONAL_ZONE).date() == selected:
            assigned += 1
        if finish_day == selected and delivery.estado == 'Entregado':
            delivered += 1
            earnings += delivery.costo_repartidor
    mean = lambda values: round(sum(values) / len(values), 1) if values else None
    return {'fecha': selected, 'asignados': assigned, 'entregados': delivered, 'ganancia': str(earnings),
            'promedio_minutos': mean(times), 'tasa_completados': round(100 * completed / finished, 1) if finished else None,
            'evolucion': [{'fecha': day, 'ganancias': str(value['ganancias']), 'promedio_minutos': mean(value['tiempos'])}
                          for day, value in sorted(days.items())]}
