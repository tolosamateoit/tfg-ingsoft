"""Regresión diaria evaluada fuera de muestra; sin datos precargados ni simulación."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, localcontext
from math import ceil

from fastapi import HTTPException
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.schemas import ForecastItem, ForecastOutput, IngredientNeed
from app.auth.service import as_utc
from app.db.models import DetallePedido, Insumo, Pedido, PrediccionDemanda, Producto, RecetaDetalle
from app.orders.service import lock_order_relations


def utc_today(db: Session):
    return as_utc(db.scalar(select(func.now()))).date()


def item_output(prediction: PrediccionDemanda, name: str) -> ForecastItem:
    return ForecastItem(**{field: getattr(prediction, field) for field in ForecastItem.model_fields if field != "producto"}, producto=name)


def ingredient_needs(db: Session, restaurant_id: int, predictions: list[ForecastItem]):
    names = {row.id_producto: row.producto for row in predictions}
    quantities = {row.id_producto: row.demanda_estimada for row in predictions}
    recipes = db.scalars(select(RecetaDetalle).where(RecetaDetalle.id_producto.in_(names))).all()
    missing = [name for id, name in names.items() if id not in {row.id_producto for row in recipes}]
    amounts = defaultdict(Decimal)
    with localcontext() as context:
        context.prec = 60
        for row in recipes:
            amounts[row.id_insumo] += quantities[row.id_producto] * row.cantidad
        ingredients = db.scalars(select(Insumo).where(Insumo.id_restaurante == restaurant_id, Insumo.id_insumo.in_(amounts))
                                 .order_by(Insumo.nombre, Insumo.id_insumo)).all()
        by_id = {row.id_insumo: row for row in ingredients}
        if len(by_id) != len(amounts) or any(row.unidad != by_id[row.id_insumo].unidad for row in recipes):
            raise HTTPException(409, "Revisá la pertenencia y las unidades de los insumos de las recetas.")
        result = []
        for row in ingredients:
            required = amounts[row.id_insumo].quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
            result.append(IngredientNeed(id_insumo=row.id_insumo, nombre=row.nombre, unidad=row.unidad,
                                        cantidad_necesaria=required, stock_actual=row.stock_actual,
                                        faltante=max(Decimal(0), required - row.stock_actual)))
    return result, missing


def generate_forecast(db: Session, restaurant_id: int) -> ForecastOutput:
    lock_order_relations(db)
    today = utc_today(db)
    cutoff = datetime.combine(today, datetime.min.time(), UTC)
    orders = db.execute(select(Pedido.id_pedido, Pedido.fecha_hora).where(
        Pedido.id_restaurante == restaurant_id, Pedido.estado == "Entregado", Pedido.fecha_hora < cutoff)).all()
    start = min((as_utc(row.fecha_hora).date() for row in orders), default=today)
    days = (today - start).days
    if days < 7 or len(orders) < 10:
        return ForecastOutput(estado="Historial insuficiente", dias_historial=days, pedidos_completados=len(orders))
    products = db.scalars(select(Producto).where(Producto.id_restaurante == restaurant_id, Producto.activo.is_(True))
                          .order_by(Producto.id_producto).with_for_update(read=True)).all()
    sales = db.execute(select(DetallePedido.id_producto, Pedido.fecha_hora, DetallePedido.cantidad)
                       .join(Pedido, Pedido.id_pedido == DetallePedido.id_pedido)
                       .join(Producto, Producto.id_producto == DetallePedido.id_producto)
                       .where(Pedido.id_restaurante == restaurant_id, Producto.id_restaurante == restaurant_id,
                              Pedido.estado == "Entregado", Pedido.fecha_hora < cutoff, Producto.activo.is_(True))).all()
    series = defaultdict(lambda: [0] * days)
    for product_id, timestamp, quantity in sales:
        series[product_id][(as_utc(timestamp).date() - start).days] += quantity
    validation_days = max(2, ceil(days * 0.2))
    split = days - validation_days
    x = [[day] for day in range(days)]
    generated = as_utc(db.scalar(select(func.now())))
    predictions = []
    for product in products:
        if product.id_producto not in series:
            continue
        y = series[product.id_producto]
        model = LinearRegression().fit(x[:split], y[:split])
        validation = model.predict(x[split:]).clip(min=0)
        mae = Decimal(str(float(mean_absolute_error(y[split:], validation)))).quantize(Decimal("0.000001"))
        model.fit(x, y)
        estimate = Decimal(str(float(model.predict([[day] for day in range(days, days + 7)]).clip(min=0).sum())))
        prediction = PrediccionDemanda(id_producto=product.id_producto, periodo_inicio=today, periodo_fin=today + timedelta(days=6),
                                      demanda_estimada=estimate.quantize(Decimal("0.000001")),
                                      modelo=f"regresion_lineal_diaria_v1;historial={start}..{today - timedelta(days=1)};validacion={validation_days}",
                                      nombre_metrica="MAE", valor_metrica=mae, generada_en=generated)
        db.add(prediction)
        predictions.append((prediction, product.nombre))
    db.flush()
    items = [item_output(prediction, name) for prediction, name in predictions]
    needs, missing = ingredient_needs(db, restaurant_id, items)
    result = ForecastOutput(estado="Predicción generada" if items else "Sin productos activos con ventas históricas",
                            dias_historial=days, pedidos_completados=len(orders), dias_validacion=validation_days,
                            predicciones=items, insumos=needs, recetas_faltantes=missing,
                            productos_sin_ventas=[product.nombre for product in products if product.id_producto not in series])
    db.commit()
    return result


def latest_forecast(db: Session, restaurant_id: int) -> ForecastOutput:
    latest = db.scalar(select(func.max(PrediccionDemanda.generada_en)).join(Producto).where(Producto.id_restaurante == restaurant_id))
    if latest is None:
        return ForecastOutput(estado="Sin predicciones guardadas")
    rows = db.execute(select(PrediccionDemanda, Producto.nombre).join(Producto)
                      .where(Producto.id_restaurante == restaurant_id, PrediccionDemanda.generada_en == latest)
                      .order_by(Producto.id_producto)).all()
    items = [item_output(prediction, name) for prediction, name in rows]
    needs, missing = ingredient_needs(db, restaurant_id, items)
    return ForecastOutput(estado="Predicción guardada; insumos calculados con recetas y stock actuales",
                          predicciones=items, insumos=needs, recetas_faltantes=missing)
