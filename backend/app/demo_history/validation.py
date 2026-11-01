"""Validación del historial importado, sin entrenar ni cambiar motores analíticos."""

from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal
import re

from app.auth.service import as_utc
from app.demo_history.plan import INGREDIENTS, LOCAL, MARKER, PRODUCTS, VERSION


def ensure(condition, message):
    if not condition:
        raise ValueError(message)


def validate_dataset(db, rid, plan):
    from app.demo_history.storage import bindings, scope, reference
    own = scope(db, rid)
    ids = bindings(db, rid, plan)
    orders = own["pedido"]
    ensure(len(orders) == len(plan["orders"]), "La cantidad de pedidos no coincide con el plan.")
    order_index = {row["id_pedido"]: i for i, row in enumerate(orders)}
    ingredient_index = {id: i for i, id in enumerate(ids["ingredients"])}
    details, histories, deliveries = defaultdict(list), defaultdict(list), {}
    for row in own["detalle_pedido"]:
        details[row["id_pedido"]].append(row)
    for row in own["historial_pedido"]:
        histories[row["id_pedido"]].append(row)
    for row in own["entrega"]:
        ensure(row["id_pedido"] not in deliveries, "Hay una entrega duplicada.")
        deliveries[row["id_pedido"]] = row
    cycles, observations = {}, defaultdict(Decimal)
    days, states, daily, product_sales = set(), Counter(), Counter(), defaultdict(Counter)
    actor_roles = {row["id_usuario"]: row["rol"] for row in own["usuario"]}
    for index, (row, planned) in enumerate(zip(orders, plan["orders"])):
        oid = row["id_pedido"]
        ensure(row["id_restaurante"] == rid and row["id_cliente"] == ids["clients"][planned["client"]], "Pedido asociado al restaurante/cliente incorrecto.")
        ensure(row["referencia_local"] == reference(plan, index), "Marca de origen distinta de la semilla/período esperado.")
        for name in ("estado", "importe_total", "costo_total", "distancia_km", "direccion_entrega", "medio_pago", "estado_pago"):
            ensure(row[name] == planned[name], f"El pedido {oid} difiere del plan en {name}.")
        ensure(as_utc(row["fecha_hora"]) == planned["fecha_hora"], "Fecha del pedido diferente al plan.")
        distance = row["distancia_km"]
        ensure(Decimal(".10") <= distance <= 5 and distance == distance.quantize(Decimal(".01")), "Distancia fuera del rango o precisión aprobada.")
        day = as_utc(row["fecha_hora"]).astimezone(LOCAL).date()
        ensure(plan["start"] <= day <= plan["end"], "Pedido fuera del período histórico.")
        days.add(day); daily[day] += 1; states[row["estado"]] += 1
        expected_items = {(ids["products"][i], qty, plan["products"][i]["precio"]) for i, qty in planned["items"]}
        ensure({(d["id_producto"], d["cantidad"], d["precio_unitario"]) for d in details[oid]} == expected_items, "Detalle del pedido incoherente con la receta/catálogo.")
        ensure(sum((d["cantidad"] * d["precio_unitario"] for d in details[oid]), Decimal(0)) == row["importe_total"], "Importe inconsistente con el detalle.")
        history = sorted(histories[oid], key=lambda event: (event["fecha_hora"], event["id_historial"]))
        expected_states = ["Nuevo"]
        expected_times = [planned["fecha_hora"]]
        expected_types = ["registro"]
        expected_actors = [ids["client_users"][planned["client"]]]
        if row["estado"] != "Nuevo":
            expected_states += ["En preparación"] * (2 if planned["repeat"] else 1)
            expected_times += [planned["prep_start"]]
            expected_types += ["preparacion"]
            expected_actors += [ids["staff"]]
            if planned["repeat"]:
                expected_times += [planned["prep_start"] + timedelta(minutes=8)]
                expected_types += ["nueva_preparacion"]
                expected_actors += [ids["staff"]]
        if row["estado"] not in {"Nuevo", "En preparación"}:
            expected_states += ["Listo"]
            expected_times += [planned["ready"]]
            expected_types += ["estado"]
            expected_actors += [ids["staff"]]
        if "courier" in planned:
            expected_states += ["Asignado", "En camino", row["estado"]]
            expected_times += [planned["assigned"], planned["departure"], planned["end"]]
            expected_types += ["asignacion", "entrega", "entrega"]
            expected_actors += [ids["owner"], ids["courier_users"][planned["courier"]], ids["courier_users"][planned["courier"]]]
        ensure([e["estado"] for e in history] == expected_states, "Secuencia de estados inválida.")
        ensure([as_utc(e["fecha_hora"]) for e in history] == expected_times, "Tiempos de preparación/entrega diferentes al plan.")
        ensure([e["tipo_evento"] for e in history] == expected_types, "Tipo de evento incompatible con la transición.")
        ensure([e["id_usuario"] for e in history] == expected_actors, "Actor del historial diferente del responsable asignado.")
        ensure(as_utc(history[0]["fecha_hora"]) == as_utc(row["fecha_hora"]), "Registro temporal inconsistente.")
        for event in history:
            ensure(MARKER in event["detalle"], "Evento sin identificación sintética.")
            expected_role = "cliente" if event["tipo_evento"] == "registro" else "repartidor" if event["tipo_evento"] == "entrega" else "propietario" if event["tipo_evento"] == "asignacion" else "personal"
            ensure(actor_roles.get(event["id_usuario"]) == expected_role, "Actor incompatible con el evento.")
            local_date = as_utc(event["fecha_hora"]).astimezone(LOCAL).date()
            ensure(plan["start"] <= local_date <= plan["end"], "Evento fuera del período histórico.")
            if event["tipo_evento"] in {"preparacion", "nueva_preparacion"}:
                cycles[event["id_historial"]] = (index, sum(1 for previous in history if previous["id_historial"] < event["id_historial"] and previous["tipo_evento"] in {"preparacion", "nueva_preparacion"}))
                for ingredient, qty in planned["consumption"].items():
                    observations[event["id_historial"], ingredient] = -qty
        delivery = deliveries.get(oid)
        ensure(bool(delivery) == ("courier" in planned), "Entrega faltante o no permitida por el estado.")
        if delivery:
            ensure(delivery["id_repartidor"] == ids["couriers"][planned["courier"]] and delivery["estado"] == row["estado"], "Repartidor o estado de entrega incorrecto.")
            ensure(delivery["costo_repartidor"] == planned["costo_repartidor"], "Costo de entrega distinto de las tarifas.")
            ensure(as_utc(delivery["fecha_asignacion"]) == planned["assigned"], "Fecha de asignación incoherente.")
            ensure(row["puntaje_prioridad"] == planned["puntaje_prioridad"] and row["factores_prioridad"] == planned["factores_prioridad"], "Factores de prioridad diferentes del cálculo real.")
        if row["estado"] == "Entregado":
            for product, qty in planned["items"]:
                product_sales[product][day] += qty
    ensure(len(days) == 90 and min(days) == plan["start"] and max(days) == plan["end"], "No se cubrieron las noventa jornadas.")
    movement_keys, quantities, running, observed_cycles = Counter(), defaultdict(Decimal), defaultdict(Decimal), {}
    for row in sorted(own["movimiento_stock"], key=lambda entry: (entry["fecha_hora"], entry["id_movimiento"])):
        ingredient = ingredient_index[row["id_insumo"]]
        local_order = order_index[row["id_pedido"]] if row["id_pedido"] is not None else None
        ensure(MARKER in row["motivo"], "Movimiento sin identificación sintética.")
        ensure(row["cantidad"] != 0, "Movimiento de cantidad cero.")
        ensure(row["tipo"] != "reposicion" or row["cantidad"] > 0, "Reposición no positiva.")
        cycle = None
        if row["tipo"] == "consumo":
            match = re.match(r"Preparación #(\d+):", row["motivo"])
            ensure(match is not None and row["cantidad"] < 0, "Consumo sin ciclo trazable o no negativo.")
            event = int(match[1]); ensure(event in cycles, "Consumo de un evento inexistente.")
            cycle_order, cycle = cycles[event]
            ensure(cycle_order == local_order, "Consumo asociado a otro pedido.")
            ensure((event, ingredient) not in observed_cycles, "Consumo duplicado por preparación/insumo.")
            observed_cycles[event, ingredient] = row["cantidad"]
        else:
            ensure(row["id_pedido"] is None and row["tipo"] in {"reposicion", "ajuste"}, "Movimiento no permitido.")
        movement_keys[ingredient, local_order, as_utc(row["fecha_hora"]), row["tipo"], row["cantidad"], cycle] += 1
        quantities[ingredient] += row["cantidad"]
        running[ingredient] += row["cantidad"]
        if running[ingredient] < 0:
            ensure(row["tipo"] == "ajuste" and ingredient == 10, "Stock negativo fuera del caso de recuento deliberado.")
    expected_movements = Counter((row["ingredient"], row["order"], row["fecha_hora"], row["tipo"], row["cantidad"], row["cycle"]) for row in plan["movements"])
    ensure(movement_keys == expected_movements, "Los movimientos no coinciden con el plan reproducible.")
    ensure(observed_cycles == dict(observations), "Los consumos difieren de las recetas o falta un ciclo.")
    for row in own["insumo"]:
        index = ingredient_index[row["id_insumo"]]
        ensure(row["stock_actual"] == quantities[index] == plan["stock"][index], "El stock no coincide con la suma de movimientos.")
        ensure(row["unidad"] == INGREDIENTS[index][1] and row["costo_unitario"] == Decimal(INGREDIENTS[index][2]), "Unidad o costo de insumo distinto del plan.")
    # Disponibilidad durante cada confirmación y ausencia de entregas simultáneas por repartidor.
    intervals = defaultdict(list)
    for row in plan["orders"]:
        if "courier" in row:
            intervals[row["courier"]].append((row["assigned"], row["end"]))
    for rows in intervals.values():
        rows.sort()
        ensure(all(a[1] <= b[0] for a, b in zip(rows, rows[1:])), "Hay entregas simultáneas del mismo repartidor.")
    per_day = defaultdict(list)
    for row in plan["orders"]:
        per_day[row["day"]].append(row)
    for rows in per_day.values():
        for row in rows:
            busy = {other["courier"] for other in rows if "courier" in other and other["assigned"] <= row["fecha_hora"] < other["end"]}
            ensure(len(busy) < 4, "Se confirmó un pedido sin repartidores disponibles.")
    courier_indexes = {id: i for i, id in enumerate(ids["couriers"])}
    actual_events = Counter((courier_indexes[row["id_repartidor"]], row["estado"], as_utc(row["fecha_hora"])) for row in own["historial_repartidor"])
    expected_events = Counter((row["courier"], row["estado"], row["fecha_hora"]) for row in plan["courier_events"])
    ensure(actual_events == expected_events, "Disponibilidades históricas distintas del plan.")
    ensure(all(row["estado_disponibilidad"] == "No disponible" for row in own["repartidor"]), "La disponibilidad actual no coincide con el cierre del historial.")
    weekend = [value for day, value in daily.items() if day.weekday() >= 5]
    weekday = [value for day, value in daily.items() if day.weekday() < 5]
    ensure(sum(weekend) / len(weekend) > sum(weekday) / len(weekday), "No aparece el aumento de fines de semana.")
    trends = {}
    for product in (0, 2, 4, 5):
        first = sum(qty for day, qty in product_sales[product].items() if day < plan["start"] + timedelta(days=30))
        last = sum(qty for day, qty in product_sales[product].items() if day >= plan["end"] - timedelta(days=29))
        trends[PRODUCTS[product][0]] = {"unidades_primeros_30_dias": first, "unidades_ultimos_30_dias": last}
    ensure(not product_sales[6] and not product_sales[7], "Los productos nuevos no deben tener ventas entregadas.")
    return dict(dataset=VERSION, restaurant_id=rid, seed=plan["seed"], as_of=plan["as_of"].isoformat(),
        start=plan["start"].isoformat(), end=plan["end"].isoformat(), fingerprint=plan["fingerprint"], days=len(days),
        orders=len(orders), products=len(own["producto"]), ingredients=len(own["insumo"]), movements=len(own["movimiento_stock"]),
        deliveries=len(own["entrega"]), customers=len(own["cliente"]), couriers=len(own["repartidor"]), states=dict(states),
        predictions=len(own["prediccion_demanda"]), alerts=len(own["alerta"]),
        average_orders_weekend=round(sum(weekend) / len(weekend), 2), average_orders_weekday=round(sum(weekday) / len(weekday), 2),
        trends=trends, cases={tag: sum(tag in row["tags"] for row in plan["orders"]) for tag in
            ("preparacion_lenta", "entrega_lenta", "nueva_preparacion: cocción arruinada", "importe_alto: pedido familiar numeroso")},
        validation="Integridad, aislamiento de referencias, importes, estados, tiempos, reparto y stock verificados.")
