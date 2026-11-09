"""Carga sintética aditiva del 1 al 9/11/2026 en el restaurante existente.

python -m app.demo_history.append_november plan --restaurant-id 1
python -m app.demo_history.append_november load --restaurant-id 1 --execute
python -m app.demo_history.append_november verify --restaurant-id 1

La carga usa solo pedidos, detalles, historiales, entregas y días operativos.
No crea cuentas ni productos, no cambia estados existentes y no toca el inventario.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import random
import re
import unicodedata
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.engine import build_engine
from app.db.models import (Cliente, DetallePedido, DiaOperativo, Entrega, HistorialPedido,
                           Insumo, MovimientoStock, Pedido, Producto, Repartidor,
                           Restaurante, Usuario)
from app.logistics.service import delivery_cost, lock_order_relations
from app.orders.operational_date import OPERATIONAL_ZONE, operational_day_bounds

RID_NAME = "rotiseria del pueblo"
START = date(2026, 11, 1)
END = date(2026, 11, 9)
SEED = 20261109
MARKER = "[OLIVA-NOV26:v1]"
LOCAL = ZoneInfo("America/Argentina/Buenos_Aires")
TARGET_TOTALS = {
    date(2026, 11, 1): 71, date(2026, 11, 2): 43, date(2026, 11, 3): 46,
    date(2026, 11, 4): 41, date(2026, 11, 5): 47, date(2026, 11, 6): 51,
    date(2026, 11, 7): 73, date(2026, 11, 8): 70, date(2026, 11, 9): 42,
}
FINAL_STATES = {"Entregado", "Cancelado", "No entregado"}
MARKER_RE = re.compile(r"^\[OLIVA-NOV26:v1\] batch=([0-9a-f]{64});seq=(\d+);total=(\d+);(.+)$")


def normalized(value: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                           if not unicodedata.combining(c)).split())


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), LOCAL)


def _restaurant(db, rid):
    row = db.get(Restaurante, rid)
    if row is None or normalized(row.nombre) != RID_NAME:
        raise ValueError("El ID no corresponde al restaurante existente esperado; no se modificó nada.")
    return row


def _entities(db, rid):
    products = db.scalars(select(Producto).where(Producto.id_restaurante == rid,
        Producto.activo.is_(True)).order_by(Producto.id_producto)).all()
    clients = db.scalars(select(Cliente).join(Usuario).where(
        Usuario.activo.is_(True), Usuario.rol == "cliente")).all()
    couriers = db.execute(select(Repartidor, Usuario).join(Usuario).where(
        Usuario.id_restaurante == rid, Usuario.rol == "repartidor", Usuario.activo.is_(True))
        .order_by(Repartidor.id_repartidor)).all()
    owner = db.scalar(select(Usuario).where(Usuario.id_restaurante == rid,
        Usuario.rol == "propietario", Usuario.activo.is_(True)).order_by(Usuario.id_usuario).limit(1))
    staff = db.scalar(select(Usuario).where(Usuario.id_restaurante == rid,
        Usuario.rol == "personal", Usuario.activo.is_(True)).order_by(Usuario.id_usuario).limit(1))
    if not products or not clients or len(couriers) < 2 or owner is None or staff is None:
        raise ValueError("Faltan productos, clientes, repartidores o actores activos existentes.")
    return products, clients, couriers, owner, staff


def _existing_counts(db, rid):
    lower, upper = operational_day_bounds(START)[0], operational_day_bounds(END + timedelta(days=1))[0]
    orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == rid,
        Pedido.fecha_hora >= lower, Pedido.fecha_hora < upper)).all()
    result = Counter()
    for order in orders:
        day = order.fecha_hora.astimezone(OPERATIONAL_ZONE).date()
        result[day] += 1
    return result


def _sales_weights(db, rid, products):
    lower = operational_day_bounds(date(2026, 10, 1))[0]
    upper = operational_day_bounds(START)[0]
    sold = dict(db.execute(select(DetallePedido.id_producto, func.sum(DetallePedido.cantidad))
        .join(Pedido, Pedido.id_pedido == DetallePedido.id_pedido)
        .where(Pedido.id_restaurante == rid, Pedido.estado == "Entregado",
               Pedido.fecha_hora >= lower, Pedido.fecha_hora < upper)
        .group_by(DetallePedido.id_producto)).all())
    return [max(1, int(sold.get(product.id_producto, 0))) for product in products]


def _basket(rng, products, weights, index, total):
    if index == total // 2:
        food = [p for p in products if not any(word in normalized(p.nombre)
            for word in ("coca", "fanta", "cerveza"))]
        food.sort(key=lambda p: (-p.precio, p.id_producto))
        drinks = [p for p in products if any(word in normalized(p.nombre)
            for word in ("coca", "fanta", "cerveza"))]
        empanadas = [p for p in products if "empanada" in normalized(p.nombre)]
        result = Counter()
        for product in food[:3]:
            result[product.id_producto] += 2 if product in food[:2] else 1
        if drinks:
            result[drinks[0].id_producto] += 4
        if empanadas:
            result[empanadas[0].id_producto] += 12
        return result, "ticket familiar de varios productos"

    count = 1 if rng.random() < .78 else 2
    selected = rng.choices(products, weights=weights, k=count)
    result = Counter()
    for product in selected:
        if "empanada" in normalized(product.nombre):
            quantity = rng.choices((3, 6, 12), weights=(.58, .32, .10))[0]
        elif any(word in normalized(product.nombre) for word in ("coca", "fanta", "cerveza")):
            quantity = rng.choices((1, 2, 3), weights=(.70, .25, .05))[0]
        else:
            quantity = rng.choices((1, 2, 3), weights=(.80, .18, .02))[0]
        result[product.id_producto] += quantity
    return result, ""


def _created_at(rng, day):
    weekend = day.weekday() >= 5
    slot = rng.choices(("lunch", "dinner", "afternoon"),
                       weights=(38, 55, 7) if weekend else (47, 53, 0))[0]
    if slot == "lunch":
        return at(day, 11, 5) + timedelta(minutes=rng.randint(0, 170), seconds=rng.randint(0, 59))
    if slot == "afternoon":
        return at(day, 16, 30) + timedelta(minutes=rng.randint(0, 100), seconds=rng.randint(0, 59))
    return at(day, 18, 35) + timedelta(minutes=rng.randint(0, 165), seconds=rng.randint(0, 59))


def build_plan(db, rid):
    restaurant = _restaurant(db, rid)
    products, clients, couriers, owner, staff = _entities(db, rid)
    existing = _existing_counts(db, rid)
    weights = _sales_weights(db, rid, products)
    rng = random.Random(SEED)
    rows = []
    addresses = ("Belgrano", "San Martín", "Mitre", "Rivadavia", "Sarmiento", "Las Heras")
    references = ("Timbre 2", "Puerta azul", "Casa al fondo", "Esquina", "Portón negro")
    zones = ("Centro", "Norte", "Sur", "Oeste")
    for day in sorted(TARGET_TOTALS):
        total = max(0, TARGET_TOTALS[day] - existing[day])
        daily = []
        for index in range(total):
            created = _created_at(rng, day)
            items, tag = _basket(rng, products, weights, index, total)
            rejected = index % 17 == 0 and index not in (total // 3, 2 * total // 3)
            state = "Cancelado" if rejected else rng.choices(
                ("Entregado", "No entregado"), weights=(.95, .05))[0]
            slow_prep = index == total // 3
            slow_travel = index == (2 * total // 3)
            if slow_prep or slow_travel:
                state = "Entregado"
            prep_start = created + timedelta(minutes=rng.randint(2, 5))
            prep_minutes = rng.randint(48, 62) if slow_prep else (
                rng.randint(6, 9) if index % 13 == 0 else rng.randint(11, 24))
            distance = Decimal(rng.randint(50, 850)) / 100
            amount = sum((p.precio * items[p.id_producto] for p in products if p.id_producto in items), Decimal(0))
            cost = sum((p.costo_unitario * items[p.id_producto] for p in products if p.id_producto in items), Decimal(0))
            daily.append(dict(day=day, index=index, created=created, prep_start=prep_start,
                ready=prep_start + timedelta(minutes=prep_minutes), prep_minutes=prep_minutes,
                slow_prep=slow_prep, slow_travel=slow_travel, state=state,
                client=clients[index % len(clients)], items=items, amount=amount, cost=cost,
                distance=distance, address=f"{rng.choice(addresses)} {rng.randint(120, 1850)}",
                reference=rng.choice(references) if rng.random() < .28 else None,
                zone=rng.choice(zones), payment=rng.choice(("efectivo", "transferencia")), tag=tag))
        daily.sort(key=lambda row: row["created"])

        # Una única entrega activa por repartidor; el recorrido usa duraciones
        # distintas para representar desempeños rápidos, medios y lentos.
        free = {courier.id_repartidor: at(day, 10, 30) for courier, _ in couriers}
        profiles = {courier.id_repartidor: index for index, (courier, _) in enumerate(couriers)}
        for row in sorted((r for r in daily if r["state"] != "Cancelado"), key=lambda r: r["ready"]):
            earliest = min(free.values())
            eligible = [cid for cid, when in free.items() if when == earliest]
            courier_id = rng.choice(eligible)
            assigned = max(row["ready"] + timedelta(minutes=2), free[courier_id])
            departure = assigned + timedelta(minutes=rng.randint(1, 4))
            profile = profiles[courier_id]
            if row["slow_travel"]:
                travel = rng.randint(32, 40)
            elif row["index"] % 13 == 0:
                travel = rng.randint(6, 9)
            else:
                travel = (rng.randint(9, 12) if profile == 1 else
                          rng.randint(12, 16) if profile == 0 else rng.randint(16, 20))
            finished = departure + timedelta(minutes=travel)
            if finished.astimezone(LOCAL).date() != day:
                raise ValueError(f"La planificación excede el día operativo {day}; no se cargó nada.")
            row.update(courier_id=courier_id, assigned=assigned, departure=departure, finished=finished,
                       travel_minutes=travel)
            free[courier_id] = finished
        for index, row in enumerate(daily):
            row["seq"] = len(rows)
            row["index"] = index
            row["detail_marker"] = tag_text = (
                f"{MARKER} batch=PLAN;seq={len(rows)};total=PLAN;"
                f"day={day.isoformat()};case={row['tag'] or 'habitual'}")
            rows.append(row)
    # Asegurar que el caso de venta alta supera el P95 vigente antes de insertar.
    high_ids = {r["seq"] for r in rows if r["tag"] == "ticket familiar de varios productos"}
    return dict(restaurant=restaurant, products=products, clients=clients, couriers=couriers,
                owner=owner, staff=staff, rows=rows, high_ids=high_ids,
                existing_counts=existing, weights=weights)


def _fingerprint(rows):
    def encode(value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if hasattr(value, "id_pedido"):
            return value.id_pedido
        if hasattr(value, "id_cliente"):
            return value.id_cliente
        raise TypeError(type(value).__name__)
    return sha256(json.dumps(rows, default=encode, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode()).hexdigest()


def _table_rows(db, model, where=None):
    table = model.__table__
    query = select(table)
    if where is not None:
        query = query.where(where)
    query = query.order_by(*table.primary_key.columns)
    return [dict(row) for row in db.execute(query).mappings()]


def _target_snapshot(db, rid):
    lower, upper = operational_day_bounds(START)[0], operational_day_bounds(END + timedelta(days=1))[0]
    order_ids = list(db.scalars(select(Pedido.id_pedido).where(Pedido.id_restaurante == rid,
        Pedido.fecha_hora >= lower, Pedido.fecha_hora < upper)))
    ids = set(order_ids)
    ingredient_ids = select(Insumo.id_insumo).where(Insumo.id_restaurante == rid)
    movement_totals = db.execute(select(func.count(MovimientoStock.id_movimiento),
        func.coalesce(func.sum(MovimientoStock.cantidad), 0), func.max(MovimientoStock.id_movimiento))
        .where(MovimientoStock.id_insumo.in_(ingredient_ids))).one()
    return dict(
        pedido=_table_rows(db, Pedido, Pedido.id_pedido.in_(ids)) if ids else [],
        detalle=_table_rows(db, DetallePedido, DetallePedido.id_pedido.in_(ids)) if ids else [],
        historial=_table_rows(db, HistorialPedido, HistorialPedido.id_pedido.in_(ids)) if ids else [],
        entrega=_table_rows(db, Entrega, Entrega.id_pedido.in_(ids)) if ids else [],
        inventario=_table_rows(db, Insumo, Insumo.id_restaurante == rid),
        movimientos=tuple(movement_totals),
        usuario=_table_rows(db, Usuario, Usuario.id_restaurante == rid),
        producto=_table_rows(db, Producto, Producto.id_restaurante == rid),
        repartidor=_table_rows(db, Repartidor, Repartidor.id_usuario.in_(
            select(Usuario.id_usuario).where(Usuario.id_restaurante == rid))),
    )


def _batch_info(db, rid):
    marker_rows = db.execute(select(HistorialPedido.id_pedido, HistorialPedido.detalle)
        .join(Pedido, Pedido.id_pedido == HistorialPedido.id_pedido)
        .where(Pedido.id_restaurante == rid, HistorialPedido.tipo_evento == "registro",
               HistorialPedido.detalle.like(f"{MARKER} batch=%"))).all()
    if not marker_rows:
        return None
    parsed = []
    for order_id, detail in marker_rows:
        match = MARKER_RE.match(detail or "")
        if not match:
            raise ValueError("Hay una marca de lote incompleta; se requiere revisión y no se escribió nada.")
        parsed.append((order_id, match.group(1), int(match.group(2)), int(match.group(3))))
    batch_ids, totals = {row[1] for row in parsed}, {row[3] for row in parsed}
    if len(batch_ids) != 1 or len(totals) != 1:
        raise ValueError("Hay más de un lote parcial; se requiere revisión manual.")
    total = next(iter(totals))
    if len(parsed) != total or {row[2] for row in parsed} != set(range(total)):
        raise ValueError("El lote existente está incompleto; no se agregaron duplicados.")
    return dict(ids=[row[0] for row in parsed], fingerprint=next(iter(batch_ids)), total=total)


def _existing_snapshot(db, rid):
    before = _target_snapshot(db, rid)
    ids = {row["id_pedido"] for row in before["pedido"]}
    return before, ids


def _verify_batch(db, rid, batch):
    orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == rid,
        Pedido.id_pedido.in_(batch["ids"]))).all()
    if len(orders) != batch["total"] or any(order.estado not in FINAL_STATES for order in orders):
        raise ValueError("El lote persistido tiene pedidos faltantes o no finales.")
    ids = {order.id_pedido for order in orders}
    details = db.execute(select(DetallePedido).where(DetallePedido.id_pedido.in_(ids))).all()
    totals = defaultdict(Decimal)
    for detail, in details:
        totals[detail.id_pedido] += detail.precio_unitario * detail.cantidad
    if len(details) == 0 or any(totals[order.id_pedido] != order.importe_total for order in orders):
        raise ValueError("El lote persistido tiene detalles o importes incoherentes.")
    deliveries = {row.id_pedido: row for row in db.scalars(select(Entrega).where(Entrega.id_pedido.in_(ids)))}
    for order in orders:
        if (order.estado == "Cancelado") == (order.id_pedido in deliveries):
            raise ValueError("Una entrega no corresponde al estado final del pedido.")
    movements = db.scalar(select(func.count()).select_from(MovimientoStock).where(
        MovimientoStock.id_pedido.in_(ids)))
    if movements:
        raise ValueError("El lote tiene movimientos de stock; no se autorizó.")
    return orders


def _make_event(order_id, actor, when, kind, state, detail):
    return HistorialPedido(id_pedido=order_id, id_usuario=actor, fecha_hora=when,
                           tipo_evento=kind, estado=state, detalle=detail)


def _insert(db, plan, batch_hash):
    ids = {}
    days_added = 0
    event_rows = []
    delivery_rows = []
    order_rows = []
    for row in plan["rows"]:
        restaurant = plan["restaurant"]
        order = Pedido(id_restaurante=restaurant.id_restaurante, id_cliente=row["client"].id_cliente,
            fecha_hora=row["created"].astimezone(UTC), estado=row["state"],
            direccion_entrega=row["address"], referencia_local=row["reference"], zona_entrega=row["zone"],
            medio_pago=row["payment"], estado_pago="pagado" if row["state"] == "Entregado" else "pendiente",
            importe_total=row["amount"], costo_total=row["cost"], distancia_km=row["distance"])
        order_rows.append((row, order))
    db.add_all(order for _, order in order_rows)
    db.flush()
    for row, order in order_rows:
        ids[row["seq"]] = order.id_pedido
        for product_id, quantity in row["items"].items():
            product = next(p for p in plan["products"] if p.id_producto == product_id)
            db.add(DetallePedido(id_pedido=order.id_pedido, id_producto=product_id,
                cantidad=quantity, precio_unitario=product.precio))
        row["detail_marker"] = (f"{MARKER} batch={batch_hash};seq={row['seq']};total={len(plan['rows'])};"
                                f"day={row['day'].isoformat()};case={row['tag'] or 'habitual'}")
        event_rows.append(_make_event(order.id_pedido, row["client"].usuario.id_usuario,
            row["created"].astimezone(UTC), "registro", "Nuevo", row["detail_marker"]))
        if row["state"] == "Cancelado":
            event_rows.append(_make_event(order.id_pedido, plan["staff"].id_usuario,
                (row["prep_start"] + timedelta(minutes=3)).astimezone(UTC),
                "estado", "Cancelado", f"{MARKER} Pedido rechazado por el restaurante."))
            continue
        event_rows.append(_make_event(order.id_pedido, plan["staff"].id_usuario,
            row["prep_start"].astimezone(UTC), "preparacion", "En preparación",
            f"{MARKER} Inicio de preparación histórica."))
        event_rows.append(_make_event(order.id_pedido, plan["staff"].id_usuario,
            row["ready"].astimezone(UTC), "estado", "Listo",
            f"{MARKER} Preparación terminada."))
        event_rows.append(_make_event(order.id_pedido, plan["owner"].id_usuario,
            row["assigned"].astimezone(UTC), "asignacion", "Asignado",
            f"{MARKER} Repartidor asignado."))
        courier_user = next(account for courier, account in plan["couriers"]
                            if courier.id_repartidor == row["courier_id"])
        event_rows.append(_make_event(order.id_pedido, courier_user.id_usuario,
            row["departure"].astimezone(UTC), "entrega", "En camino",
            f"{MARKER} Salida a reparto."))
        event_rows.append(_make_event(order.id_pedido, courier_user.id_usuario,
            row["finished"].astimezone(UTC), "entrega", row["state"],
            f"{MARKER} {row['tag'] or 'Entrega finalizada.'}"))
        delivery_rows.append(Entrega(id_pedido=order.id_pedido, id_repartidor=row["courier_id"],
            fecha_asignacion=row["assigned"].astimezone(UTC), estado=row["state"],
            costo_repartidor=delivery_cost(restaurant, order)))
    db.add_all(event_rows)
    db.add_all(delivery_rows)
    for day in sorted(TARGET_TOTALS):
        if db.get(DiaOperativo, (plan["restaurant"].id_restaurante, day)) is None:
            db.add(DiaOperativo(id_restaurante=plan["restaurant"].id_restaurante, fecha=day))
            days_added += 1
    db.flush()
    return ids, days_added


def _summary(db, rid, ids):
    rows = db.execute(select(Pedido.id_pedido, Pedido.fecha_hora, Pedido.estado)
        .where(Pedido.id_pedido.in_(ids))).all()
    counts = Counter((row.fecha_hora.astimezone(OPERATIONAL_ZONE).date(), row.estado) for row in rows)
    return {day.isoformat(): {state: counts[day, state] for state in sorted(FINAL_STATES) if counts[day, state]}
            for day in sorted(TARGET_TOTALS)}


def _report(db, rid, ids, existing_ids, before):
    after = _target_snapshot(db, rid)
    for name in ("pedido", "detalle", "historial", "entrega"):
        baseline = [row for row in before[name] if name == "pedido" and row["id_pedido"] in existing_ids] if name == "pedido" else before[name]
        if name != "pedido":
            baseline = [row for row in baseline if row["id_pedido"] in existing_ids]
        current = [row for row in after[name] if (row.get("id_pedido") if name != "pedido" else row["id_pedido"]) in existing_ids]
        if baseline != current:
            raise ValueError("Un pedido o relación preexistente cambió; se revirtió la transacción.")
    for name in ("inventario", "movimientos", "usuario", "producto", "repartidor"):
        if before[name] != after[name]:
            raise ValueError(f"Cambió información protegida en {name}; se revirtió la transacción.")
    orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == rid, Pedido.id_pedido.in_(ids))).all()
    if len(orders) != len(ids) or any(row.estado not in FINAL_STATES for row in orders):
        raise ValueError("Se encontró un pedido faltante o no final.")
    dates = list(db.scalars(select(DiaOperativo.fecha).where(
        DiaOperativo.id_restaurante == rid, DiaOperativo.fecha.between(START, END)).order_by(DiaOperativo.fecha)))
    if dates != sorted(TARGET_TOTALS):
        raise ValueError("No quedaron registrados todos los días operativos del período.")
    detail_counts = dict(db.execute(select(DetallePedido.id_pedido, func.count())
        .where(DetallePedido.id_pedido.in_(ids)).group_by(DetallePedido.id_pedido)).all())
    history_counts = dict(db.execute(select(HistorialPedido.id_pedido, func.count())
        .where(HistorialPedido.id_pedido.in_(ids)).group_by(HistorialPedido.id_pedido)).all())
    delivery_count = db.scalar(select(func.count()).select_from(Entrega).where(Entrega.id_pedido.in_(ids)))
    if any(detail_counts.get(oid, 0) < 1 for oid in ids) or any(history_counts.get(oid, 0) < 2 for oid in ids):
        raise ValueError("Hay pedidos sin detalles o historial suficiente.")
    return dict(inserted=len(orders), by_date=_summary(db, rid, ids),
        final_states=dict(Counter(row.estado for row in orders)), existing_orders_unchanged=True,
        inventory_unchanged=True, no_stock_movements=True,
        details=sum(detail_counts.values()), histories=sum(history_counts.values()),
        deliveries=delivery_count,
        operational_dates=[str(day) for day in dates])


def preflight(db, rid):
    if db.bind.dialect.name != "postgresql":
        raise ValueError("La carga requiere la base PostgreSQL configurada.")
    revision = db.scalar(text("SELECT version_num FROM public.alembic_version"))
    if revision != "0007_cambio_clave_pendiente":
        raise ValueError("La base no tiene la revisión actual esperada; no se modificó nada.")
    if not db.scalar(text("SELECT to_regclass('public.dia_operativo')")):
        raise ValueError("Falta la tabla DIA_OPERATIVO; no se modificó nada.")
    _restaurant(db, rid)
    return revision


def load(engine, rid):
    with Session(engine) as db, db.begin():
        preflight(db, rid)
        lock_order_relations(db)
        db.execute(text("SET LOCAL lock_timeout = '10s'"))
        restaurant = db.scalar(select(Restaurante).where(Restaurante.id_restaurante == rid).with_for_update())
        batch = _batch_info(db, rid)
        if batch:
            orders = _verify_batch(db, rid, batch)
            return dict(action="unchanged", inserted=0, verified_batch_orders=len(orders), fingerprint=batch["fingerprint"])
        before, existing_ids = _existing_snapshot(db, rid)
        plan = build_plan(db, rid)
        if not plan["rows"]:
            return dict(action="unchanged", inserted=0, reason="Los nueve días ya alcanzaron los volúmenes previstos.")
        # Marca el rechazo según el nombre real del sistema: Cancelado.
        batch_hash = _fingerprint([{k: v for k, v in row.items() if k != "detail_marker"}
                                   for row in plan["rows"]])
        ids, days_added = _insert(db, plan, batch_hash)
        db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        report = _report(db, rid, list(ids.values()), existing_ids, before)
        report.update(action="created", fingerprint=batch_hash,
                      generated_per_date=report["by_date"], customers_available=len(plan["clients"]),
                      unique_customers_used=len({row["client"].id_cliente for row in plan["rows"]}),
                      ids_repartidores=sorted({row["courier_id"] for row in plan["rows"] if "courier_id" in row}),
                      operating_days_added=days_added)
        return report


def plan_report(engine, rid):
    with Session(engine) as db, db.begin():
        db.execute(text("SET TRANSACTION READ ONLY"))
        revision = preflight(db, rid)
        batch = _batch_info(db, rid)
        if batch:
            return dict(mode="read only", action="already_loaded", count=batch["total"], fingerprint=batch["fingerprint"])
        plan = build_plan(db, rid)
        return dict(mode="read only", database=db.scalar(text("SELECT current_database()")),
            alembic_revision=revision, restaurant_id=rid, start=str(START), end=str(END),
            existing_orders=dict((day.isoformat(), count) for day, count in sorted(plan["existing_counts"].items())),
            planned_new_orders=len(plan["rows"]), planned_daily_totals={day.isoformat(): TARGET_TOTALS[day] for day in TARGET_TOTALS},
            planned_final_states=dict(Counter(row["state"] for row in plan["rows"])),
            active_products=len(plan["products"]), existing_customers=len(plan["clients"]),
            active_couriers=len(plan["couriers"]), stock_writes=0, existing_rows_modified=0)


def verify(engine, rid):
    with Session(engine) as db, db.begin():
        db.execute(text("SET TRANSACTION READ ONLY"))
        preflight(db, rid)
        batch = _batch_info(db, rid)
        if batch is None:
            raise ValueError("No existe el lote sintético de noviembre.")
        rows = _verify_batch(db, rid, batch)
        return dict(mode="read only", verified_orders=len(rows),
                    final_states=dict(Counter(row.estado for row in rows)),
                    orders_by_date=_summary(db, rid, [row.id_pedido for row in rows]),
                    marker_fingerprint=batch["fingerprint"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "load", "verify"))
    parser.add_argument("--restaurant-id", required=True, type=int)
    parser.add_argument("--execute", action="store_true", help="Confirma la inserción transaccional.")
    args = parser.parse_args()
    if args.action == "load" and not args.execute:
        parser.error("La carga requiere --execute.")
    engine = build_engine()
    try:
        result = plan_report(engine, args.restaurant_id) if args.action == "plan" else (
            load(engine, args.restaurant_id) if args.action == "load" else verify(engine, args.restaurant_id))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except ValueError as error:
        parser.exit(1, f"Carga cancelada: {error}\n")
    except SQLAlchemyError:
        parser.exit(1, "Error de PostgreSQL; la transacción no se confirmó.\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
