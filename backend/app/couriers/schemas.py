from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from app.auth.security import normalize_email
from app.menu.schemas import InputModel, Money


class CourierInput(InputModel):
    nombre: str = Field(min_length=1, max_length=150)
    correo: str = Field(min_length=3, max_length=254)
    contrasena: SecretStr = Field(min_length=15, max_length=20)
    telefono: str | None = Field(default=None, max_length=50)
    zona: str | None = Field(default=None, max_length=150)

    @field_validator("correo")
    @classmethod
    def valid_email(cls, value):
        return normalize_email(value)


class RatesInput(InputModel):
    costo_fijo_entrega: Money
    costo_por_km: Money


class RatesOutput(RatesInput):
    model_config = ConfigDict(from_attributes=True)


class AvailabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_disponibilidad: Literal["Disponible", "No disponible"]


class CourierOutput(BaseModel):
    id_repartidor: int
    nombre: str
    zona: str | None
    activo: bool
    estado_disponibilidad: str
    ultimo_cambio: datetime | None
    entrega_activa: bool = False


class CourierPage(BaseModel):
    id_restaurante: int
    abierto: bool
    delivery_disponible: bool
    repartidores: list[CourierOutput]
