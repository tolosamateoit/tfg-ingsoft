"""DTO de consulta: el cliente no recibe costos internos ni datos de otros usuarios."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_serializer


class RestaurantOutput(BaseModel):
    id_restaurante: int
    nombre: str
    abierto: bool
    delivery_disponible: bool


class MenuItemOutput(BaseModel):
    id_producto: int
    nombre: str
    precio: Decimal

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
    distancia_km: Decimal
    detalles: list[OrderItemOutput]


class OrderPage(BaseModel):
    pedidos: list[OrderSummary]
    total: int
    limit: int
    offset: int
