"""Plan determinista sin conexión: noventa jornadas de una rotisería ficticia."""

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from fractions import Fraction
import json
import random

from app.db.models import Pedido
from app.logistics.priority import calculate
from app.logistics.service import delivery_cost
from types import SimpleNamespace

VERSION = "hist90-v1"
MARKER = "[OLIVA-HIST90:v1]"
DOMAIN = "hist90.oliva.invalid"
OWNER_EMAIL = f"lucia@{DOMAIN}"
LOCAL = timezone(timedelta(hours=-3))
FIXED = Decimal("900.00")
PER_KM = Decimal("280.00")
Q = Decimal("0.000001")

# Cantidades en kg/l/unidad; los costos de productos salen de estas recetas.
INGREDIENTS = [
    ("Carne vacuna", "kg", "9000", "100"), ("Pollo", "kg", "6500", "1"),
    ("Papas", "kg", "1300", "160"), ("Harina de trigo", "kg", "900", "120"),
    ("Cebolla", "kg", "1200", "80"), ("Aceite de girasol", "l", "3200", "0.5"),
    ("Espinaca", "kg", "2500", "50"), ("Huevos", "unidad", "250", "400"),
    ("Queso mozzarella", "kg", "6500", "60"), ("Tomate", "kg", "2000", "90"),
    ("Lechuga", "kg", "1800", "-0.2"), ("Zanahoria", "kg", "1300", "50"),
    ("Fideos secos", "kg", "2200", "90"), ("Berenjena", "kg", "2000", "20"),
    ("Pan rallado", "kg", "1300", "50"),
]
PRODUCTS = [
    ("Milanesa con puré", "10500", "Milanesa de carne con puré de papas.", [(0,".22"),(2,".28"),(7,".25"),(14,".06"),(5,".02")]),
    ("Pollo al horno con papas", "14000", "Porción de pollo al horno con papas doradas.", [(1,".4"),(2,".35"),(5,".025")]),
    ("Empanada de carne", "1800", "Empanada de carne vacuna y cebolla, por unidad.", [(0,".055"),(3,".04"),(4,".03"),(5,".006")]),
    ("Tarta de verduras", "8500", "Porción de tarta de espinaca y queso.", [(3,".12"),(6,".18"),(7,"1"),(8,".05")]),
    ("Ensalada de estación", "7000", "Tomate, lechuga y zanahoria con aceite.", [(9,".12"),(10,".1"),(11,".08"),(5,".01")]),
    ("Pasta con salsa", "9000", "Pasta con salsa de tomate y queso.", [(12,".2"),(9,".15"),(8,".03"),(5,".01")]),
    ("Tortilla de papas", "8000", "Nueva incorporación a la carta; aún sin ventas entregadas.", [(2,".25"),(7,"2"),(4,".06"),(5,".02")]),
    ("Berenjenas al horno", "8500", "Berenjenas con tomate y mozzarella, recién incorporadas.", [(13,".25"),(9,".1"),(8,".06"),(5,".01")]),
]
CLIENT_NAMES = ["Valentina López", "Joaquín Pérez", "Camila Suárez", "Nicolás Romero", "Florencia Díaz", "Tomás Herrera",
    "Agustina Fernández", "Mateo Torres", "Julieta Castro", "Santiago Molina", "Luciana Acosta", "Franco Medina",
    "Rocío Benítez", "Lautaro Gómez", "Mariana Ruiz", "Federico Silva", "Carolina Rojas", "Gabriel Navarro",
    "Paula Ortiz", "Emiliano Sosa", "Daniela Vega", "Ignacio Cabrera", "Sol Pereyra", "Bruno Álvarez"]
COURIER_NAMES = ["Ana Martínez", "Diego Ramírez", "Elena Vázquez", "Lucas Moreno"]


def at(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), LOCAL).astimezone(UTC)


def serial(value):
    if isinstance(value, (Decimal, datetime, date)):
        return value.isoformat() if not isinstance(value, Decimal) else str(value)
    raise TypeError(type(value).__name__)


def digest(value):
    return sha256(json.dumps(value, default=serial, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def schedule_day(orders, day, prior_success, prior_finished):
    """No asignar dos entregas simultáneas; diferir confirmaciones sin delivery disponible."""
    for attempt in range(200):
        successes, finished = prior_success.copy(), prior_finished.copy()
        free = [at(day, 10, 30)] * 4
        events = [dict(courier=i, estado="Disponible", fecha_hora=free[i]) for i in range(4)]
        scheduled = []
        for order in sorted(orders, key=lambda row: (row["ready"], row["local_id"])):
            if order["estado"] not in {"Entregado", "No entregado"}:
                continue
            assigned = max(order["ready"] + timedelta(minutes=2), min(free))
            candidates = [i for i in range(4) if free[i] <= assigned]
            courier = min(candidates, key=lambda i: (-Fraction(successes[i], finished[i] or 1), COURIER_NAMES[i]))
            departure = assigned + timedelta(minutes=1)
            end = departure + timedelta(minutes=order["travel"])
            if end.astimezone(LOCAL).date() != day:
                raise ValueError("La jornada simulada excede el cierre diario.")
            order.update(courier=courier, assigned=assigned, departure=departure, end=end)
            ephemeral = Pedido(fecha_hora=order["fecha_hora"], distancia_km=order["distancia_km"],
                               importe_total=order["importe_total"], costo_total=order["costo_total"])
            calculate(ephemeral, assigned)
            order["puntaje_prioridad"] = ephemeral.puntaje_prioridad
            order["factores_prioridad"] = ephemeral.factores_prioridad
            order["costo_repartidor"] = delivery_cost(SimpleNamespace(costo_fijo_entrega=FIXED, costo_por_km=PER_KM), ephemeral)
            events.extend([dict(courier=courier, estado="No disponible", fecha_hora=assigned), dict(courier=courier, estado="Disponible", fecha_hora=end)])
            free[courier] = end
            finished[courier] += 1
            successes[courier] += order["estado"] == "Entregado"
            scheduled.append(order)
        shifted = False
        for order in sorted(orders, key=lambda row: (row["fecha_hora"], row["local_id"])):
            busy = [row for row in scheduled if row["assigned"] <= order["fecha_hora"] < row["end"]]
            if len({row["courier"] for row in busy}) == 4:
                delay = min(row["end"] for row in busy) - order["fecha_hora"]
                for field in ("fecha_hora", "prep_start", "ready"):
                    order[field] += delay
                if "confirmacion_diferida_por_disponibilidad" not in order["tags"]:
                    order["tags"].append("confirmacion_diferida_por_disponibilidad")
                shifted = True
                break
        if not shifted:
            for courier in range(4):
                events.append(dict(courier=courier, estado="No disponible", fecha_hora=max(at(day, 23, 30), free[courier] + timedelta(minutes=1))))
            return events, successes, finished
    raise ValueError("No se pudo construir una jornada con disponibilidad válida.")


def build_plan(as_of: date, seed: int = 20261031, *, inventory=None, catalog=None,
               basket=None, marker=MARKER):
    # Parámetros opcionales para reutilizar el simulador sin cambiar el dataset previo.
    ingredients = INGREDIENTS if inventory is None else inventory
    recipes = PRODUCTS if catalog is None else catalog
    rng = random.Random(seed)
    start = as_of - timedelta(days=90)
    orders, movements, courier_events = [], [], []
    stocks = defaultdict(Decimal)
    counts = Counter()
    product_costs = [sum((Decimal(qty) * Decimal(ingredients[i][2]) for i, qty in product[3]), Decimal(0)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP) for product in recipes]
    products = [dict(nombre=p[0], precio=Decimal(p[1]), costo_unitario=product_costs[i], activo=True,
                     descripcion=p[2], imagen_url=None) for i, p in enumerate(recipes)]

    def movement(ingredient, quantity, timestamp, kind, reason, order=None, cycle=None):
        stocks[ingredient] += quantity
        movements.append(dict(ingredient=ingredient, cantidad=quantity.quantize(Q), fecha_hora=timestamp,
                              tipo=kind, motivo=f"{marker} {reason}", order=order, cycle=cycle))

    for ingredient in range(len(ingredients)):
        movement(ingredient, Decimal(100 if ingredient == 7 else 10), at(start, 10), "reposicion", "Existencias iniciales del historial.")
    successes, finished = [0] * 4, [0] * 4
    for day_index in range(90):
        day = start + timedelta(days=day_index)
        day_orders = []
        total = (36 if day.weekday() >= 5 else 22) + rng.randint(-3, 5)
        for number in range(total):
            lunch = number < round(total * .6)
            created = at(day, 11 if lunch else 19) + timedelta(minutes=rng.randint(10, 135) if lunch else rng.randint(0, 75), seconds=rng.randint(0, 59))
            progress = day_index / 89
            weights = [35 - 15 * progress, 22, 13 + 17 * progress, 10, 5 + 9 * progress, 12 - 5 * progress]
            items = Counter()
            for _ in range(1 if rng.random() < .72 else 2):
                product = rng.choices(range(6), weights=weights)[0]
                items[product] += rng.choice([3, 6, 12]) if product == 2 else rng.choices([1, 2, 3], [80, 18, 2])[0]
            tags = []
            if day_index >= 60 and day_index % 8 == 0 and number == 1:
                items = Counter({0: 5, 1: 4, 2: 24})
                tags.append("importe_alto: pedido familiar numeroso")
            if basket is not None:
                items = basket(rng, day, day_index, number, tags)
            prep_minutes = rng.randint(14, 27)
            if day_index >= 60 and day_index % 6 == 0 and number == 2:
                prep_minutes = rng.randint(75, 95)
                tags.append("preparacion_lenta")
            repeat = day_index % 11 == 0 and number == 6
            if repeat:
                tags.append("nueva_preparacion: cocción arruinada")
            prep_start = created + timedelta(minutes=rng.randint(2, 5))
            ready = prep_start + timedelta(minutes=prep_minutes + (8 if repeat else 0))
            distance = Decimal(rng.randint(10, 500)) / 100
            travel = max(7, round(6 + float(distance) * 3 + rng.randint(-2, 4)))
            if day_index >= 60 and day_index % 7 == 0 and number == 4:
                travel = rng.randint(65, 85)
                tags.append("entrega_lenta")
            state = "No entregado" if rng.random() < .035 else "Entregado"
            if state == "No entregado":
                tags.append("incidencia: cliente ausente")
            order = dict(local_id=len(orders), day=day_index, client=rng.randrange(len(CLIENT_NAMES)),
                fecha_hora=created, direccion_entrega=f"{rng.choice(['Belgrano', 'San Martín', 'Mitre', 'Rivadavia'])} {rng.randint(120, 1800)}",
                medio_pago=rng.choice(["efectivo", "transferencia"]), estado_pago="pagado" if state == "Entregado" else "pendiente",
                distancia_km=distance, estado=state, items=sorted(items.items()),
                importe_total=sum((products[i]["precio"] * qty for i, qty in items.items()), Decimal(0)),
                costo_total=sum((product_costs[i] * qty for i, qty in items.items()), Decimal(0)),
                prep_start=prep_start, ready=ready, repeat=repeat, travel=travel, tags=tags)
            orders.append(order); day_orders.append(order)
        # Fotografías del corte: casos pendientes para consultar HU-06, sin inventar cancelaciones.
        if day_index == 89:
            for product, state in ((6, "Nuevo"), (6, "En preparación"), (0, "Listo")):
                timestamp = at(day, 22, 10) + timedelta(minutes=len(day_orders) % 3)
                order = dict(local_id=len(orders), day=day_index, client=len(day_orders) % len(CLIENT_NAMES),
                    fecha_hora=timestamp, direccion_entrega="Sarmiento 680", medio_pago="efectivo", estado_pago="pendiente",
                    distancia_km=Decimal("1.25"), estado=state, items=[(product, 1)], importe_total=products[product]["precio"],
                    costo_total=product_costs[product], prep_start=timestamp + timedelta(minutes=2),
                    ready=timestamp + timedelta(minutes=22), repeat=False, travel=12,
                    tags=["corte_historico: pendiente para priorización"])
                orders.append(order); day_orders.append(order)
        demand = defaultdict(Decimal)
        for order in day_orders:
            amounts = defaultdict(Decimal)
            if order["estado"] != "Nuevo":
                for product, qty in order["items"]:
                    for ingredient, amount in recipes[product][3]:
                        amounts[ingredient] += Decimal(amount) * qty
                for ingredient, quantity in amounts.items():
                    demand[ingredient] += quantity * (2 if order["repeat"] else 1)
            order["consumption"] = dict(amounts)
        for ingredient, quantity in demand.items():
            desired = quantity + Decimal(10 if ingredient == 7 else 2)
            if stocks[ingredient] < desired:
                movement(ingredient, desired - stocks[ingredient], at(day, 10, 15), "reposicion", "Compra diaria para cocina.")
        day_events, successes, finished = schedule_day(day_orders, day, successes, finished)
        courier_events.extend(day_events)
        for order in sorted(day_orders, key=lambda row: (row["ready"], row["local_id"])):
            for cycle in range(2 if order["repeat"] else 1):
                for ingredient, quantity in order["consumption"].items():
                    movement(ingredient, -quantity, order["prep_start"] + timedelta(minutes=8 * cycle), "consumo",
                             "Consumo de receta.", order["local_id"], cycle)
    # Recuento final: reservas amplias, faltantes y una diferencia de inventario trazada.
    for ingredient, row in enumerate(ingredients):
        target = Decimal(row[3])
        delta = target - stocks[ingredient]
        if delta:
            movement(ingredient, delta, at(as_of - timedelta(days=1), 23, 45), "reposicion" if delta > 0 else "ajuste",
                     "Recuento final; reserva de compras." if delta > 0 else "Recuento final: merma y diferencia de inventario deliberada.")
    for row in orders:
        counts[row["estado"]] += 1
    plan = dict(version=VERSION, marker=marker, seed=seed, as_of=as_of, start=start, end=as_of - timedelta(days=1),
                products=products, orders=orders, movements=movements,
                courier_events=sorted(courier_events, key=lambda row: (row["fecha_hora"], row["courier"])),
                stock=dict(stocks), counts=dict(counts))
    plan["fingerprint"] = digest(plan)
    return plan
