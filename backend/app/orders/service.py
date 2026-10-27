"""Consultas acotadas por rol, titularidad y restaurante en PostgreSQL."""

from decimal import Decimal, localcontext

from fastapi import HTTPException
from sqlalchemy import exists, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Cliente, DetallePedido, HistorialPedido, Pedido, Producto, Repartidor, Restaurante, Usuario
from app.orders.schemas import (
    CustomerMenuOutput, MenuItemOutput, OrderItemOutput, OrderOutput, OrderPage,
    OrderSummary, RestaurantOutput, OrderInput,
)


def lock_order_relations(db: Session):
    # El trigger del DER toma este mismo lock antes de bloquear filas.
    db.execute(text("SELECT pg_advisory_xact_lock(1647042, 1)"))


def create_order(db: Session, user: Usuario, restaurant_id: int, data: OrderInput) -> OrderOutput:
    lock_order_relations(db)
    restaurant = db.scalar(select(Restaurante).where(Restaurante.id_restaurante == restaurant_id)
                           .with_for_update(read=True))
    if restaurant is None or not restaurant.abierto:
        raise HTTPException(409, "El restaurante debe estar abierto para confirmar el pedido.")
    courier = db.execute(select(Repartidor, Usuario).join(Usuario, Usuario.id_usuario == Repartidor.id_usuario)
                         .where(Usuario.id_restaurante == restaurant_id, Usuario.activo.is_(True),
                                Usuario.rol == "repartidor", Repartidor.estado_disponibilidad == "Disponible")
                         .order_by(Repartidor.id_repartidor).limit(1).with_for_update(read=True)).first()
    if courier is None:
        raise HTTPException(409, "No hay repartidores disponibles en este restaurante.")
    client = db.scalar(select(Cliente).join(Usuario, Usuario.id_usuario == Cliente.id_usuario)
                       .where(func.lower(Usuario.correo) == data.correo_cliente.lower(),
                              Usuario.rol == "cliente", Usuario.activo.is_(True)).with_for_update(read=True))
    if client is None:
        raise HTTPException(422, "Ingresá el correo de una cuenta de cliente activa y precargada.")
    ids = [item.id_producto for item in data.detalles]
    products = db.scalars(select(Producto).where(Producto.id_restaurante == restaurant_id,
                                               Producto.activo.is_(True), Producto.id_producto.in_(ids))
                          .order_by(Producto.id_producto).with_for_update(read=True)).all()
    by_id = {product.id_producto: product for product in products}
    if len(by_id) != len(ids):
        raise HTTPException(422, "Todos los productos deben estar activos y pertenecer al restaurante.")
    with localcontext() as context:
        context.prec = 40
        amount = sum((by_id[item.id_producto].precio * item.cantidad for item in data.detalles), Decimal(0))
        cost = sum((by_id[item.id_producto].costo_unitario * item.cantidad for item in data.detalles), Decimal(0))
    if max(amount, cost) > Decimal("9999999999999999.99"):
        raise HTTPException(422, "El importe o costo del pedido supera el máximo permitido.")
    order = Pedido(id_restaurante=restaurant_id, id_cliente=client.id_cliente, estado="Nuevo",
                   direccion_entrega=data.direccion_entrega, referencia_local=data.referencia_local or None,
                   zona_entrega=data.zona_entrega or None, medio_pago=data.medio_pago, estado_pago="pendiente",
                   distancia_km=data.distancia_km, importe_total=amount, costo_total=cost)
    try:
        db.add(order)
        db.flush()
        db.add_all([DetallePedido(id_pedido=order.id_pedido, id_producto=item.id_producto,
                                 cantidad=item.cantidad, precio_unitario=by_id[item.id_producto].precio)
                    for item in data.detalles])
        db.add(HistorialPedido(id_pedido=order.id_pedido, id_usuario=user.id_usuario,
                              tipo_evento="registro", estado="Nuevo", detalle="Registro del pedido."))
        db.flush()
        result = read_order(db, user, order.id_pedido)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo guardar el pedido. Actualizá los datos y volvé a intentar.") from None


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
