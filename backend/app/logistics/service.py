from fractions import Fraction
from decimal import Decimal, ROUND_HALF_UP, localcontext

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Cliente, Entrega, HistorialPedido, HistorialRepartidor, Pedido, Repartidor, Restaurante, Usuario
from app.logistics.priority import calculate, refresh_priorities
from app.logistics.schemas import AssignmentOutput, DeliveryOutput, DeliveryStateInput, DistanceInput, TrackingEvent, TrackingOutput
from app.orders.service import lock_order_relations
from app.preparation.service import scoped_order

IN_PROGRESS = ("Asignado", "En camino")
FINISHED = ("Entregado", "No entregado")


def delivery_cost(restaurant: Restaurante, order: Pedido) -> Decimal:
    with localcontext() as context:
        context.prec = 40
        cost = (restaurant.costo_fijo_entrega + restaurant.costo_por_km * order.distancia_km).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
    if cost > Decimal("9999999999999999.99"):
        raise HTTPException(422, "El costo de entrega supera el máximo permitido.")
    return cost


def assign_ready_orders(db: Session, user: Usuario, restaurant_id: int) -> AssignmentOutput:
    lock_order_relations(db)
    restaurant = db.scalar(select(Restaurante).where(Restaurante.id_restaurante == restaurant_id).with_for_update(read=True))
    if restaurant is None:
        raise HTTPException(404, "Restaurante no disponible.")
    _, ordered = refresh_priorities(db, restaurant_id)
    existing = set(db.scalars(select(Entrega.id_pedido).where(Entrega.id_pedido.in_([order.id_pedido for order in ordered]))).all())
    ready = [order for order in ordered if order.estado == "Listo" and order.id_pedido not in existing]
    candidates = ranked_couriers(db, restaurant_id)
    # Al asignar pasa a Ocupado: se usa cada candidato una vez en este lote.
    plan = [(order, courier, account, delivery_cost(restaurant, order))
            for order, (courier, account) in zip(ready, candidates)]
    created = []
    try:
        for order, courier, account, cost in plan:
            delivery = Entrega(id_pedido=order.id_pedido, id_repartidor=courier.id_repartidor,
                               estado="Asignado", costo_repartidor=cost)
            db.add(delivery)
            order.estado = "Asignado"
            courier.estado_disponibilidad = "Ocupado"
            db.add(HistorialRepartidor(id_repartidor=courier.id_repartidor, estado="Ocupado"))
            db.add(HistorialPedido(id_pedido=order.id_pedido, id_usuario=user.id_usuario, tipo_evento="asignacion",
                                  estado="Asignado", detalle=f"Repartidor asignado: {account.nombre} (#{courier.id_repartidor})."))
            created.append(delivery)
        db.flush()
        ids = [delivery.id_entrega for delivery in created]
        by_id = {row[0].id_entrega: delivery_output(row) for row in db.execute(
            delivery_query(user).where(Entrega.id_entrega.in_(ids))).all()}
        result = AssignmentOutput(entregas=[by_id[id] for id in ids], pendientes=len(ready) - len(created))
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo guardar la asignación. Actualizá y volvé a intentar.") from None


def delivery_query(user: Usuario):
    query = (select(Entrega, Pedido, Usuario.nombre, Cliente.nombre)
             .join(Pedido, Pedido.id_pedido == Entrega.id_pedido)
             .join(Cliente, Cliente.id_cliente == Pedido.id_cliente)
             .join(Repartidor, Repartidor.id_repartidor == Entrega.id_repartidor)
             .join(Usuario, Usuario.id_usuario == Repartidor.id_usuario))
    if user.rol in {"personal", "propietario"}:
        return query.where(Pedido.id_restaurante == user.id_restaurante, Usuario.id_restaurante == user.id_restaurante)
    if user.rol == "repartidor":
        return query.where(Repartidor.id_usuario == user.id_usuario, Pedido.id_restaurante == user.id_restaurante)
    if user.rol == "cliente":
        return query.where(Cliente.id_usuario == user.id_usuario)
    raise HTTPException(403, "No tenés permiso para consultar entregas.")


def delivery_output(row) -> DeliveryOutput:
    delivery, order, courier, client = row
    return DeliveryOutput(id_entrega=delivery.id_entrega, id_pedido=order.id_pedido,
                          id_repartidor=delivery.id_repartidor, repartidor=courier, cliente=client,
                          direccion_entrega=order.direccion_entrega, referencia_local=order.referencia_local,
                          estado=delivery.estado, fecha_asignacion=delivery.fecha_asignacion)


def deliveries(db: Session, user: Usuario, offset: int) -> list[DeliveryOutput]:
    return [delivery_output(row) for row in db.execute(delivery_query(user)
            .order_by(Entrega.fecha_asignacion.desc(), Entrega.id_entrega.desc()).offset(offset).limit(20)).all()]


def tracking(db: Session, user: Usuario, order_id: int) -> TrackingOutput:
    query = select(Pedido).join(Cliente, Cliente.id_cliente == Pedido.id_cliente).where(Pedido.id_pedido == order_id)
    if user.rol in {"personal", "propietario"}:
        query = query.where(Pedido.id_restaurante == user.id_restaurante)
    elif user.rol == "cliente":
        query = query.where(Cliente.id_usuario == user.id_usuario)
    elif user.rol == "repartidor":
        query = query.join(Entrega, Entrega.id_pedido == Pedido.id_pedido).join(Repartidor).where(
            Repartidor.id_usuario == user.id_usuario, Pedido.id_restaurante == user.id_restaurante)
    else:
        raise HTTPException(403, "No tenés permiso para consultar el seguimiento.")
    order = db.scalar(query)
    if order is None:
        raise HTTPException(404, "Pedido no disponible.")
    row = db.execute(delivery_query(user).where(Entrega.id_pedido == order_id)).first()
    events = db.execute(select(HistorialPedido.id_historial, HistorialPedido.fecha_hora,
                               Usuario.nombre.label("usuario"), HistorialPedido.estado, HistorialPedido.detalle)
                        .join(Usuario, Usuario.id_usuario == HistorialPedido.id_usuario)
                        .where(HistorialPedido.id_pedido == order_id).order_by(HistorialPedido.id_historial)).mappings()
    return TrackingOutput(id_pedido=order_id, estado_pedido=order.estado,
                          entrega=delivery_output(row) if row else None,
                          historial=[TrackingEvent(**event) for event in events])


def change_distance(db: Session, user: Usuario, restaurant_id: int, order_id: int, data: DistanceInput) -> TrackingOutput:
    lock_order_relations(db)
    order = scoped_order(db, restaurant_id, order_id, lock=True)
    if order.estado not in {"Nuevo", "En preparación", "Listo"} or db.scalar(select(Entrega.id_entrega).where(Entrega.id_pedido == order_id)):
        raise HTTPException(409, "La distancia solo puede corregirse antes de asignar la entrega.")
    if order.distancia_km != data.distancia_km:
        previous = order.distancia_km
        order.distancia_km = data.distancia_km
        calculate(order, db.scalar(select(func.now())))
        db.add(HistorialPedido(id_pedido=order_id, id_usuario=user.id_usuario, tipo_evento="distancia", estado=order.estado,
                              detalle=f"Distancia estimada: {previous} → {data.distancia_km} km."))
    db.flush()
    result = tracking(db, user, order_id)
    db.commit()
    return result


def ranked_couriers(db: Session, restaurant_id: int):
    candidates = db.execute(select(Repartidor, Usuario).join(Usuario, Usuario.id_usuario == Repartidor.id_usuario)
                            .where(Usuario.id_restaurante == restaurant_id, Usuario.rol == "repartidor", Usuario.activo.is_(True),
                                   Repartidor.estado_disponibilidad == "Disponible")
                            .order_by(Repartidor.id_repartidor).with_for_update()).all()
    stats = {courier.id_repartidor: [0, 0, 0] for courier, _ in candidates}
    rows = db.execute(select(Entrega.id_repartidor, Entrega.estado, func.count())
                      .join(Pedido, Pedido.id_pedido == Entrega.id_pedido)
                      .where(Pedido.id_restaurante == restaurant_id, Entrega.id_repartidor.in_(stats))
                      .group_by(Entrega.id_repartidor, Entrega.estado)).all()
    for courier_id, state, count in rows:
        if state in IN_PROGRESS:
            stats[courier_id][0] += count
        if state in FINISHED:
            stats[courier_id][2] += count
            if state == "Entregado":
                stats[courier_id][1] += count
    return sorted(candidates, key=lambda row: (stats[row[0].id_repartidor][0],
                  -Fraction(stats[row[0].id_repartidor][1], stats[row[0].id_repartidor][2] or 1),
                  row[1].nombre.casefold(), row[1].nombre, row[0].id_repartidor))


def change_delivery_state(db: Session, user: Usuario, delivery_id: int, data: DeliveryStateInput) -> TrackingOutput:
    lock_order_relations(db)
    row = db.execute(delivery_query(user).where(Entrega.id_entrega == delivery_id).with_for_update()).first()
    if row is None:
        raise HTTPException(404, "Entrega no disponible.")
    delivery, order, _, _ = row
    if data.estado == delivery.estado:
        return tracking(db, user, order.id_pedido)
    if not (delivery.estado == "Asignado" and data.estado == "En camino"
            or delivery.estado == "En camino" and data.estado in FINISHED):
        raise HTTPException(409, "Transición de entrega no permitida.")
    try:
        delivery.estado = data.estado
        order.estado = data.estado
        db.add(HistorialPedido(id_pedido=order.id_pedido, id_usuario=user.id_usuario, tipo_evento="entrega",
                              estado=data.estado, detalle=f"Entrega #{delivery_id}: {data.estado}."))
        db.flush()
        if data.estado in FINISHED:
            courier = db.get(Repartidor, delivery.id_repartidor, with_for_update=True)
            remaining = db.scalar(select(func.count()).select_from(Entrega).where(
                Entrega.id_repartidor == courier.id_repartidor, Entrega.estado.in_(IN_PROGRESS)))
            if remaining == 0 and courier.estado_disponibilidad == "Ocupado":
                courier.estado_disponibilidad = "Disponible"
                db.add(HistorialRepartidor(id_repartidor=courier.id_repartidor, estado="Disponible"))
        db.flush()
        result = tracking(db, user, order.id_pedido)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo actualizar la entrega. Actualizá y volvé a intentar.") from None
