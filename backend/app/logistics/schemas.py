from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class PriorityFactor(BaseModel):
    codigo: str
    nombre: str
    aporte: Decimal | None
    barra: Decimal
    detalle: str


class PriorityOutput(BaseModel):
    id_pedido: int
    fecha_hora: datetime
    estado: str
    distancia_km: Decimal | None
    puntaje_prioridad: Decimal
    factores_prioridad: dict[str, str | int | None]
    posicion: int = 0
    explicacion: str = ''
    factores: list[PriorityFactor] = []
    repartidor: str | None = None
    resumen_productos: str = ""
    advertencia_importe: str | None = None


class PriorityPage(BaseModel):
    calculada_en: datetime
    pedidos: list[PriorityOutput]


class DistanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    distancia_km: Annotated[Decimal, Field(ge=0, le=10, max_digits=12, decimal_places=3, allow_inf_nan=False)]


class DeliveryStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado: Literal["En camino", "Entregado", "No entregado"]


class DeliveryOutput(BaseModel):
    id_entrega: int
    id_pedido: int
    id_repartidor: int
    repartidor: str
    cliente: str
    direccion_entrega: str
    referencia_local: str | None
    estado: str
    fecha_asignacion: datetime
    distancia_km: Decimal | None
    resumen_productos: str = ""
    advertencia_entrega: str | None = None


class TrackingEvent(BaseModel):
    id_historial: int
    fecha_hora: datetime
    usuario: str | None
    estado: str
    detalle: str | None


class TrackingOutput(BaseModel):
    id_pedido: int
    estado_pedido: str
    entrega: DeliveryOutput | None
    historial: list[TrackingEvent]


class AssignmentOutput(BaseModel):
    entregas: list[DeliveryOutput]
    pendientes: int


class AssignmentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id_pedido: int = Field(gt=0, strict=True)
    id_repartidor: int = Field(gt=0, strict=True)
    version: int = Field(ge=0, strict=True)
    distancia_km: Annotated[Decimal, Field(ge=0, le=10, max_digits=12, decimal_places=3, allow_inf_nan=False)] | None = None
