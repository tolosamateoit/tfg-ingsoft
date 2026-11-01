"""Verificación de datos persistidos de preparación, sin motores analíticos."""

from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import re

from sqlalchemy import select, text

from app.db.models import Pedido, Usuario
from app.demo_history.plan import CLIENT_NAMES, LOCAL, at
from app.demo_history.storage import reference, scope
from app.demo_history.validation import ensure
from app.orders.operational_date import operational_date


def verify(db, rid, plan):
    from app.demo_history.preparation import CATALOG, COURIER_NAMES, INVENTORY, MARKER, account_email
    own = scope(db, rid)
    products = {row["nombre"]: row for row in own["producto"]}
    ingredients = {row["nombre"]: row for row in own["insumo"]}
    pids = [products[p[0]]["id_producto"] for p in CATALOG]
    iids = [ingredients[p[0]]["id_insumo"] for p in INVENTORY]
    accounts = {row["correo"]: row for row in own["usuario"]}
    client_users = [accounts[account_email(rid, "cliente", i)]["id_usuario"] for i in range(len(CLIENT_NAMES))]
    courier_users = [accounts[account_email(rid, "repartidor", i)]["id_usuario"] for i in range(len(COURIER_NAMES))]
    clients = {row["id_usuario"]: row["id_cliente"] for row in own["cliente"]}
    couriers = {row["id_usuario"]: row["id_repartidor"] for row in own["repartidor"]}
    for user in client_users + courier_users:
        ensure(any(row["id_usuario"] == user and row["id_restaurante"] == rid for row in own["usuario"]), "Cuenta fuera del restaurante.")
    recipes = {(r["id_producto"], r["id_insumo"]): (r["cantidad"], r["unidad"]) for r in own["receta_detalle"]}
    for i, product in enumerate(CATALOG):
        expected = {(pids[i], iids[j]): (Decimal(qty), INVENTORY[j][1]) for j, qty in product[3]}
        ensure({k: v for k, v in recipes.items() if k[0] == pids[i]} == expected, "Receta o equivalencia envasada incorrecta.")
        cost = sum((Decimal(qty) * ingredients[INVENTORY[j][0]]["costo_unitario"] for j, qty in product[3]), Decimal(0)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        stored = products[product[0]]
        ensure(stored["precio"] == Decimal(product[1]) > cost > 0 and stored["costo_unitario"] == cost, "Precio/costo incoherente.")
    orders = [row for row in own["pedido"] if MARKER in (row["referencia_local"] or "")]
    ensure(len(orders) == len(plan["orders"]), "Cantidad de pedidos sintéticos distinta del plan.")
    refs = {row["referencia_local"]: row for row in orders}
    ensure(len(refs) == len(orders), "Referencias sintéticas duplicadas.")
    details, history, deliveries = defaultdict(list), defaultdict(list), {}
    for row in own["detalle_pedido"]:
        details[row["id_pedido"]].append(row)
    for row in own["historial_pedido"]:
        history[row["id_pedido"]].append(row)
    for row in own["entrega"]:
        deliveries[row["id_pedido"]] = row
    users = {r["id_usuario"]: r for r in own["usuario"]}
    expected_consumption, local_ids, days, states = {}, {}, Counter(), Counter()
    delivery_count = 0
    for i, planned in enumerate(plan["orders"]):
        row = refs.get(reference(plan, i))
        ensure(row is not None, "Semilla, tarifas, período o contenido distintos de la carga persistida.")
        oid = row["id_pedido"]; local_ids[oid] = i
        ensure(row["id_cliente"] == clients[client_users[planned["client"]]], "Cliente incorrecto.")
        for key in ("fecha_hora", "estado", "importe_total", "costo_total", "distancia_km", "direccion_entrega", "estado_pago", "medio_pago"):
            ensure(row[key] == planned[key], f"Pedido distinto del plan: {key}.")
        actual = [(d["id_producto"], d["cantidad"], d["precio_unitario"]) for d in details[oid]]
        expected = [(pids[j], qty, plan["products"][j]["precio"]) for j, qty in planned["items"]]
        ensure(Counter(actual) == Counter(expected), "Detalle distinto del plan.")
        ensure(sum(d[1] * d[2] for d in actual) == row["importe_total"], "Importe distinto de los detalles.")
        events = sorted(history[oid], key=lambda e: (e["fecha_hora"], e["id_historial"]))
        expected_events = [("Nuevo", planned["fecha_hora"], "registro")]
        if planned["estado"] != "Nuevo":
            expected_events.append(("En preparación", planned["prep_start"], "preparacion"))
            if planned["repeat"]:
                expected_events.append(("En preparación", planned["prep_start"] + timedelta(minutes=8), "nueva_preparacion"))
        if planned["estado"] not in ("Nuevo", "En preparación"):
            expected_events.append(("Listo", planned["ready"], "estado"))
        if "courier" in planned:
            expected_events.extend([("Asignado", planned["assigned"], "asignacion"),
                                    ("En camino", planned["departure"], "entrega"),
                                    (planned["estado"], planned["end"], "entrega")])
        ensure([(e["estado"], e["fecha_hora"], e["tipo_evento"]) for e in events] == expected_events, "Secuencia/tiempos inválidos.")
        ensure(all(a[1] <= b[1] for a, b in zip(expected_events, expected_events[1:])), "Eventos desordenados.")
        for event in events:
            ensure(MARKER in event["detalle"], "Evento sin marca sintética.")
            actor = users.get(event["id_usuario"])
            kind = event["tipo_evento"]
            role = "cliente" if kind == "registro" else "repartidor" if kind == "entrega" else "propietario" if kind == "asignacion" else "personal"
            ensure(actor is not None and actor["rol"] == role, "Actor inválido.")
            if role == "cliente":
                ensure(actor["id_usuario"] == client_users[planned["client"]], "Registro de otro cliente.")
            if role == "repartidor":
                ensure(actor["id_usuario"] == courier_users[planned["courier"]], "Entrega por otro repartidor.")
            ensure(plan["start"] <= event["fecha_hora"].astimezone(LOCAL).date() <= plan["end"], "Evento fuera del corte.")
            if kind in ("preparacion", "nueva_preparacion"):
                for j, qty in planned["consumption"].items():
                    expected_consumption[event["id_historial"], iids[j]] = (oid, -qty, event["fecha_hora"])
        delivery = deliveries.get(oid)
        ensure(bool(delivery) == ("courier" in planned), "Entrega incompatible con estado.")
        if delivery:
            delivery_count += 1
            ensure(delivery["id_repartidor"] == couriers[courier_users[planned["courier"]]] and delivery["estado"] == row["estado"], "Entrega/repartidor incoherentes.")
            ensure(delivery["fecha_asignacion"] == planned["assigned"] and delivery["costo_repartidor"] == planned["costo_repartidor"], "Tarifa/asignación incorrectas.")
        days[row["fecha_hora"].astimezone(LOCAL).date()] += 1
        states[row["estado"]] += 1
    ensure(len(days) == 90 and min(days) == plan["start"] and max(days) == plan["end"], "Período incompleto.")
    observed, ledger, movement_keys = {}, defaultdict(Decimal), Counter()
    for m in own["movimiento_stock"]:
        ledger[m["id_insumo"]] += m["cantidad"]
        if MARKER not in (m["motivo"] or ""):
            continue
        if "Saldo de apertura" in m["motivo"]:
            ensure(m["id_pedido"] is None and m["tipo"] == "ajuste", "Apertura inválida.")
            continue
        cycle = None
        if m["tipo"] == "consumo":
            match = re.match(r"Preparación #(\d+):", m["motivo"])
            ensure(match is not None, "Consumo sin ciclo.")
            key = (int(match[1]), m["id_insumo"])
            ensure(key not in observed, "Consumo duplicado.")
            observed[key] = (m["id_pedido"], m["cantidad"], m["fecha_hora"])
        movement_keys[iids.index(m["id_insumo"]), local_ids.get(m["id_pedido"]), m["fecha_hora"], m["tipo"], m["cantidad"]] += 1
    ensure(observed == expected_consumption, "Consumos distintos de recetas y ciclos.")
    expected_keys = Counter((m["ingredient"], m["order"], m["fecha_hora"], m["tipo"], m["cantidad"]) for m in plan["movements"])
    ensure(movement_keys == expected_keys, "Movimientos distintos del plan.")
    for name, unit, cost, _ in INVENTORY:
        row = ingredients[name]
        ensure(row["stock_actual"] == ledger[row["id_insumo"]] >= 0, "Saldo de inventario inconsistente.")
        ensure(row["unidad"] == unit and row["costo_unitario"] == Decimal(cost), "Unidad/costo incorrectos.")
    for user in courier_users:
        cid = couriers[user]
        actual = Counter((h["estado"], h["fecha_hora"]) for h in own["historial_repartidor"] if h["id_repartidor"] == cid)
        i = courier_users.index(user)
        expected = Counter((h["estado"], h["fecha_hora"]) for h in plan["courier_events"] if h["courier"] == i)
        if i < 2:
            expected["Disponible", at(plan["end"], 23, 50)] += 1
        ensure(actual == expected, "Disponibilidad histórica incorrecta.")
        intervals = sorted((p["assigned"], p["end"]) for p in plan["orders"] if p.get("courier") == i)
        ensure(all(a[1] <= b[0] for a, b in zip(intervals, intervals[1:])), "Entregas simultáneas.")
    # Detectar cruces reales incluso donde las FK aisladas serían válidas.
    checks = [
        "SELECT count(*) FROM receta_detalle d JOIN producto p USING(id_producto) JOIN insumo i USING(id_insumo) WHERE p.id_restaurante<>i.id_restaurante",
        "SELECT count(*) FROM detalle_pedido d JOIN pedido p USING(id_pedido) JOIN producto x USING(id_producto) WHERE p.id_restaurante<>x.id_restaurante",
        "SELECT count(*) FROM entrega e JOIN pedido p USING(id_pedido) JOIN repartidor r USING(id_repartidor) JOIN usuario u ON u.id_usuario=r.id_usuario WHERE p.id_restaurante IS DISTINCT FROM u.id_restaurante",
        "SELECT count(*) FROM movimiento_stock m JOIN pedido p USING(id_pedido) JOIN insumo i USING(id_insumo) WHERE p.id_restaurante<>i.id_restaurante",
        "SELECT count(*) FROM pedido p JOIN cliente c USING(id_cliente) JOIN usuario u USING(id_usuario) WHERE u.id_restaurante IS NOT NULL AND p.id_restaurante<>u.id_restaurante",
        "SELECT count(*) FROM historial_pedido h JOIN pedido p USING(id_pedido) JOIN cliente c USING(id_cliente) JOIN usuario u ON u.id_usuario=h.id_usuario WHERE u.id_restaurante IS DISTINCT FROM p.id_restaurante AND h.id_usuario<>c.id_usuario",
    ]
    ensure(all(db.scalar(text(sql)) == 0 for sql in checks), "Existen referencias entre restaurantes.")
    max_day = max(row["fecha_hora"].astimezone(LOCAL).date() for row in own["pedido"])
    ensure(operational_date(db, rid) == max_day, "Fecha operativa incorrecta.")
    cases = {tag: sum(tag in p["tags"] for p in plan["orders"]) for tag in
             ("preparacion_lenta", "entrega_lenta", "importe_alto: pedido familiar numeroso")}
    ensure(all(cases.values()), "Faltan anomalías válidas.")
    return dict(restaurant_id=rid, products=len(own["producto"]), ingredients=len(own["insumo"]),
                couriers=len(own["repartidor"]), orders=len(own["pedido"]), deliveries=len(own["entrega"]),
                generated_orders=len(orders), generated_deliveries=delivery_count, days=len(days),
                start=str(plan["start"]), end=str(plan["end"]), operational_date=str(max_day),
                states=dict(states), cases=cases, fingerprint=plan["fingerprint"], validation="passed")
