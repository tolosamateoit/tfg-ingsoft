"""Consultas acotadas por rol, titularidad y restaurante en PostgreSQL."""

from decimal import Decimal, localcontext

from fastapi import HTTPException
from sqlalchemy import exists, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.auth.service import as_utc
from app.orders.operational_date import operational_date, operational_day_bounds
from app.orders.summaries import summary_data
from app.orders.distance import unconfirmed_events

from app.db.models import Cliente, DetallePedido, Entrega, HistorialPedido, Pedido, Producto, Repartidor, Restaurante, Usuario
from app.orders.schemas import (
    CustomerMenuOutput, MenuItemOutput, OrderItemOutput, OrderOutput, OrderPage,
    OrderSummary, RestaurantOutput, OrderInput,
)


def lock_order_relations(db: Session):
    # El trigger del DER toma este mismo lock antes de bloquear filas.
    db.execute(text("SELECT pg_advisory_xact_lock(1647042, 1)"))


def create_order(db: Session, user: Usuario, restaurant_id: int, data: OrderInput) -> OrderOutput:
    if user.rol not in {"cliente", "personal", "propietario"} or (
        user.rol != "cliente" and user.id_restaurante != restaurant_id
    ):
        raise HTTPException(403, "No tenés permiso para registrar pedidos en este restaurante.")
    if user.rol == "cliente" and data.correo_cliente is not None:
        raise HTTPException(422, "El cliente del pedido se obtiene de tu sesión.")
    if user.rol != "cliente" and not data.correo_cliente:
        raise HTTPException(422, "Ingresá el correo del cliente.")
    lock_order_relations(db)
    restaurant = db.scalar(select(Restaurante).where(Restaurante.id_restaurante == restaurant_id)
                           .with_for_update(read=True))
    if restaurant is None or not restaurant.abierto:
        raise HTTPException(409, "El restaurante debe estar abierto para confirmar el pedido.")
    courier = db.execute(select(Repartidor, Usuario).join(Usuario, Usuario.id_usuario == Repartidor.id_usuario)
                         .where(Usuario.id_restaurante == restaurant_id, Usuario.activo.is_(True),
                                Usuario.rol == "repartidor", Repartidor.estado_disponibilidad == "Disponible",
                                ~exists(select(Entrega.id_entrega).where(Entrega.id_repartidor == Repartidor.id_repartidor,
                                                                       Entrega.estado.in_(['Asignado', 'En camino', 'asignada']))))
                         .order_by(Repartidor.id_repartidor).limit(1).with_for_update(read=True)).first()
    if courier is None:
        raise HTTPException(409, "No hay repartidores disponibles en este restaurante.")
    client = db.scalar(select(Cliente).join(Usuario, Usuario.id_usuario == Cliente.id_usuario)
                       .where(Usuario.id_usuario == user.id_usuario if user.rol == "cliente"
                              else func.lower(Usuario.correo) == data.correo_cliente.lower(),
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
    from app.menu.availability import validate_order_stock
    validate_order_stock(db, restaurant_id, data.detalles)
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
        from app.demo_history.simulation import local_demo, MARKER
        db.add(HistorialPedido(id_pedido=order.id_pedido, id_usuario=user.id_usuario,
            tipo_evento='registro', estado='Nuevo', detalle=f'Registro del pedido. Distancia: {data.distancia_km} km.'
            + (f' [{MARKER}]' if local_demo() else '')))
        db.flush()
        result = _order_output(db, user, order, restaurant, client.nombre)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo guardar el pedido. Actualizá los datos y volvé a intentar.") from None


def courier_available(restaurant_id):
    return exists(select(Repartidor.id_repartidor).join(Usuario, Usuario.id_usuario == Repartidor.id_usuario)
                  .where(Usuario.id_restaurante == restaurant_id, Usuario.activo.is_(True),
                         Usuario.rol == "repartidor", Repartidor.estado_disponibilidad == "Disponible",
                         ~exists(select(Entrega.id_entrega).where(Entrega.id_repartidor == Repartidor.id_repartidor,
                                                                Entrega.estado.in_(['Asignado', 'En camino', 'asignada'])))))


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
    products = db.execute(select(Producto.id_producto, Producto.nombre, Producto.precio, Producto.descripcion, Producto.imagen_url)
                          .where(Producto.id_restaurante == restaurant_id, Producto.activo.is_(True))
                          .order_by(Producto.nombre, Producto.id_producto)).mappings()
    from app.menu.availability import product_availability
    available = product_availability(db, restaurant_id)
    return CustomerMenuOutput(restaurante=RestaurantOutput(**row),
        productos=[MenuItemOutput(**product, disponible_stock=available.get(product['id_producto'], False)) for product in products])


def scoped_orders(user: Usuario):
    query = select(Pedido).join(Cliente, Cliente.id_cliente == Pedido.id_cliente)
    if user.rol == "cliente":
        return query.where(Cliente.id_usuario == user.id_usuario)
    if user.rol in {"personal", "propietario"} and user.id_restaurante is not None:
        return query.where(Pedido.id_restaurante == user.id_restaurante)
    if user.rol == 'repartidor' and user.id_restaurante is not None:
        return query.join(Entrega).join(Repartidor).where(Repartidor.id_usuario == user.id_usuario,
            Pedido.id_restaurante == user.id_restaurante)
    raise HTTPException(403, "No tenés permiso para consultar pedidos.")


def order_summary(order: Pedido, restaurant: str, client: str, state_since=None) -> OrderSummary:
    return OrderSummary(id_pedido=order.id_pedido, id_restaurante=order.id_restaurante,
                        restaurante=restaurant, cliente=client, fecha_hora=as_utc(order.fecha_hora),
                        estado=order.estado, importe_total=order.importe_total,
                        medio_pago=order.medio_pago, estado_pago=order.estado_pago,
                        estado_desde=as_utc(state_since or order.fecha_hora))


def state_since_query():
    return select(func.max(HistorialPedido.fecha_hora)).where(
        HistorialPedido.id_pedido == Pedido.id_pedido, HistorialPedido.estado == Pedido.estado,
        HistorialPedido.tipo_evento != "distancia",
    ).correlate(Pedido).scalar_subquery()


def list_orders(db: Session, user: Usuario, limit: int, offset: int, periodo: str = "historial", fecha=None) -> OrderPage:
    scoped = scoped_orders(user)
    if periodo not in {"dia", "historial"}:
        raise HTTPException(422, "Período inválido.")
    reference = operational_date(db, user.id_restaurante) if user.rol in {"personal", "propietario"} else None
    if periodo == "dia":
        if user.rol not in {"personal", "propietario"}:
            raise HTTPException(403, "La fecha operativa requiere el contexto del restaurante.")
        if reference is None:
            scoped = scoped.where(False)
        else:
            start, end = operational_day_bounds(reference)
            scoped = scoped.where(Pedido.fecha_hora >= start, Pedido.fecha_hora < end)
    if fecha is not None:
        start, end = operational_day_bounds(fecha)
        scoped = scoped.where(Pedido.fecha_hora >= start, Pedido.fecha_hora < end)
    total = db.scalar(select(func.count()).select_from(scoped.subquery()))
    rows = db.execute(scoped.add_columns(Restaurante.nombre, Cliente.nombre, state_since_query())
                      .join(Restaurante, Restaurante.id_restaurante == Pedido.id_restaurante)
                      .order_by(Pedido.fecha_hora.desc(), Pedido.id_pedido.desc()).limit(limit).offset(offset)).all()
    extra = summary_data(db, [row[0].id_pedido for row in rows])
    from app.analytics.operational import owner_order_warnings
    warnings = owner_order_warnings(db, user, [row[0].id_pedido for row in rows], reference_day=reference,
                                   target_orders=[row[0] for row in rows])
    for oid, warning in warnings.items():
        extra[oid].update(warning)
    return OrderPage(pedidos=[order_summary(order, restaurant, client, since).model_copy(update=extra[order.id_pedido])
                             for order, restaurant, client, since in rows],
                     total=total, limit=limit, offset=offset, fecha_operativa=reference, periodo=periodo)


def read_order(db: Session, user: Usuario, order_id: int) -> OrderOutput:
    row = db.execute(scoped_orders(user).add_columns(Restaurante, Cliente.nombre)
                     .join(Restaurante, Restaurante.id_restaurante == Pedido.id_restaurante)
                     .where(Pedido.id_pedido == order_id)).first()
    if row is None:
        raise HTTPException(404, "Pedido no disponible.")
    return _order_output(db, user, *row)


def _order_output(db, user, order, restaurant, client):
    """Solo pedidos ya autorizados por read_order o create_order."""
    order_id = order.id_pedido
    details = db.execute(select(DetallePedido.id_producto, Producto.nombre, DetallePedido.cantidad,
                                DetallePedido.precio_unitario)
                         .join(Producto, Producto.id_producto == DetallePedido.id_producto)
                         .where(DetallePedido.id_pedido == order_id)
                         .order_by(DetallePedido.id_detalle)).mappings().all()
    history = db.scalars(select(HistorialPedido).where(HistorialPedido.id_pedido == order_id)
                         .order_by(HistorialPedido.fecha_hora, HistorialPedido.id_historial)).all()
    from app.orders.timing import order_times
    since, preparation_time, delivery_time = order_times(order, history)
    economy = None
    known_distance = order_id not in unconfirmed_events(
        (event.id_pedido, event.tipo_evento, event.detalle) for event in history)
    delivery_row = db.execute(select(Entrega, Usuario.nombre).select_from(Entrega)
        .join(Repartidor, Repartidor.id_repartidor == Entrega.id_repartidor)
        .join(Usuario, Usuario.id_usuario == Repartidor.id_usuario)
        .where(Entrega.id_pedido == order_id, Usuario.id_restaurante == order.id_restaurante)).first()
    delivery = delivery_row[0] if delivery_row else None
    if user.rol == "propietario" and known_distance:
        from app.logistics.service import delivery_cost
        rates = restaurant
        estimated = delivery_cost(rates, order)
        economy = {key: format(value, ".2f") for key, value in {
            "importe_productos": order.importe_total, "costo_productos": order.costo_total,
            "costo_fijo_entrega": rates.costo_fijo_entrega, "costo_por_km": rates.costo_por_km,
            "componente_km": rates.costo_por_km * order.distancia_km,
            "costo_entrega": estimated, "margen_estimado": order.importe_total - order.costo_total - estimated,
        }.items()}
        if delivery:
            economy["costo_entrega_asignado"] = format(delivery.costo_repartidor, ".2f")
    extra = summary_data(db, [order_id],
        details=[(order_id, detail['cantidad'], detail['nombre']) for detail in details],
        deliveries=[(order_id, delivery.id_entrega, delivery.id_repartidor, delivery_row[1], delivery.estado)] if delivery else [])
    summary = order_summary(order, restaurant.nombre, client, since).model_copy(update=extra[order_id])
    from app.analytics.operational import owner_order_warnings
    summary = summary.model_copy(update=owner_order_warnings(db, user, [order_id], target_orders=[order]).get(order_id, {}))
    return OrderOutput(**summary.model_dump(),
                       direccion_entrega=order.direccion_entrega, referencia_local=order.referencia_local,
                       zona_entrega=order.zona_entrega, distancia_km=order.distancia_km if known_distance else None,
                       preparacion_minutos=preparation_time, entrega_minutos=delivery_time, economia=economy,
                       detalles=[OrderItemOutput(**detail, subtotal=detail["precio_unitario"] * detail["cantidad"])
                                 for detail in details])
