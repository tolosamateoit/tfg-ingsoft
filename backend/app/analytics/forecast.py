"""HU-08: promedios evaluados temporalmente, con trazabilidad persistida."""

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from itertools import combinations

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.analytics.schemas import DayForecastOutput, ForecastItem, ForecastOutput, HistoricalOrdersDay, IngredientNeed, PreparationProduct
from app.auth.service import as_utc
from app.db.models import DetallePedido, Insumo, Pedido, PrediccionDemanda, Producto, RecetaDetalle
from app.orders.operational_date import operational_day_bounds, OPERATIONAL_ZONE
from app.orders.service import lock_order_relations
from app.orders.operating_days import operating_days, analysis_reference_date
from app.db.models import DiaOperativo


def utc_today(db: Session):
    # HU-09 conserva su reloj anterior.
    return as_utc(db.scalar(select(func.now()))).date()


def rounded(value):
    return Decimal(str(value)).quantize(Decimal('0.000001'))


def predict(values, start, offset, method, *, dates=None, target=None):
    sample = [value for index, value in enumerate(values)
              if method == 'promedio_diario' or (dates[index] if dates is not None else start + timedelta(days=index)).weekday()
              == (target if target is not None else start + timedelta(days=offset)).weekday()]
    if not sample:
        sample = values  # Sin antecedentes de ese día de semana, usar la referencia diaria existente.
    return sum(sample) / len(sample)


def evaluate_series(values, start, *, method=None, dates=None, future_start=None):
    """21+ días iniciales, 7 de selección y 7 de prueba independiente.

    Cada bloque representa una predicción de siete días sin actualizarse con
    sus resultados. Los días de prueba nunca eligen el método.
    """
    if len(values) < 35:
        raise ValueError('Se requieren 35 días para selección y evaluación independientes.')
    methods = ('promedio_diario', 'promedio_dia_semana')
    split = len(values) - 14
    scores = {method: sum(abs(values[i] - predict(values[:split], start, i, method, dates=dates[:split] if dates else None, target=dates[i] if dates else None))
                          for i in range(split, split + 7)) / 7 for method in methods}
    chosen = method or min(methods, key=scores.get)  # empate: referencia más simple
    test_start = len(values) - 7
    errors = {method: sum(abs(values[i] - predict(values[:test_start], start, i, method, dates=dates[:test_start] if dates else None, target=dates[i] if dates else None))
                          for i in range(test_start, len(values))) / 7 for method in methods}
    daily = [rounded(predict(values, start, len(values) + i, chosen, dates=dates,
                     target=future_start + timedelta(days=i) if future_start else None)) for i in range(7)]
    return chosen, scores, errors, daily


def item_output(prediction, name):
    fields = ('id_prediccion', 'id_producto', 'periodo_inicio', 'periodo_fin',
              'demanda_estimada', 'modelo', 'nombre_metrica', 'valor_metrica', 'generada_en')
    data = {field: getattr(prediction, field) for field in fields}
    data['generada_en'] = as_utc(prediction.generada_en)
    if prediction.modelo.startswith('{'):
        meta = json.loads(prediction.modelo)
        data.update(meta['item'])
        data['modelo'] = meta['metodo']
    return ForecastItem(**data, producto=name)


def ingredient_needs(db: Session, restaurant_id: int, predictions: list[ForecastItem], *, preparation=False):
    names = {row.id_producto: row.producto for row in predictions}
    quantities = {row.id_producto: row.demanda_estimada for row in predictions}
    recipes = db.scalars(select(RecetaDetalle).join(Producto).where(
        Producto.id_restaurante == restaurant_id, RecetaDetalle.id_producto.in_(names))).all()
    missing = [name for id, name in names.items() if id not in {row.id_producto for row in recipes}]
    amounts = defaultdict(Decimal)
    with localcontext() as context:
        context.prec = 60
        for row in recipes:
            amounts[row.id_insumo] += quantities[row.id_producto] * row.cantidad
        ingredients = db.scalars(select(Insumo).where(Insumo.id_restaurante == restaurant_id,
            Insumo.id_insumo.in_(amounts)).order_by(Insumo.nombre, Insumo.id_insumo)).all()
        by_id = {row.id_insumo: row for row in ingredients}
        if len(by_id) != len(amounts) or any(row.unidad != by_id[row.id_insumo].unidad for row in recipes):
            raise HTTPException(409, 'Revisá la pertenencia y las unidades de los insumos de las recetas.')
        result = []
        for row in ingredients:
            required = amounts[row.id_insumo].quantize(Decimal('0.000001'), rounding=ROUND_CEILING)
            indivisible = row.unidad.lower() in {'unidad', 'unidades', 'u'}
            available = row.stock_actual
            if preparation and indivisible:
                required = required.to_integral_value(rounding=ROUND_CEILING)
                available = available.to_integral_value(rounding=ROUND_FLOOR)
            shortage = max(Decimal(0), required - available)
            replacement = shortage.to_integral_value(rounding=ROUND_CEILING) if indivisible else shortage
            if preparation and not indivisible:
                replacement = replacement.quantize(Decimal('.01'), rounding=ROUND_CEILING)
            result.append(IngredientNeed(id_insumo=row.id_insumo, nombre=row.nombre, unidad=row.unidad,
                cantidad_necesaria=required, stock_actual=available, faltante=shortage,
                reposicion_sugerida=replacement,
                explicacion=f'Se recomienda reponer {replacement.normalize():f} {row.unidad}: se estiman {required.normalize():f} y hay {available.normalize():f} disponibles.'))
    return result, missing


def associations(baskets, names):
    """Presencia por pedido (no cantidades); soporte, confianza y lift mínimos."""
    n = len(baskets)
    counts = Counter(p for basket in baskets.values() for p in basket)
    pairs = Counter(pair for basket in baskets.values() for pair in combinations(sorted(basket), 2))
    messages = []
    for (a, b), together in sorted(pairs.items()):
        if n < 30 or together < 10 or together / n < .05:
            continue
        for source, target in ((a, b), (b, a)):
            confidence = together / counts[source]
            lift = confidence / (counts[target] / n)
            if counts[source] >= 20 and confidence >= .5 and lift >= 1.2:
                messages.append(f'Los pedidos de {names[source]} suelen incluir {names[target]}: '
                    f'{together} de {counts[source]} pedidos ({confidence:.0%}); '
                    f'frecuencia relativa {lift:.2f} veces la habitual, sobre {n} pedidos entregados.')
    return messages


def calculate_forecast(db: Session, restaurant_id: int, *, target_date: date | None = None,
                       reference_day: date | None = None, history_orders=None):
    """Cálculo sin escrituras, también utilizable en verificación READ ONLY."""
    day = reference_day if reference_day is not None else analysis_reference_date(db, restaurant_id)
    if day is None:
        return ForecastOutput(estado='Historial insuficiente', dias_historial=0, pedidos_completados=0)
    if target_date is not None and not day <= target_date <= day + timedelta(days=7):
        raise HTTPException(422, 'Elegí una fecha entre la fecha operativa y los siete días siguientes.')
    # Para prever la fecha operativa se excluye TODO ese día, aunque tenga ventas.
    history_end = min(day, target_date - timedelta(days=1)) if target_date else day
    cutoff = operational_day_bounds(history_end)[1]
    if history_orders is None:
        orders = db.execute(select(Pedido.id_pedido, Pedido.fecha_hora, Pedido.estado).where(
            Pedido.id_restaurante == restaurant_id, Pedido.fecha_hora < cutoff)).all()
    else:
        orders = [row for row in history_orders if as_utc(row.fecha_hora) < cutoff]
    earliest_order = db.scalar(select(func.min(Pedido.fecha_hora)).where(Pedido.id_restaurante == restaurant_id, Pedido.fecha_hora < cutoff))
    earliest_record = db.scalar(select(func.min(DiaOperativo.fecha)).where(DiaOperativo.id_restaurante == restaurant_id, DiaOperativo.fecha <= history_end))
    first_order = as_utc(earliest_order).astimezone(OPERATIONAL_ZONE).date() if earliest_order else None
    start = min((value for value in (first_order, earliest_record) if value is not None), default=history_end)
    dates = operating_days(db, restaurant_id, start, history_end)
    days = len(dates)
    result = ForecastOutput(estado='Historial insuficiente', fecha_operativa=day,
                            dias_historial=days, pedidos_completados=sum(row.estado == 'Entregado' for row in orders))
    if days < 35 or result.pedidos_completados < 10:
        result.limitaciones = ['Se requieren 35 días operativos y 10 pedidos entregados: 21 días iniciales, 7 para elegir el método y 7 para evaluarlo.']
        return result
    products = db.scalars(select(Producto).where(Producto.id_restaurante == restaurant_id,
                          Producto.activo.is_(True)).order_by(Producto.id_producto)).all()
    names = {p.id_producto: p.nombre for p in products}
    sales = db.execute(select(DetallePedido.id_producto, Pedido.fecha_hora, DetallePedido.cantidad, Pedido.id_pedido)
        .join(Pedido, Pedido.id_pedido == DetallePedido.id_pedido).join(Producto)
        .where(Pedido.id_restaurante == restaurant_id, Producto.id_restaurante == restaurant_id,
               Pedido.fecha_hora < cutoff, Producto.activo.is_(True))).all()
    series = defaultdict(lambda: [0] * days)
    day_index = {day: index for index, day in enumerate(dates)}
    baskets = {row.id_pedido: set() for row in orders if row.estado == 'Entregado'}
    for product_id, timestamp, quantity, order_id in sales:
        series[product_id][day_index[as_utc(timestamp).astimezone(OPERATIONAL_ZONE).date()]] += quantity
        if order_id in baskets:
            baskets[order_id].add(product_id)
    generated = as_utc(db.scalar(select(func.now())))
    for product in products:
        if product.id_producto not in series:
            result.productos_sin_ventas.append(product.nombre)
            continue
        first_date = target_date or day + timedelta(days=1)
        chosen, scores, errors, daily = evaluate_series(series[product.id_producto], start,
            method='promedio_dia_semana' if target_date else None, dates=dates, future_start=first_date)
        if target_date:
            daily = [rounded(predict(series[product.id_producto], start, 0, chosen, dates=dates, target=target_date))]
        result.predicciones.append(ForecastItem(id_prediccion=0, id_producto=product.id_producto,
            producto=product.nombre, periodo_inicio=first_date, periodo_fin=target_date or day + timedelta(days=7),
            demanda_estimada=sum(daily), modelo=chosen, nombre_metrica='MAE', valor_metrica=rounded(errors[chosen]),
            generada_en=generated, dias=[dict(fecha=first_date + timedelta(days=i), cantidad=q) for i, q in enumerate(daily)],
            observaciones_evaluadas=7, comparacion_mae={m: rounded(v) for m, v in scores.items()},
            mae_referencia=rounded(errors['promedio_diario']),
            explicacion=('Promedio de las ventas de cada día de semana.' if chosen == 'promedio_dia_semana' else 'Promedio diario de ventas.')
                + (' Evaluado en los últimos 7 días operativos independientes; patrón del día de semana solicitado.' if target_date else
                   ' Elegido por menor MAE en 7 días operativos de selección; evaluado en otros 7 posteriores.')
                + f' Historial: {start} a {history_end}, incluidos días operativos sin pedidos.'))
    result.dias_validacion = 7
    result.observaciones_evaluadas = len(result.predicciones) * 7
    result.mae = rounded(sum(p.valor_metrica for p in result.predicciones) / len(result.predicciones)) if result.predicciones else None
    if not target_date:
        result.insumos, result.recetas_faltantes = ingredient_needs(db, restaurant_id, result.predicciones)
    else:
        order_counts = [0] * days
        for order in orders:
            order_counts[day_index[as_utc(order.fecha_hora).astimezone(OPERATIONAL_ZONE).date()]] += 1
        result.pedidos_estimados_original = rounded(predict(order_counts, start,
            0, 'promedio_dia_semana', dates=dates, target=target_date))
    result.asociaciones = associations(baskets, names)
    result.limitaciones = ['Estimaciones basadas en pedidos registrados, por fecha local de creación y días operativos; no miden demanda no registrada.',
        'MAE calculado en 7 días operativos independientes; no garantiza el error futuro. El historial sintético valida la demo, no precisión comercial.']
    if not result.asociaciones:
        result.limitaciones.append('Sin evidencia suficiente para afirmar asociaciones entre productos.')
    result.estado = 'Predicción generada' if result.predicciones else 'Sin productos activos con ventas históricas'
    return result


def day_forecast(db: Session, restaurant_id: int, selected: date | None = None, *,
                 reference_day: date | None = None, history_orders=None) -> DayForecastOutput:
    """Promedio de los siete últimos días abiertos del mismo día de semana."""
    day = reference_day if reference_day is not None else analysis_reference_date(db, restaurant_id)
    if day is None:
        return DayForecastOutput(estado='Sin historial', aviso='Todavía no hay pedidos para estimar la demanda.')
    target = selected or day
    weekdays = ('Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom')
    weekday_names = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábados', 'domingos')
    options = [dict(fecha=day + timedelta(days=i),
                    etiqueta=f'{weekdays[(day + timedelta(days=i)).weekday()]} {(day + timedelta(days=i)):%d/%m}')
               for i in range(8)]
    if not day <= target <= day + timedelta(days=7):
        raise HTTPException(422, 'Elegí una fecha entre la fecha operativa y los siete días siguientes.')
    history_end = min(day, target - timedelta(days=1))
    cutoff = operational_day_bounds(history_end)[1]
    first_order = db.scalar(select(func.min(Pedido.fecha_hora)).where(
        Pedido.id_restaurante == restaurant_id, Pedido.fecha_hora < cutoff))
    first_record = db.scalar(select(func.min(DiaOperativo.fecha)).where(
        DiaOperativo.id_restaurante == restaurant_id, DiaOperativo.fecha <= history_end))
    first_order_day = as_utc(first_order).astimezone(OPERATIONAL_ZONE).date() if first_order else None
    first = min((value for value in (first_record, first_order_day) if value is not None), default=history_end)
    dates = [value for value in operating_days(db, restaurant_id, first, history_end)
             if value.weekday() == target.weekday()][-7:]
    result = DayForecastOutput(estado='Historial insuficiente', fecha_operativa=day, fecha_seleccionada=target,
                               fechas_disponibles=options)
    if not dates:
        result.aviso = 'Todavía no hay días operativos anteriores de este día de la semana para calcular una recomendación.'
        return result

    products = db.scalars(select(Producto).where(Producto.id_restaurante == restaurant_id,
        Producto.activo.is_(True)).order_by(Producto.id_producto)).all()
    names = {product.id_producto: product.nombre for product in products}
    windows = [operational_day_bounds(value) for value in dates]
    rows = db.execute(select(Pedido.id_pedido, Pedido.fecha_hora, DetallePedido.id_producto, DetallePedido.cantidad)
        .join(DetallePedido, DetallePedido.id_pedido == Pedido.id_pedido)
        .where(Pedido.id_restaurante == restaurant_id, Pedido.estado == 'Entregado',
               or_(*(and_(Pedido.fecha_hora >= start, Pedido.fecha_hora < end) for start, end in windows)))).all()
    units = defaultdict(int)
    orders = {value: set() for value in dates}
    for order_id, timestamp, product_id, quantity in rows:
        order_day = as_utc(timestamp).astimezone(OPERATIONAL_ZONE).date()
        orders[order_day].add(order_id)
        if product_id in names:
            units[product_id, order_day] += quantity
    result.historial_pedidos = [HistoricalOrdersDay(fecha=value, pedidos=len(orders[value])) for value in dates]
    average_orders = Decimal(sum(row.pedidos for row in result.historial_pedidos)) / len(dates)
    result.promedio_pedidos = rounded(average_orders)
    result.pedidos_estimados = int(average_orders.to_integral_value(rounding=ROUND_CEILING))
    prepared = []
    predictions = []
    generated = as_utc(db.scalar(select(func.now())))
    for product in products:
        history = [dict(fecha=value, unidades=units[product.id_producto, value]) for value in dates]
        average = Decimal(sum(row['unidades'] for row in history)) / len(dates)
        quantity = int(average.to_integral_value(rounding=ROUND_CEILING))
        result.productos.append(PreparationProduct(id_producto=product.id_producto, nombre=product.nombre,
                                    cantidad=quantity, estimacion_original=rounded(average), historial_ventas=history))
        item = ForecastItem(id_prediccion=0, id_producto=product.id_producto, producto=product.nombre,
            periodo_inicio=target, periodo_fin=target, demanda_estimada=rounded(average), modelo='promedio_dia_semana',
            nombre_metrica=None, valor_metrica=None, generada_en=generated,
            dias=[dict(fecha=target, cantidad=rounded(average))],
            explicacion=f'Promedio de {len(dates)} días operativos anteriores del mismo día de semana.')
        predictions.append(item)
        if quantity > 0:
            prepared.append(item.model_copy(update={'demanda_estimada': Decimal(quantity)}))
    result.estado = 'Predicción generada'
    result.evaluacion = ForecastOutput(estado=result.estado, fecha_operativa=day, dias_historial=len(dates),
                                      predicciones=predictions)
    result.productos.sort(key=lambda p: (-p.estimacion_original, p.id_producto))
    result.insumos, missing = ingredient_needs(db, restaurant_id, prepared, preparation=True)
    result.compras_completas = not missing
    result.cantidad_faltantes = sum(row.faltante > 0 for row in result.insumos)
    result.explicaciones = [f'Tomamos como referencia las ventas de los últimos {len(dates)} {weekday_names[target.weekday()]} operativos, incluidos los días sin ventas.']
    if result.productos and result.productos[0].cantidad > 0:
        result.explicaciones.append(f'{result.productos[0].nombre} fue el producto con más unidades vendidas en esos días.')
    notices = []
    if missing:
        notices.append('Compras incompletas: faltan recetas de ' + ', '.join(missing) + '.')
    result.aviso = ' '.join(notices) or None
    return result


def generate_forecast(db: Session, restaurant_id: int) -> ForecastOutput:
    lock_order_relations(db)
    result = calculate_forecast(db, restaurant_id)
    summary = result.model_dump(mode='json', exclude={'predicciones', 'insumos', 'recetas_faltantes'})
    for item in result.predicciones:
        metadata = dict(version=2, metodo=item.modelo, resumen=summary,
            item=item.model_dump(mode='json', include={'dias', 'explicacion', 'observaciones_evaluadas', 'comparacion_mae', 'mae_referencia'}))
        row = PrediccionDemanda(**item.model_dump(include={'id_producto', 'periodo_inicio', 'periodo_fin',
            'demanda_estimada', 'nombre_metrica', 'valor_metrica', 'generada_en'}), modelo=json.dumps(metadata, ensure_ascii=False))
        db.add(row)
        db.flush()
        item.id_prediccion = row.id_prediccion
    db.commit()
    return result


def latest_forecast(db: Session, restaurant_id: int) -> ForecastOutput:
    latest = db.scalar(select(func.max(PrediccionDemanda.generada_en)).join(Producto).where(Producto.id_restaurante == restaurant_id))
    if latest is None:
        return ForecastOutput(estado='Sin predicciones guardadas')
    rows = db.execute(select(PrediccionDemanda, Producto.nombre).join(Producto)
        .where(Producto.id_restaurante == restaurant_id, PrediccionDemanda.generada_en == latest)
        .order_by(Producto.id_producto)).all()
    items = [item_output(prediction, name) for prediction, name in rows]
    needs, missing = ingredient_needs(db, restaurant_id, items)
    summary = json.loads(rows[0][0].modelo)['resumen'] if rows[0][0].modelo.startswith('{') else {}
    summary['estado'] = 'Predicción guardada; insumos calculados con recetas y stock actuales'
    return ForecastOutput(**summary, predicciones=items, insumos=needs, recetas_faltantes=missing)
