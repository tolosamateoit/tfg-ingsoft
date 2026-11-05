"""Gestión del mismo inventario consumido por HU-04; sin tablas adicionales."""

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.models import Insumo, MovimientoStock, RecetaDetalle, Producto
from app.menu.schemas import InputModel, Money
from app.menu.service import lock_recipe_relations, refresh_recipe_costs

StockQuantity = Annotated[Decimal, Field(max_digits=18, decimal_places=6, allow_inf_nan=False)]


class IngredientInput(InputModel):
    nombre: str = Field(min_length=1, max_length=150)
    unidad: Literal['unidad', 'kg', 'l']
    costo_unitario: Money


class MovementInput(InputModel):
    tipo: Literal["reposicion", "ajuste"]
    cantidad: StockQuantity
    motivo: str = Field(default='', max_length=500)

    @model_validator(mode="after")
    def valid_quantity(self):
        if self.cantidad == 0 or self.tipo == "reposicion" and self.cantidad < 0:
            raise ValueError("La reposición debe ser positiva; el ajuste debe ser distinto de cero.")
        return self


def ingredient(db: Session, restaurant_id: int, ingredient_id: int):
    result = db.scalar(select(Insumo).where(Insumo.id_restaurante == restaurant_id,
                       Insumo.id_insumo == ingredient_id, Insumo.activo.is_(True)).with_for_update())
    if result is None:
        raise HTTPException(404, "Insumo no disponible en este restaurante.")
    return result


def save_ingredient(db: Session, restaurant_id: int, data: IngredientInput, ingredient_id: int | None = None):
    lock_recipe_relations(db)
    row = ingredient(db, restaurant_id, ingredient_id) if ingredient_id else Insumo(
        id_restaurante=restaurant_id, stock_actual=Decimal(0))
    if ingredient_id and row.unidad != data.unidad and (
        row.stock_actual != 0
        or db.scalar(select(exists().where(RecetaDetalle.id_insumo == ingredient_id)))
        or db.scalar(select(exists().where(MovimientoStock.id_insumo == ingredient_id)))
    ):
        raise HTTPException(409, "No se puede cambiar la unidad de un insumo con stock, recetas o movimientos.")
    for name, value in data.model_dump().items():
        setattr(row, name, value)
    db.add(row)
    refresh_recipe_costs(db, restaurant_id)
    db.commit()
    return row


def record_movement(db: Session, restaurant_id: int, ingredient_id: int, data: MovementInput, actor_id: int):
    lock_recipe_relations(db)
    row = ingredient(db, restaurant_id, ingredient_id)
    if row.stock_actual + data.cantidad < 0:
        raise HTTPException(409, 'No hay stock suficiente para restar esa cantidad.')
    if data.cantidad < 0:
        from app.menu.availability import reserved_ingredients
        reserved = reserved_ingredients(restaurant_id)
        held = db.scalar(select(reserved.c.reservado).where(reserved.c.id_insumo == ingredient_id)) or Decimal(0)
        if row.stock_actual + data.cantidad < held:
            raise HTTPException(409, 'Ese stock está reservado para pedidos pendientes.')
    if abs(row.stock_actual + data.cantidad) > Decimal("999999999999.999999"):
        raise HTTPException(422, "El stock resultante supera el rango permitido.")
    row.stock_actual += data.cantidad
    db.add(MovimientoStock(id_insumo=ingredient_id, tipo=data.tipo, cantidad=data.cantidad,
                          motivo=f"Usuario #{actor_id}" + (f": {data.motivo}" if data.motivo else '')))
    db.commit()
    return row


def deactivate_ingredient(db: Session, restaurant_id: int, ingredient_id: int):
    lock_recipe_relations(db)
    row = ingredient(db, restaurant_id, ingredient_id)
    names = db.scalars(select(Producto.nombre).join(RecetaDetalle).where(
        RecetaDetalle.id_insumo == ingredient_id, Producto.id_restaurante == restaurant_id,
        Producto.activo.is_(True)).order_by(Producto.nombre)).all()
    if names:
        raise HTTPException(409, "El insumo se utiliza en productos activos: " + ", ".join(names) + ".")
    from app.db.models import DetallePedido, Pedido
    pending = db.scalar(select(Pedido.id_pedido).join(DetallePedido).join(
        RecetaDetalle, RecetaDetalle.id_producto == DetallePedido.id_producto).where(
        Pedido.id_restaurante == restaurant_id, Pedido.estado == 'Nuevo',
        RecetaDetalle.id_insumo == ingredient_id).limit(1))
    if pending:
        raise HTTPException(409, "El insumo está reservado para pedidos pendientes.")
    row.activo = False
    db.commit()
    return row
