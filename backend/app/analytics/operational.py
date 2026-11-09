"""Indicadores operativos y anomalías de consulta; sin escrituras ni cambios de estado.

Reglas internas: mínimo 20 importes positivos de pedidos entregados en días
anteriores; mínimo 10 entregas previas del mismo repartidor terminadas antes de
la salida analizada. Ventana retrospectiva: 90 días. Límite superior robusto:
max(1.75 * mediana, Q3 + 3 * RIC); comparación estricta. No son plazos prometidos.
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
    return {oid: dict(advertencia_importe=amounts[oid].mensaje if oid in amounts else None,
                      advertencia_entrega=delays[oid].mensaje if oid in delays else None) for oid in order_ids}


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
    orders, samples, amounts, delays, classified = operational_evidence(db, restaurant, end)
    first_registered = db.scalar(select(func.min(DiaOperativo.fecha)).where(
        DiaOperativo.id_restaurante == restaurant, DiaOperativo.fecha <= day))
    first = min([local_day(o.fecha_hora) for o in orders] + ([first_registered] if first_registered else []) or [day])
    if target < first:
        raise HTTPException(422, 'La fecha elegida es anterior al historial disponible.')
    daily = [o for o in orders if start <= as_utc(o.fecha_hora) < end]
    sold = [o for o in daily if o.estado == 'Entregado']
    sales = sum((o.importe_total for o in sold), Decimal(0))
    completed = [r for r in samples if start <= r.ended < end]
    result = OperationalDashboard(fecha_operativa=day, fecha=target, primera_fecha=first, pedidos=len(daily),
        ventas=sales, ticket_promedio=rounded(sales / len(sold)) if sold else None, pedidos_entregados=len(sold),
        entrega_minutos=rounded(sum((r.duration for r in completed), Decimal(0)) / len(completed)) if completed else None,
        entregas_con_tiempo=len(completed), entregas_habituales=sum(classified.get(r.delivery_id) is False for r in completed),
        entregas_demoradas=sum(classified.get(r.delivery_id) is True for r in completed),
        entregas_sin_referencia=sum(r.delivery_id not in classified for r in completed))
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
    trend = {target - timedelta(days=i): SalesDay(fecha=target - timedelta(days=i)) for i in reversed(range(7))}
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
    result.alertas = [amounts[o.id_pedido] for o in daily if o.id_pedido in amounts]
    result.alertas.extend(delays[r.order_id] for r in completed if r.order_id in delays)
    # La misma referencia robusta de las alertas se aplica a conteos por día abierto.
    open_days = operating_days(db, restaurant, target - timedelta(days=90), target)
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
    forecast = day_forecast(db, restaurant, day, reference_day=day, history_orders=orders if target == day else None)
    result.fecha_stock = forecast.fecha_seleccionada
    result.aviso_stock = forecast.aviso
    for row in forecast.insumos:
        if row.faltante > 0:
            unit = 'un.' if row.unidad.lower() in {'unidad', 'unidades', 'u'} else 'L' if row.unidad.lower() == 'l' else row.unidad
            result.alertas.append(OperationalAlert(clave=f'stock:{day}:{row.id_insumo}', tipo='stock',
                observado=row.faltante, habitual=row.stock_actual, fecha_pronostico=forecast.fecha_seleccionada,
                mensaje=f'Podrían faltar {quantity_text(row.faltante)} {unit} de {row.nombre} para lo previsto el {day:%d/%m}. '
                        f'Compra sugerida: {quantity_text(row.reposicion_sugerida)} {unit}.'))
    rank = {'stock': 0, 'entrega': 1, 'importe': 2, 'demanda': 3}
    result.alertas.sort(key=lambda a: (rank[a.tipo], -(a.observado / a.habitual if a.habitual and a.habitual > 0 else a.observado), a.clave))
    result.total_alertas = len(result.alertas)
    result.alertas = result.alertas[:6]
    return result
