"""DTO de consulta: el cliente no recibe costos internos ni datos de otros usuarios."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


class OrderItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_producto: int = Field(gt=0, strict=True)
    cantidad: int = Field(gt=0, le=2147483647, strict=True)


class OrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    correo_cliente: str | None = Field(default=None, min_length=3, max_length=254)
    direccion_entrega: str = Field(min_length=1, max_length=500)
    referencia_local: str | None = Field(default=None, max_length=500)
    zona_entrega: str | None = Field(default=None, max_length=150)
    medio_pago: str = Field(min_length=1, max_length=50)
    distancia_km: Annotated[Decimal, Field(ge=0, le=5, max_digits=12, decimal_places=3, allow_inf_nan=False)]
    detalles: list[OrderItemInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_products(self):
        if len({item.id_producto for item in self.detalles}) != len(self.detalles):
            raise ValueError("No repitas productos; modificá su cantidad.")
        return self


class RestaurantOutput(BaseModel):
    id_restaurante: int
    nombre: str
    abierto: bool
    delivery_disponible: bool


class MenuItemOutput(BaseModel):
    id_producto: int
    nombre: str
    precio: Decimal
    descripcion: str | None = None
    imagen_url: str | None = None

    @field_serializer("precio")
    def money_as_text(self, value: Decimal) -> str:
        return format(value, ".2f")


class CustomerMenuOutput(BaseModel):
    restaurante: RestaurantOutput
    productos: list[MenuItemOutput]


class OrderSummary(BaseModel):
    id_pedido: int
    id_restaurante: int
    restaurante: str
    cliente: str
    fecha_hora: datetime
    estado: str
    importe_total: Decimal
    medio_pago: str
    estado_pago: str
    estado_desde: datetime
    resumen_productos: str = ""
    id_entrega: int | None = None
    id_repartidor: int | None = None
    repartidor: str | None = None
    estado_entrega: str | None = None
    advertencia_importe: str | None = None
    advertencia_entrega: str | None = None

    @field_serializer("importe_total")
    def money_as_text(self, value: Decimal) -> str:
        return format(value, ".2f")


class OrderItemOutput(BaseModel):
    id_producto: int
    nombre: str
    cantidad: int
    precio_unitario: Decimal
    subtotal: Decimal

    @field_serializer("precio_unitario", "subtotal")
    def money_as_text(self, value: Decimal) -> str:
        return format(value, ".2f")


class OrderOutput(OrderSummary):
    direccion_entrega: str
    referencia_local: str | None
    zona_entrega: str | None
    distancia_km: Decimal | None
    detalles: list[OrderItemOutput]
    preparacion_minutos: Decimal | None = None
    entrega_minutos: Decimal | None = None
    economia: dict[str, str] | None = None

    @field_serializer("distancia_km")
    def distance_as_text(self, value: Decimal | None) -> str | None:
        return format(value, ".2f") if value is not None else None


class OrderPage(BaseModel):
    pedidos: list[OrderSummary]
    total: int
    limit: int
    offset: int
    fecha_operativa: date | None = None
    periodo: str = "historial"
