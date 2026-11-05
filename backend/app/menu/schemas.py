"""Entradas acotadas a los atributos aprobados del DER, sin asignación de restaurante."""

from decimal import Decimal
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_serializer, field_validator, model_validator

Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2, allow_inf_nan=False)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6, allow_inf_nan=False)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductInput(InputModel):
    nombre: str = Field(min_length=1, max_length=150)
    precio: Money
    costo_unitario: Money
    activo: StrictBool
    descripcion: str | None = Field(default=None, max_length=1000)
    imagen_url: str | None = Field(default=None, max_length=2000)

    @field_validator("descripcion", "imagen_url")
    @classmethod
    def empty_as_none(cls, value):
        return value or None

    @field_validator("imagen_url")
    @classmethod
    def valid_image_url(cls, value):
        if value is None:
            return value
        parsed = urlsplit(value)
        if (any(char.isspace() for char in value) or "\\" in value or any(ord(c) < 32 for c in value)
                or parsed.username or parsed.password):
            raise ValueError("URL de imagen inválida.")
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            return value
        if not parsed.scheme and not parsed.netloc and parsed.path.startswith("/images/") and ".." not in parsed.path:
            return value
        raise ValueError("Usá una URL http/https o una ruta dentro de /images/.")


class ProductOutput(ProductInput):
    model_config = ConfigDict(from_attributes=True)
    id_producto: int
    id_restaurante: int
    disponible_stock: bool = False
    insumos_faltantes: list[str] = []

    @field_serializer("precio", "costo_unitario")
    def money_as_text(self, value: Decimal) -> str:
        return format(value, ".2f")


class IngredientOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_insumo: int
    nombre: str
    unidad: str
    stock_actual: Decimal
    costo_unitario: Decimal


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
