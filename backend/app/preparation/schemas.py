from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_serializer, model_validator


class PreparationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    estado: Literal["En preparación", "Listo", "Cancelado"]
    version: int = Field(ge=0, strict=True)
    nueva_preparacion: StrictBool = False
    motivo: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def explicit_repeat(self):
        if self.nueva_preparacion and (self.estado != "En preparación" or not self.motivo):
            raise ValueError("La nueva preparación requiere motivo y estado En preparación.")
        return self


class StockOutput(BaseModel):
    id_insumo: int
    nombre: str
    unidad: str
    stock_actual: Decimal

    @field_serializer("stock_actual")
    def quantity(self, value: Decimal) -> str:
        return format(value, ".6f")


class ConsumptionOutput(BaseModel):
    id_movimiento: int
    id_insumo: int
    nombre: str
    unidad: str
    cantidad: Decimal
    fecha_hora: datetime
    motivo: str | None

    @field_serializer("cantidad")
    def quantity(self, value: Decimal) -> str:
        return format(value, ".6f")


class PreparationEvent(BaseModel):
    id_historial: int
    fecha_hora: datetime
    usuario: str
    estado: str
    tipo_evento: str
    detalle: str | None


class PreparationOutput(BaseModel):
    id_pedido: int
    estado: str
    version: int
    historial: list[PreparationEvent]
    movimientos: list[ConsumptionOutput]
