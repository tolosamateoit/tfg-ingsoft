"""Consumo atómico por preparación, serializado con los locks del DER existente."""

from decimal import Decimal, localcontext

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import DetallePedido, HistorialPedido, Insumo, MovimientoStock, Pedido, RecetaDetalle, Usuario
from app.orders.service import lock_order_relations
from app.preparation.schemas import ConsumptionOutput, PreparationEvent, PreparationInput, PreparationOutput, StockOutput

LIMIT = Decimal("999999999999.999999")


def scoped_order(db: Session, restaurant_id: int, order_id: int, *, lock=False) -> Pedido:
    query = select(Pedido).where(Pedido.id_pedido == order_id, Pedido.id_restaurante == restaurant_id)
    if lock:
        query = query.with_for_update()
    order = db.scalar(query)
    if order is None:
        raise HTTPException(404, "Pedido no disponible en este restaurante.")
    return order


def stock(db: Session, restaurant_id: int) -> list[StockOutput]:
    rows = db.execute(select(Insumo.id_insumo, Insumo.nombre, Insumo.unidad, Insumo.stock_actual)
                      .where(Insumo.id_restaurante == restaurant_id).order_by(Insumo.nombre, Insumo.id_insumo)).mappings()
    return [StockOutput(**row) for row in rows]


def preparation(db: Session, restaurant_id: int, order_id: int) -> PreparationOutput:
    order = scoped_order(db, restaurant_id, order_id)
    return _preparation_output(db, restaurant_id, order)


def preparation_history(db, order_id):
    return db.execute(select(HistorialPedido.id_historial, HistorialPedido.fecha_hora, Usuario.nombre.label("usuario"),
                                HistorialPedido.estado, HistorialPedido.tipo_evento, HistorialPedido.detalle)
                         .join(Usuario, Usuario.id_usuario == HistorialPedido.id_usuario)
                         .where(HistorialPedido.id_pedido == order_id).order_by(HistorialPedido.id_historial)).mappings().all()


def _preparation_output(db, restaurant_id, order, history=None):
    order_id = order.id_pedido
    history = preparation_history(db, order_id) if history is None else history
    ingredient_ids = select(MovimientoStock.id_insumo).where(
        MovimientoStock.id_pedido == order_id, MovimientoStock.tipo == 'consumo')
    later = func.coalesce(func.sum(MovimientoStock.cantidad).over(
        partition_by=MovimientoStock.id_insumo, order_by=MovimientoStock.id_movimiento.desc(),
        rows=(None, -1)), 0)
    ledger = (select(MovimientoStock.id_movimiento, MovimientoStock.id_insumo, Insumo.nombre,
                     Insumo.unidad, MovimientoStock.cantidad, MovimientoStock.fecha_hora, MovimientoStock.motivo,
                     MovimientoStock.id_pedido, MovimientoStock.tipo,
                     (Insumo.stock_actual - later).label('stock_despues'),
                     (Insumo.stock_actual - later - MovimientoStock.cantidad).label('stock_antes'))
              .join(Insumo, Insumo.id_insumo == MovimientoStock.id_insumo)
              .where(Insumo.id_restaurante == restaurant_id, MovimientoStock.id_insumo.in_(ingredient_ids)).subquery())
    movements = db.execute(select(ledger).where(ledger.c.id_pedido == order_id, ledger.c.tipo == 'consumo')
                           .order_by(ledger.c.id_movimiento)).mappings()
    return PreparationOutput(id_pedido=order_id, estado=order.estado,
                             version=history[-1]["id_historial"] if history else 0,
                             historial=[PreparationEvent(**row) for row in history],
                             movimientos=[ConsumptionOutput(**row) for row in movements])


def consumption(db: Session, restaurant_id: int, order_id: int, *, exclude_order_id=None):
    details = db.execute(select(DetallePedido.id_producto, DetallePedido.cantidad)
                         .where(DetallePedido.id_pedido == order_id)).all()
    recipes = db.scalars(select(RecetaDetalle).where(RecetaDetalle.id_producto.in_([row.id_producto for row in details]))).all()
    if not details or {row.id_producto for row in details} - {row.id_producto for row in recipes}:
        raise HTTPException(409, "Completá las recetas de todos los productos antes de preparar el pedido.")
    amounts: dict[int, Decimal] = {}
    by_product: dict[int, list[RecetaDetalle]] = {}
    for recipe in recipes:
        by_product.setdefault(recipe.id_producto, []).append(recipe)
    with localcontext() as context:
        context.prec = 50
        for product_id, quantity in details:
            for recipe in by_product[product_id]:
                amounts[recipe.id_insumo] = amounts.get(recipe.id_insumo, Decimal(0)) + recipe.cantidad * quantity
        ingredients = db.scalars(select(Insumo).where(Insumo.id_restaurante == restaurant_id, Insumo.id_insumo.in_(amounts))
                                 .order_by(Insumo.id_insumo).with_for_update()).all()
        by_id = {ingredient.id_insumo: ingredient for ingredient in ingredients}
        if len(by_id) != len(amounts) or any(recipe.unidad != by_id[recipe.id_insumo].unidad for recipe in recipes):
            raise HTTPException(409, "Revisá la pertenencia y las unidades de los insumos de las recetas.")
        from app.menu.availability import reserved_ingredients
        reserved = reserved_ingredients(restaurant_id, exclude_order_id=exclude_order_id)
        held = dict(db.execute(select(reserved.c.id_insumo, reserved.c.reservado)
                               .where(reserved.c.id_insumo.in_(amounts))).all())
        for ingredient in ingredients:
            if ingredient.stock_actual - held.get(ingredient.id_insumo, 0) < amounts[ingredient.id_insumo]:
                raise HTTPException(409, 'No hay stock suficiente para preparar el pedido.')
            if amounts[ingredient.id_insumo] > LIMIT or abs(ingredient.stock_actual - amounts[ingredient.id_insumo]) > LIMIT:
                raise HTTPException(422, "El consumo supera el rango de cantidades permitido.")
    return ingredients, amounts


def change_preparation(db: Session, user: Usuario, restaurant_id: int, order_id: int,
                       data: PreparationInput) -> PreparationOutput:
    lock_order_relations(db)  # Antes de las filas: mismo orden que HU-02/HU-03 y triggers.
    order = scoped_order(db, restaurant_id, order_id, lock=True)
    history = preparation_history(db, order_id)
    if order.estado == data.estado and not data.nueva_preparacion:
        return _preparation_output(db, restaurant_id, order, history)  # Reintento sin consumo duplicado.
    if data.version != (history[-1]['id_historial'] if history else 0):
        raise HTTPException(409, "El pedido cambió. Actualizá el detalle antes de continuar.")
    prepared = any(event['tipo_evento'] in {"preparacion", "nueva_preparacion"} for event in history)
    if data.nueva_preparacion:
        valid = prepared and order.estado in {"En preparación", "Listo"}
    else:
        valid = (order.estado == "Nuevo" and data.estado == "En preparación" and not prepared
                 or order.estado == 'Nuevo' and data.estado == 'Cancelado' and not prepared
                 or order.estado == "En preparación" and data.estado == "Listo")
    if not valid:
        raise HTTPException(409, "Transición no permitida. Para repetir el consumo usá Nueva preparación explícita.")
    if order.estado == 'Nuevo' and data.estado == 'En preparación':
        from app.db.models import Restaurante
        from app.orders.service import courier_available
        restaurant = db.scalar(select(Restaurante).where(Restaurante.id_restaurante == restaurant_id).with_for_update(read=True))
        if not restaurant or not restaurant.abierto:
            raise HTTPException(409, 'El restaurante está cerrado y no puede confirmar pedidos.')
        if not db.scalar(select(courier_available(restaurant_id))):
            raise HTTPException(409, 'No hay repartidores disponibles para confirmar el pedido.')
    ingredients, amounts = consumption(db, restaurant_id, order_id,
        exclude_order_id=order_id if order.estado == 'Nuevo' else None) if data.estado == "En preparación" else ([], {})
    try:
        order.estado = data.estado
        event = HistorialPedido(id_pedido=order_id, id_usuario=user.id_usuario, estado=data.estado,
                                tipo_evento="nueva_preparacion" if data.nueva_preparacion else "preparacion" if ingredients else "estado",
                                detalle=data.motivo or ('Pedido rechazado por el restaurante.' if data.estado == 'Cancelado'
                                                        else "Cambio de estado de preparación."))
        db.add(event)
        db.flush()
        for ingredient in ingredients:
            quantity = amounts[ingredient.id_insumo]
            ingredient.stock_actual -= quantity
            db.add(MovimientoStock(id_insumo=ingredient.id_insumo, id_pedido=order_id, tipo="consumo", cantidad=-quantity,
                                   motivo=f"Preparación #{event.id_historial}: {event.detalle}"))
        db.flush()
        result = _preparation_output(db, restaurant_id, order)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo guardar la preparación. Actualizá y volvé a intentar.") from None
