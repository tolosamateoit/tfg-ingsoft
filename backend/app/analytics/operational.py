"""Operational indicators and read-only anomaly analysis.

State-delay alerts use the selected-day averages shown in the dashboard. Delivery alerts keep the courier history reference.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import median, quantiles

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.auth.service import as_utc
from app.db.models import DetallePedido, DiaOperativo, Entrega, HistorialPedido, Pedido, Producto, Repartidor, Usuario
from app.orders.operational_date import operational_date, operational_day_bounds, OPERATIONAL_ZONE
from app.orders.operating_days import analysis_reference_date, operating_days


class OperationalAlert(BaseModel):
    clave: str
    tipo: str
    mensaje: str
    observado: Decimal
    habitual: Decimal | None = None
    umbral: Decimal | None = None
    antecedentes: int = 0
    id_pedido: int | None = None
    id_entrega: int | None = None
    fecha_pronostico: date | None = None
    demoras: list['StateDelay'] = []


class StateDelay(BaseModel):
    estado: str
    minutos: Decimal
    habitual: Decimal


class StateAverage(BaseModel):
    estado: str
    minutos: Decimal | None = None
    pedidos: int = 0


class SalesDay(BaseModel):
    fecha: date
    pedidos: int = 0
    ventas: Decimal = Decimal(0)
    proporcion: int = 0


class TopProduct(BaseModel):
    id_producto: int
    nombre: str
    cantidad: int


class OperationalDashboard(BaseModel):
    fecha_operativa: date | None = None
    fecha: date | None = None
    primera_fecha: date | None = None
    pedidos: int = 0
    ventas: Decimal = Decimal(0)
    ticket_promedio: Decimal | None = None
    pedidos_entregados: int = 0
    entrega_minutos: Decimal | None = None
    tiempos_promedio: list[StateAverage] = []
    entregas_con_tiempo: int = 0
    entregas_habituales: int = 0
    entregas_demoradas: int = 0
    entregas_sin_referencia: int = 0
    productos: list[TopProduct] = []
    evolucion: list[SalesDay] = []
    alertas: list[OperationalAlert] = []
    total_alertas: int = 0
    fecha_stock: date | None = None
    aviso_stock: str | None = None


def local_day(value):
    return as_utc(value).astimezone(OPERATIONAL_ZONE).date()


def rounded(value):
    return value.quantize(Decimal('.01'))


def robust_reference(values, minimum):
    if len(values) < minimum:
        return None
    center = Decimal(median(values))
    if center <= 0:
        return None
    q1, _, q3 = quantiles(values, n=4, method='inclusive')
    return center, max(center * Decimal('1.75'), q3 + 3 * (q3 - q1))


def amount_text(value):
    return '$ ' + f'{value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def quantity_text(value):
    return f'{value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.').rstrip('0').rstrip(',')


ORDER_STATES = ('Nuevo', 'En preparación', 'Listo', 'Asignado', 'En camino')


def percentile_95(values):
    """Rango más cercano: el valor en la posición ceil(0,95 × n)."""
    if len(values) < 20:
        return None
    values = sorted(values)
    return values[(95 * len(values) + 99) // 100 - 1]


def amount_p95_for_day(db, restaurant_id, day):
    """P95 de ventas entregadas en los 30 días operativos anteriores al pedido."""
    first_operating = db.scalar(select(func.min(DiaOperativo.fecha)).where(
        DiaOperativo.id_restaurante == restaurant_id))
    first_order = db.scalar(select(func.min(Pedido.fecha_hora)).where(
        Pedido.id_restaurante == restaurant_id))
    first = min([value for value in (first_operating, local_day(first_order) if first_order else None)
                 if value is not None], default=day)
    if day <= first:
        return None
    operating = operating_days(db, restaurant_id, first, day - timedelta(days=1))[-30:]
    if not operating:
        return None
    starts = operational_day_bounds(operating[0])[0]
    end = operational_day_bounds(day)[0]
    orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == restaurant_id,
        Pedido.estado == 'Entregado', Pedido.fecha_hora >= starts, Pedido.fecha_hora < end)).all()
    allowed = set(operating)
    return percentile_95([order.importe_total for order in orders if local_day(order.fecha_hora) in allowed])


def amount_alerts_for_orders(db, restaurant_id, targets):
    alerts = {}
    by_day = defaultdict(list)
    for order in targets:
        by_day[local_day(order.fecha_hora)].append(order)
    for day, orders in by_day.items():
        threshold = amount_p95_for_day(db, restaurant_id, day)
        if threshold is None:
            continue
        for order in orders:
            if order.importe_total > threshold:
                alerts[order.id_pedido] = OperationalAlert(clave=f'importe:{order.id_pedido}', tipo='importe',
                    id_pedido=order.id_pedido, observado=order.importe_total, habitual=threshold,
                    umbral=threshold, mensaje=f'Importe del pedido: {amount_text(order.importe_total)}. '
                    f'Referencia histórica (P95): {amount_text(threshold)}.')
    return alerts


def state_durations(db, orders, now):
    """Duraciones completas por pedido y estado, y estado actual verificable."""
    if not orders:
        return {}, {}
    rows = db.execute(select(HistorialPedido.id_pedido, HistorialPedido.fecha_hora,
                             HistorialPedido.estado, HistorialPedido.tipo_evento)
        .where(HistorialPedido.id_pedido.in_([order.id_pedido for order in orders]),
               HistorialPedido.fecha_hora <= now)
        .order_by(HistorialPedido.id_pedido, HistorialPedido.fecha_hora, HistorialPedido.id_historial)).all()
    events = defaultdict(list)
    for oid, when, state, kind in rows:
        if kind != 'distancia':
            events[oid].append((as_utc(when), state))
    completed, current = {}, {}
    for order in orders:
        previous, entered = None, None
        spans = defaultdict(list)
        for when, state in events[order.id_pedido]:
            if when < as_utc(order.fecha_hora):
                continue
            if state == previous:
                continue
            if previous in ORDER_STATES and entered is not None and when > entered:
                spans[previous].append((entered, when))
            previous, entered = state, when
        completed[order.id_pedido] = spans
        if previous == order.estado and previous in ORDER_STATES and entered is not None and now > entered:
            current[order.id_pedido] = (previous, entered)
    return completed, current


def state_delay_analysis(orders, spans, current, now):
    """Usa como referencia por estado el mismo promedio que ve el propietario."""
    daily_durations = {state: [] for state in ORDER_STATES}
    for order in orders:
        for state, durations in spans.get(order.id_pedido, {}).items():
            if durations:
                daily_durations[state].append(sum(
                    (Decimal(str((finish - begin).total_seconds())) / 60 for begin, finish in durations),
                    Decimal(0)))
    averages = {state: sum(values, Decimal(0)) / len(values) if values else None
                for state, values in daily_durations.items()}
    delays = defaultdict(list)
    for order in orders:
        for state in ORDER_STATES:
            durations = [Decimal(str((finish - begin).total_seconds())) / 60
                         for begin, finish in spans.get(order.id_pedido, {}).get(state, [])]
            ongoing = current.get(order.id_pedido)
            if ongoing and ongoing[0] == state:
                durations.append(Decimal(str((now - ongoing[1]).total_seconds())) / 60)
            average = averages[state]
            habitual = rounded(average) if average is not None else None
            total = sum(durations, Decimal(0))
            if durations and habitual is not None and total > habitual * Decimal('1.5'):
                delays[order.id_pedido].append(StateDelay(estado=state, minutos=rounded(total),
                                                           habitual=rounded(habitual)))
    return daily_durations, averages, delays


def _state_delay_message(order_id, delay):
    return (f"Alerta: pedido #{order_id} demorado. "
            f"Lleva {quantity_text(delay.minutos)} minutos; el promedio para el estado {delay.estado} "
            f"es {quantity_text(delay.habitual)} minutos.")


@dataclass(frozen=True)
class DeliverySample:
    order_id: int
    delivery_id: int
    courier_id: int
    began: datetime
    ended: datetime
    duration: Decimal


def delivery_samples(db, restaurant, cutoff, *, courier_order_ids=None):
    query = select(Entrega.id_pedido, Entrega.id_entrega, Entrega.id_repartidor, Entrega.fecha_asignacion)
    if courier_order_ids is not None:
        if not courier_order_ids:
            return []
        query = query.where(Entrega.id_repartidor.in_(select(Entrega.id_repartidor)
            .where(Entrega.id_pedido.in_(courier_order_ids)).correlate(None)))
    deliveries = db.execute(query
        .join(Pedido, Pedido.id_pedido == Entrega.id_pedido)
        .join(Repartidor, Repartidor.id_repartidor == Entrega.id_repartidor)
        .join(Usuario, Usuario.id_usuario == Repartidor.id_usuario)
        .where(Pedido.id_restaurante == restaurant, Usuario.id_restaurante == restaurant,
               Entrega.estado == 'Entregado', Pedido.estado == 'Entregado', Pedido.fecha_hora < cutoff)).all()
    by_order = {r.id_pedido: r for r in deliveries}
    if not by_order:
        return []
    events = db.execute(select(HistorialPedido.id_pedido, HistorialPedido.estado, HistorialPedido.fecha_hora)
        .where(HistorialPedido.id_pedido.in_(by_order), HistorialPedido.tipo_evento == 'entrega',
               HistorialPedido.fecha_hora < cutoff)
        .order_by(HistorialPedido.fecha_hora, HistorialPedido.id_historial)).all()
    began, samples = {}, {}
    for order_id, state, timestamp in events:
        timestamp = as_utc(timestamp)
        delivery = by_order[order_id]
        if timestamp < as_utc(delivery.fecha_asignacion):
            continue
        if state == 'En camino':
            began[order_id] = timestamp
            samples.pop(order_id, None)
        elif state in {'Entregado', 'No entregado'}:
            start = began.pop(order_id, None)
            samples.pop(order_id, None)
            if state == 'Entregado' and start is not None and timestamp > start:
                samples[order_id] = DeliverySample(order_id, delivery.id_entrega, delivery.id_repartidor,
                    start, timestamp, Decimal(str((timestamp - start).total_seconds())) / 60)
    return sorted(samples.values(), key=lambda r: (r.ended, r.delivery_id))


def detect_alerts(orders, samples, *, target_ids=None):
    """Devuelve evidencias por pedido y clasificación de entregas con referencia."""
    amount_alerts, delay_alerts, classified = {}, {}, {}
    delivered = defaultdict(list)
    grouped = defaultdict(list)
    for order in orders:
        grouped[local_day(order.fecha_hora)].append(order)
        if order.estado == 'Entregado' and order.importe_total > 0:
            delivered[local_day(order.fecha_hora)].append(order.importe_total)
    for day, daily in grouped.items():
        if target_ids is not None:
            daily = [order for order in daily if order.id_pedido in target_ids]
            if not daily:
                continue
        values = [v for previous, amounts in delivered.items() if day - timedelta(days=90) <= previous < day for v in amounts]
        reference = robust_reference(values, 20)
        if not reference:
            continue
        center, threshold = reference
        for order in daily:
            if order.estado not in {'Cancelado', 'No entregado'} and order.importe_total > threshold:
                amount_alerts[order.id_pedido] = OperationalAlert(clave=f'importe:{order.id_pedido}', tipo='importe',
                    id_pedido=order.id_pedido, observado=order.importe_total, habitual=center, umbral=threshold,
                    antecedentes=len(values), mensaje=f'Pedido #{order.id_pedido}: este pedido es mucho más alto que el importe habitual. '
                    f'Importe {amount_text(order.importe_total)}; lo habitual es {amount_text(center)}.')
    prior = defaultdict(list)
    for sample in samples:
        if target_ids is not None and sample.order_id not in target_ids:
            prior[sample.courier_id].append(sample)
            continue
        previous = [r.duration for r in prior[sample.courier_id]
                    if sample.began - timedelta(days=90) <= r.ended < sample.began]
        reference = robust_reference(previous, 10)
        if reference:
            center, threshold = reference
            classified[sample.delivery_id] = sample.duration > threshold
            if sample.duration > threshold:
                delay_alerts[sample.order_id] = OperationalAlert(clave=f'entrega:{sample.delivery_id}', tipo='entrega',
                    id_pedido=sample.order_id, id_entrega=sample.delivery_id,
                    observado=rounded(sample.duration), habitual=rounded(center), umbral=threshold, antecedentes=len(previous),
                    mensaje=f'Entrega #{sample.delivery_id}: tardó {quantity_text(sample.duration)} minutos. '
                    f'Habitualmente este repartidor tarda unos {quantity_text(center)} minutos.')
        prior[sample.courier_id].append(sample)
    return amount_alerts, delay_alerts, classified


def operational_evidence(db, restaurant, cutoff):
    orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == restaurant, Pedido.fecha_hora < cutoff)
                        .order_by(Pedido.fecha_hora, Pedido.id_pedido)).all()
    samples = delivery_samples(db, restaurant, cutoff)
    amounts, delays, classified = detect_alerts(orders, samples)
    return orders, samples, amounts, delays, classified


def owner_order_warnings(db, user, order_ids, *, reference_day=None, target_orders=None):
    """Un lote por página; los demás roles no reciben referencias privadas."""
    if user.rol != 'propietario' or (order_ids is not None and not order_ids):
        return {}
    day = reference_day or operational_date(db, user.id_restaurante)
    if day is None:
        return {}
    cutoff = operational_day_bounds(day)[1]
    if order_ids is None:
        orders, _, amounts, delays, _ = operational_evidence(db, user.id_restaurante, cutoff)
        order_ids = [order.id_pedido for order in orders]
        target_orders = orders
    else:
        ids = set(order_ids)
        if target_orders is None:
            target_orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == user.id_restaurante,
                Pedido.id_pedido.in_(ids), Pedido.fecha_hora < cutoff)).all()
        targets = [o for o in target_orders if o.id_pedido in ids and o.id_restaurante == user.id_restaurante
                   and as_utc(o.fecha_hora) < cutoff]
        amounts, delays = {}, {}
        if targets:
            first = min(local_day(o.fecha_hora) for o in targets)
            last = max(local_day(o.fecha_hora) for o in targets)
            # Solo importes entregados en las ventanas de referencia y pedidos objetivo.
            orders = db.execute(select(Pedido.id_pedido, Pedido.fecha_hora, Pedido.estado, Pedido.importe_total)
                .where(Pedido.id_restaurante == user.id_restaurante, Pedido.fecha_hora < cutoff,
                    or_(Pedido.id_pedido.in_(ids), and_(Pedido.estado == 'Entregado', Pedido.importe_total > 0,
                        Pedido.fecha_hora >= operational_day_bounds(first - timedelta(days=90))[0],
                        Pedido.fecha_hora < operational_day_bounds(last)[0])))
                .order_by(Pedido.fecha_hora, Pedido.id_pedido)).all()
            # Conservar todos los eventos de cada entrega evita perder viajes largos o repetidos.
            samples = delivery_samples(db, user.id_restaurante, cutoff,
                courier_order_ids=[o.id_pedido for o in targets if o.estado == 'Entregado'])
            amounts, delays, _ = detect_alerts(orders, samples, target_ids=ids)
    targets = [order for order in (target_orders or []) if order.id_pedido in set(order_ids)
               and order.id_restaurante == user.id_restaurante]
    if targets:
        amounts = amount_alerts_for_orders(db, user.id_restaurante, targets)
    state_warnings = {}
    active_targets = [order for order in targets if local_day(order.fecha_hora) == day
                      and order.estado in ORDER_STATES]
    if active_targets:
        start, end = operational_day_bounds(day)
        day_orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == user.id_restaurante,
            Pedido.fecha_hora >= start, Pedido.fecha_hora < end)).all()
        now = as_utc(db.scalar(select(func.now())))
        spans, current = state_durations(db, day_orders, now)
        _, _, day_delays = state_delay_analysis(day_orders, spans, current, now)
        for order in active_targets:
            ongoing = current.get(order.id_pedido)
            if ongoing and ongoing[0] == order.estado:
                delay = next((item for item in day_delays.get(order.id_pedido, [])
                              if item.estado == order.estado), None)
                if delay:
                    state_warnings[order.id_pedido] = _state_delay_message(order.id_pedido, delay)
    return {oid: {"advertencia_importe": amounts[oid].mensaje if oid in amounts else None,
                   "advertencia_entrega": delays[oid].mensaje if oid in delays else None,
                   **({"advertencia_demora_estado": state_warnings[oid]} if oid in state_warnings else {})}
            for oid in order_ids}


def operational_dashboard(db: Session, user: Usuario, restaurant: int, selected: date | None = None):
    if user.rol not in {'propietario', 'personal'} or user.id_restaurante != restaurant:
        raise HTTPException(403, 'No tenés permiso para consultar indicadores y alertas.')
    day = analysis_reference_date(db, restaurant)
    if day is None:
        return OperationalDashboard()
    target = selected or day
    if target > day:
        raise HTTPException(422, 'Elegí una fecha anterior o igual a la fecha operativa.')
    start, end = operational_day_bounds(target)
    orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == restaurant, Pedido.fecha_hora < end)
                        .order_by(Pedido.fecha_hora, Pedido.id_pedido)).all()
    samples = delivery_samples(db, restaurant, end)
    _, _, classified = detect_alerts([], samples)
    first_registered = db.scalar(select(func.min(DiaOperativo.fecha)).where(
        DiaOperativo.id_restaurante == restaurant, DiaOperativo.fecha <= day))
    first = min([local_day(o.fecha_hora) for o in orders] + ([first_registered] if first_registered else []) or [day])
    if target < first:
        raise HTTPException(422, 'La fecha elegida es anterior al historial disponible.')
    daily = [o for o in orders if start <= as_utc(o.fecha_hora) < end]
    operational_days = operating_days(db, restaurant, first, target)
    now = as_utc(db.scalar(select(func.now())))
    spans, current = state_durations(db, daily, now)
    daily_durations, _, state_delays = state_delay_analysis(daily, spans, current, now)
    sold = [o for o in daily if o.estado == 'Entregado']
    sales = sum((o.importe_total for o in sold), Decimal(0))
    completed = [r for r in samples if start <= r.ended < end]
    result = OperationalDashboard(fecha_operativa=day, fecha=target, primera_fecha=first, pedidos=len(daily),
        ventas=sales, ticket_promedio=rounded(sales / len(sold)) if sold else None, pedidos_entregados=len(sold),
        entrega_minutos=rounded(sum((r.duration for r in completed), Decimal(0)) / len(completed)) if completed else None,
        entregas_con_tiempo=len(completed), entregas_habituales=sum(classified.get(r.delivery_id) is False for r in completed),
        entregas_demoradas=sum(classified.get(r.delivery_id) is True for r in completed),
        entregas_sin_referencia=sum(r.delivery_id not in classified for r in completed))
    result.tiempos_promedio = [StateAverage(estado=state, pedidos=len(daily_durations[state]),
        minutos=rounded(sum(daily_durations[state], Decimal(0)) / len(daily_durations[state]))
        if daily_durations[state] else None) for state in ORDER_STATES]
    totals = defaultdict(int)
    names = {}
    if sold:
        details = db.execute(select(DetallePedido.id_producto, Producto.nombre, DetallePedido.cantidad)
            .join(Producto, Producto.id_producto == DetallePedido.id_producto)
            .where(DetallePedido.id_pedido.in_([o.id_pedido for o in sold]), Producto.id_restaurante == restaurant)).all()
        for pid, name, count in details:
            totals[pid] += count
            names[pid] = name
    result.productos = [TopProduct(id_producto=pid, nombre=names[pid], cantidad=total)
                        for pid, total in sorted(totals.items(), key=lambda r: (-r[1], r[0]))[:5]]
    trend = {value: SalesDay(fecha=value) for value in operational_days[-7:]}
    for order in orders:
        bucket = trend.get(local_day(order.fecha_hora))
        if bucket:
            bucket.pedidos += 1
            if order.estado == 'Entregado':
                bucket.ventas += order.importe_total
    maximum = max((r.ventas for r in trend.values()), default=Decimal(0))
    for bucket in trend.values():
        bucket.proporcion = max(1, int(bucket.ventas / maximum * 100)) if bucket.ventas and maximum else 0
    result.evolucion = list(trend.values())
    result.alertas = []
    result.alertas.extend(amount_alerts_for_orders(db, restaurant, daily).values())
    for order in daily:
        detected = state_delays.get(order.id_pedido, [])
        if detected:
            result.alertas.append(OperationalAlert(clave=f'demoras:{order.id_pedido}', tipo='demora',
                id_pedido=order.id_pedido, observado=max(row.minutos for row in detected), demoras=detected,
                mensaje=f'Pedido #{order.id_pedido} — Demoras detectadas'))
    # La misma referencia robusta de las alertas se aplica a conteos por día abierto.
    open_days = [value for value in operational_days if value >= target - timedelta(days=90)]
    if target in open_days:
        daily_counts = defaultdict(int)
        for order in orders:
            daily_counts[local_day(order.fecha_hora)] += 1
        previous = [Decimal(daily_counts[d]) for d in open_days if d < target]
        reference = robust_reference(previous, 20)
        if reference:
            center, upper = reference
            threshold = max(Decimal(0), center * 2 - upper)
            observed = Decimal(len(daily))
            if observed <= threshold and observed < center:
                result.alertas.append(OperationalAlert(clave=f'demanda:{target}', tipo='demanda',
                    observado=observed, habitual=center, umbral=threshold, antecedentes=len(previous),
                    mensaje=f'Se registraron {len(daily)} pedidos en un día operativo; lo habitual es {quantity_text(center)}.'))
    # Mismo servicio, fecha, unidades enteras y recetas que Previsión de demanda.
    # El stock es actual: nunca se presenta como una reconstrucción de fechas pasadas.
    from app.analytics.forecast import day_forecast
    forecast = day_forecast(db, restaurant, target, reference_day=target, history_orders=orders)
    result.fecha_stock = forecast.fecha_seleccionada
    result.aviso_stock = forecast.aviso
    for row in forecast.insumos:
        if row.faltante > 0:
            unit = 'un.' if row.unidad.lower() in {'unidad', 'unidades', 'u'} else 'L' if row.unidad.lower() == 'l' else row.unidad
            result.alertas.append(OperationalAlert(clave=f'stock:{target}:{row.id_insumo}', tipo='stock',
                observado=row.faltante, habitual=row.stock_actual, fecha_pronostico=forecast.fecha_seleccionada,
                mensaje=f'Podrían faltar {quantity_text(row.faltante)} {unit} de {row.nombre} para lo previsto el {target:%d/%m}. '
                        f'Compra sugerida: {quantity_text(row.reposicion_sugerida)} {unit}.'))
    rank = {'stock': 0, 'demora': 1, 'importe': 2, 'demanda': 3}
    result.alertas.sort(key=lambda a: (rank[a.tipo], -(a.observado / a.habitual if a.habitual and a.habitual > 0 else a.observado), a.clave))
    result.total_alertas = len(result.alertas)
    return result
