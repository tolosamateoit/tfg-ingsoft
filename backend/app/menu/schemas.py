"""Entradas acotadas a los atributos aprobados del DER, sin asignación de restaurante."""

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_serializer, model_validator

Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2, allow_inf_nan=False)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6, allow_inf_nan=False)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductInput(InputModel):
    nombre: str = Field(min_length=1, max_length=150)
    precio: Money
    costo_unitario: Money
    activo: StrictBool


class ProductOutput(ProductInput):
    model_config = ConfigDict(from_attributes=True)
    id_producto: int
    id_restaurante: int

    @field_serializer("precio", "costo_unitario")
    def money_as_text(self, value: Decimal) -> str:
        return format(value, ".2f")


class IngredientOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_insumo: int
    nombre: str
    unidad: str


class RecipeItemInput(InputModel):
    id_insumo: int = Field(gt=0, strict=True)
    cantidad: Quantity
    unidad: str = Field(min_length=1, max_length=32)


class RecipeInput(InputModel):
    detalles: list[RecipeItemInput] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_ingredients(self):
        if len({item.id_insumo for item in self.detalles}) != len(self.detalles):
            raise ValueError("Un insumo no puede repetirse en la receta.")
        return self


class RecipeItemOutput(RecipeItemInput):
    nombre: str


class RecipeOutput(BaseModel):
    id_producto: int
    detalles: list[RecipeItemOutput]
