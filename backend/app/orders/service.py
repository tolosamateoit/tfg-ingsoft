"""Consultas acotadas por rol, titularidad y restaurante en PostgreSQL."""

from fastapi import HTTPException
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.db.models import Cliente, DetallePedido, Pedido, Producto, Repartidor, Restaurante, Usuario
from app.orders.schemas import (
    CustomerMenuOutput, MenuItemOutput, OrderItemOutput, OrderOutput, OrderPage,
    OrderSummary, RestaurantOutput,
)


def courier_available(restaurant_id):
    return exists(select(Repartidor.id_repartidor).join(Usuario, Usuario.id_usuario == Repartidor.id_usuario)
                  .where(Usuario.id_restaurante == restaurant_id, Usuario.activo.is_(True),
                         Usuario.rol == "repartidor", Repartidor.estado_disponibilidad == "Disponible"))


def customer_restaurants(db: Session) -> list[RestaurantOutput]:
    rows = db.execute(select(Restaurante.id_restaurante, Restaurante.nombre, Restaurante.abierto,
                             (Restaurante.abierto & courier_available(Restaurante.id_restaurante)).label("delivery_disponible"))
                      .order_by(Restaurante.nombre, Restaurante.id_restaurante)).mappings()
    return [RestaurantOutput(**row) for row in rows]


def customer_menu(db: Session, restaurant_id: int) -> CustomerMenuOutput:
    row = db.execute(select(Restaurante.id_restaurante, Restaurante.nombre, Restaurante.abierto,
                            (Restaurante.abierto & courier_available(Restaurante.id_restaurante)).label("delivery_disponible"))
                     .where(Restaurante.id_restaurante == restaurant_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "Restaurante no disponible.")
    products = db.execute(select(Producto.id_producto, Producto.nombre, Producto.precio)
                          .where(Producto.id_restaurante == restaurant_id, Producto.activo.is_(True))
                          .order_by(Producto.nombre, Producto.id_producto)).mappings()
    return CustomerMenuOutput(restaurante=RestaurantOutput(**row),
                              productos=[MenuItemOutput(**product) for product in products])


def scoped_orders(user: Usuario):
    query = select(Pedido).join(Cliente, Cliente.id_cliente == Pedido.id_cliente)
    if user.rol == "cliente":
        return query.where(Cliente.id_usuario == user.id_usuario)
    if user.rol in {"personal", "propietario"} and user.id_restaurante is not None:
        return query.where(Pedido.id_restaurante == user.id_restaurante)
    raise HTTPException(403, "No tenés permiso para consultar pedidos.")


def order_summary(order: Pedido, restaurant: str, client: str) -> OrderSummary:
    return OrderSummary(id_pedido=order.id_pedido, id_restaurante=order.id_restaurante,
                        restaurante=restaurant, cliente=client, fecha_hora=order.fecha_hora,
                        estado=order.estado, importe_total=order.importe_total,
                        medio_pago=order.medio_pago, estado_pago=order.estado_pago)


def list_orders(db: Session, user: Usuario, limit: int, offset: int) -> OrderPage:
    scoped = scoped_orders(user)
    total = db.scalar(select(func.count()).select_from(scoped.subquery()))
    rows = db.execute(scoped.add_columns(Restaurante.nombre, Cliente.nombre)
                      .join(Restaurante, Restaurante.id_restaurante == Pedido.id_restaurante)
                      .order_by(Pedido.fecha_hora.desc(), Pedido.id_pedido.desc()).limit(limit).offset(offset)).all()
    return OrderPage(pedidos=[order_summary(order, restaurant, client) for order, restaurant, client in rows],
                     total=total, limit=limit, offset=offset)


def read_order(db: Session, user: Usuario, order_id: int) -> OrderOutput:
    row = db.execute(scoped_orders(user).add_columns(Restaurante.nombre, Cliente.nombre)
                     .join(Restaurante, Restaurante.id_restaurante == Pedido.id_restaurante)
                     .where(Pedido.id_pedido == order_id)).first()
    if row is None:
        raise HTTPException(404, "Pedido no disponible.")
    order, restaurant, client = row
    details = db.execute(select(DetallePedido.id_producto, Producto.nombre, DetallePedido.cantidad,
                                DetallePedido.precio_unitario)
                         .join(Producto, Producto.id_producto == DetallePedido.id_producto)
                         .where(DetallePedido.id_pedido == order_id)
                         .order_by(DetallePedido.id_detalle)).mappings()
    return OrderOutput(**order_summary(order, restaurant, client).model_dump(),
                       direccion_entrega=order.direccion_entrega, referencia_local=order.referencia_local,
                       zona_entrega=order.zona_entrega, distancia_km=order.distancia_km,
                       detalles=[OrderItemOutput(**detail, subtotal=detail["precio_unitario"] * detail["cantidad"])
                                 for detail in details])
