from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AvailabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_disponibilidad: Literal["Disponible", "Ocupado", "No disponible"]


class CourierOutput(BaseModel):
    id_repartidor: int
    nombre: str
    zona: str | None
    activo: bool
    estado_disponibilidad: str
    ultimo_cambio: datetime | None


class CourierPage(BaseModel):
    id_restaurante: int
    abierto: bool
    delivery_disponible: bool
    repartidores: list[CourierOutput]
