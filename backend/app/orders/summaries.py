"""Enriquecimiento por lote de pedidos ya autorizados; sin una consulta por fila."""

from sqlalchemy import select

from app.db.models import DetallePedido, Entrega, Pedido, Producto, Repartidor, Usuario


def summary_data(db, order_ids):
    ids = list(order_ids)
    if not ids:
        return {}
    result = {oid: dict(resumen_productos="", id_entrega=None, id_repartidor=None,
                        repartidor=None, estado_entrega=None) for oid in ids}
    parts = {oid: [] for oid in ids}
    details = db.execute(select(DetallePedido.id_pedido, DetallePedido.cantidad, Producto.nombre)
        .join(Producto, Producto.id_producto == DetallePedido.id_producto)
        .join(Pedido, Pedido.id_pedido == DetallePedido.id_pedido)
        .where(DetallePedido.id_pedido.in_(ids), Producto.id_restaurante == Pedido.id_restaurante)
        .order_by(DetallePedido.id_pedido, DetallePedido.id_detalle))
    for oid, quantity, name in details:
        parts[oid].append(f"{quantity} × {name}")
    for oid in ids:
        result[oid]["resumen_productos"] = ", ".join(parts[oid])
    deliveries = db.execute(select(Entrega.id_pedido, Entrega.id_entrega, Entrega.id_repartidor,
                                   Usuario.nombre, Entrega.estado)
        .join(Pedido, Pedido.id_pedido == Entrega.id_pedido)
        .join(Repartidor, Repartidor.id_repartidor == Entrega.id_repartidor)
        .join(Usuario, Usuario.id_usuario == Repartidor.id_usuario)
        .where(Entrega.id_pedido.in_(ids), Usuario.id_restaurante == Pedido.id_restaurante))
    for oid, delivery, courier, name, state in deliveries:
        result[oid].update(id_entrega=delivery, id_repartidor=courier, repartidor=name, estado_entrega=state)
    return result
