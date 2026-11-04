"""Gestión del mismo inventario consumido por HU-04; sin tablas adicionales."""

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.models import Insumo, MovimientoStock, RecetaDetalle
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
    motivo: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_quantity(self):
        if self.cantidad == 0 or self.tipo == "reposicion" and self.cantidad < 0:
            raise ValueError("La reposición debe ser positiva; el ajuste debe ser distinto de cero.")
        return self


def ingredient(db: Session, restaurant_id: int, ingredient_id: int):
    result = db.scalar(select(Insumo).where(Insumo.id_restaurante == restaurant_id,
                       Insumo.id_insumo == ingredient_id).with_for_update())
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
    if abs(row.stock_actual + data.cantidad) > Decimal("999999999999.999999"):
        raise HTTPException(422, "El stock resultante supera el rango permitido.")
    row.stock_actual += data.cantidad
    db.add(MovimientoStock(id_insumo=ingredient_id, tipo=data.tipo, cantidad=data.cantidad,
                          motivo=f"Usuario #{actor_id}: {data.motivo}"))
    db.commit()
    return row
