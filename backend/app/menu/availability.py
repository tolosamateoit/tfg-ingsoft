"""Disponibilidad por receta y reservas de pedidos aún no preparados."""
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import case, func, select

from app.db.models import DetallePedido, Insumo, Pedido, Producto, RecetaDetalle


def reserved_ingredients(restaurant_id, *, exclude_order_id=None):
    query = (select(RecetaDetalle.id_insumo.label('id_insumo'),
                   func.sum(RecetaDetalle.cantidad * DetallePedido.cantidad).label('reservado'))
        .join(DetallePedido, DetallePedido.id_producto == RecetaDetalle.id_producto)
        .join(Pedido, Pedido.id_pedido == DetallePedido.id_pedido)
        .where(Pedido.id_restaurante == restaurant_id, Pedido.estado == 'Nuevo'))
    if exclude_order_id is not None:
        query = query.where(Pedido.id_pedido != exclude_order_id)
    return query.group_by(RecetaDetalle.id_insumo).subquery()


def ingredient_available(restaurant_id, reserved):
    return ((Insumo.id_restaurante == restaurant_id) & Insumo.activo.is_(True) &
            (RecetaDetalle.unidad == Insumo.unidad) &
            (Insumo.stock_actual - func.coalesce(reserved.c.reservado, 0) >= RecetaDetalle.cantidad))


def product_availability(db, restaurant_id, product_ids=None):
    """Una receta completa y stock libre para al menos una unidad."""
    reserved = reserved_ingredients(restaurant_id)
    valid = ingredient_available(restaurant_id, reserved)
    query = (select(Producto.id_producto, func.count(RecetaDetalle.id_insumo),
                    func.sum(case((valid, 1), else_=0)))
        .outerjoin(RecetaDetalle, RecetaDetalle.id_producto == Producto.id_producto)
        .outerjoin(Insumo, Insumo.id_insumo == RecetaDetalle.id_insumo)
        .outerjoin(reserved, reserved.c.id_insumo == Insumo.id_insumo)
        .where(Producto.id_restaurante == restaurant_id)
        .group_by(Producto.id_producto))
    if product_ids is not None:
        query = query.where(Producto.id_producto.in_(product_ids))
    return {pid: count > 0 and count == valid_count for pid, count, valid_count in db.execute(query)}


def validate_order_stock(db, restaurant_id, items):
    """Validar el carrito completo, sumando insumos compartidos y reservas existentes.

    El llamador ya tomó el lock de relaciones compartido con preparación,
    movimientos y cambios de receta. La reserva es el propio pedido Nuevo.
    """
    quantities = {item.id_producto: item.cantidad for item in items}
    reserved = reserved_ingredients(restaurant_id)
    rows = db.execute(select(RecetaDetalle.id_producto, RecetaDetalle.cantidad,
        RecetaDetalle.unidad, Insumo, func.coalesce(reserved.c.reservado, 0))
        .join(Insumo, Insumo.id_insumo == RecetaDetalle.id_insumo)
        .outerjoin(reserved, reserved.c.id_insumo == Insumo.id_insumo)
        .where(RecetaDetalle.id_producto.in_(quantities))).all()
    if set(quantities) != {row[0] for row in rows}:
        raise HTTPException(409, 'Hay productos sin receta o inventario asociado.')
    needed = {}
    available = {}
    for product_id, amount, unit, ingredient, held in rows:
        if ingredient.id_restaurante != restaurant_id or not ingredient.activo or ingredient.unidad != unit:
            raise HTTPException(409, 'Revisá las unidades y los insumos de la receta.')
        iid = ingredient.id_insumo
        needed[iid] = needed.get(iid, Decimal(0)) + amount * quantities[product_id]
        available[iid] = ingredient.stock_actual - held
    if any(amount > available[iid] for iid, amount in needed.items()):
        raise HTTPException(409, 'No hay stock suficiente para las cantidades solicitadas.')


def missing_ingredients(db, restaurant_id):
    reserved = reserved_ingredients(restaurant_id)
    rows = db.execute(select(RecetaDetalle.id_producto, Insumo.nombre)
        .join(Producto, Producto.id_producto == RecetaDetalle.id_producto)
        .join(Insumo, Insumo.id_insumo == RecetaDetalle.id_insumo)
        .outerjoin(reserved, reserved.c.id_insumo == Insumo.id_insumo)
        .where(Producto.id_restaurante == restaurant_id,
            ~ingredient_available(restaurant_id, reserved))
        .order_by(Insumo.nombre)).all()
    result = {}
    for product_id, name in rows:
        result.setdefault(product_id, []).append(name)
    return result
