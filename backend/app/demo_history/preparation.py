"""Carga ADITIVA sobre un restaurante existente. Nunca crea restaurantes ni borra.

python -m app.demo_history.preparation plan|check|load|validate --restaurant-id 2
La escritura exige load --execute. El corte predeterminado es explícito e inclusivo.
"""

import argparse
from copy import deepcopy
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import secrets
import unicodedata
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.db.engine import build_engine
from app.db.models import (Cliente, DetallePedido, Entrega, HistorialPedido,
                           HistorialRepartidor, Insumo, MovimientoStock, Pedido,
                           Producto, RecetaDetalle, Repartidor, Restaurante, Usuario)
from app.demo_history.plan import CLIENT_NAMES, LOCAL, at, build_plan, digest
from app.demo_history.storage import (DEFAULT_OUTPUT, TABLES, backup_scope, bulk,
                                      insert_history, preflight, private_json, reference, scope, table_rows)
from app.orders.operational_date import operational_date
from app.orders.service import lock_order_relations

MARKER = "[OLIVA-PREP26:v1]"
COURIER_NAMES = ["Ana Martínez", "Elena Vázquez", "Lucas Moreno", "Bruno Castro"]
INVENTORY = [
    ("Carne", "kg", "12000", "25"), ("Huevo", "unidad", "250", "120"),
    ("Pan rallado", "kg", "2000", "15"), ("Papas", "kg", "1300", "50"),
    ("Aceite de girasol", "l", "3200", "12"), ("Pan para lomito", "unidad", "600", "80"),
    ("Tomate", "kg", "2000", "15"), ("Lechuga", "kg", "1800", "8"),
    ("Queso mozzarella", "kg", "6500", "20"), ("Harina de trigo", "kg", "900", "40"),
    ("Salsa de tomate", "kg", "1800", "12"), ("Levadura", "kg", "4500", "2"),
    ("Cebolla", "kg", "1200", "20"), ("Pollo", "kg", "6500", "25"),
    ("Pan de hamburguesa", "unidad", "400", "80"),
    ("Coca-Cola 1.5 L", "unidad", "2400", "120"),
    ("Fanta 1.5 L", "unidad", "2200", "100"),
    ("Cerveza lata 473 ml", "unidad", "1800", "100"),
    ("Sal", "kg", "1000", "5"),
]
# Para envasados, receta_detalle representa equivalencia de inventario 1:1,
# no una receta de elaboración. Se conserva el DER y el consumo existente.
CATALOG = [
    ("Milanesa", "20000", "Milanesa con papas, porción individual.", [(0,".22"),(1,".25"),(2,".06"),(3,".28"),(4,".02"),(18,".003")]),
    ("Lomito completo", "15000", "Lomito con queso, huevo, tomate y lechuga.", [(0,".18"),(5,"1"),(1,"1"),(6,".06"),(7,".025"),(8,".04"),(4,".01"),(18,".002")]),
    ("Empanada de carne", "1800", "Empanada de carne, por unidad.", [(0,".055"),(9,".04"),(12,".03"),(4,".006"),(18,".001")]),
    ("Pizza mozzarella", "12000", "Pizza de ocho porciones.", [(9,".35"),(8,".25"),(10,".15"),(11,".008"),(4,".015"),(18,".006")]),
    ("Hamburguesa completa", "10000", "Hamburguesa con queso y vegetales.", [(0,".15"),(14,"1"),(8,".035"),(6,".04"),(7,".02"),(18,".002")]),
    ("Pollo con papas", "14000", "Pollo al horno con papas.", [(13,".4"),(3,".35"),(4,".025"),(18,".004")]),
    ("Coca-Cola 1.5 L", "4500", "Bebida envasada: una botella por unidad vendida.", [(15,"1")]),
    ("Fanta 1.5 L", "4200", "Bebida envasada: una botella por unidad vendida.", [(16,"1")]),
    ("Cerveza lata 473 ml", "3500", "Bebida envasada: una lata por unidad vendida.", [(17,"1")]),
    ("Empanada de pollo", "1800", "Empanada de pollo, por unidad.", [(13,".06"),(9,".04"),(12,".025"),(4,".006"),(18,".001")]),
]


def basket(rng, day, index, number, tags):
    weights = [18, 30 if day.weekday() in (4, 5) else 20, 22 if day.weekday() == 1 else 14,
               30 if day.weekday() in (5, 6) else 15, 18, 12, 4, 4, 5, 10 + index / 15]
    items = Counter()
    for _ in range(1 if rng.random() < .68 else 2):
        product = rng.choices(range(len(CATALOG)), weights)[0]
        items[product] += rng.choice([3, 6, 12]) if product in (2, 9) else rng.choices([1, 2, 3], [75, 22, 3])[0]
    if "importe_alto: pedido familiar numeroso" in tags:
        items = Counter({1: 8, 3: 5, 2: 36, 6: 5, 7: 4})
    else:
        if 1 in items and rng.random() < .8:
            items[6] += max(1, (items[1] + 1) // 2)
        if 3 in items and rng.random() < .8:
            items[7] += items[3]
    return items


def plan_for(cutoff=date(2026, 10, 31), seed=20261031):
    if cutoff > date(2026, 10, 31) or cutoff.year < 2000:
        raise ValueError("El corte debe estar entre 2000 y el 31/10/2026.")
    plan = build_plan(cutoff + timedelta(days=1), seed, inventory=INVENTORY,
                      catalog=CATALOG, basket=basket, marker=MARKER)
    plan["courier_names"] = COURIER_NAMES
    plan["fingerprint"] = digest({k: v for k, v in plan.items() if k != "fingerprint"})
    return plan


def normalized(name):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", name.casefold())
                            if not unicodedata.combining(c)).split())


def target(db, rid):
    restaurant = db.get(Restaurante, rid)
    if restaurant is None or normalized(restaurant.nombre) != "rotiseria del pueblo":
        raise ValueError("El ID no corresponde a Rotisería del Pueblo.")
    if "OLIVA-HIST90" in restaurant.horario_atencion:
        raise ValueError("Ese ID es el dataset independiente anterior; usá el restaurante original.")
    return restaurant


def unique_by_name(rows):
    result = {}
    for row in rows:
        key = normalized(row.nombre)
        if key in result:
            raise ValueError("Hay nombres duplicados; se requiere revisión sin fusionar registros.")
        result[key] = row
    return result


def account_email(rid, kind, i):
    return f"{kind}{i + 1:02}.r{rid}@prep26.oliva.invalid"


def setup(db, rid, plan, output):
    inventory = unique_by_name(db.scalars(select(Insumo).where(Insumo.id_restaurante == rid)))
    products = unique_by_name(db.scalars(select(Producto).where(Producto.id_restaurante == rid)))
    ingredients, product_ids, balances = [], [], []
    for name, unit, cost, _ in INVENTORY:
        row = inventory.get(normalized(name))
        if row is None:
            row = Insumo(id_restaurante=rid, nombre=name, unidad=unit, costo_unitario=Decimal(cost), stock_actual=0)
            db.add(row); db.flush()
        if row.unidad != unit or row.costo_unitario != Decimal(cost):
            raise ValueError("Unidad/costo de insumo existente difiere del catálogo; revisar antes de cargar.")
        ingredients.append(row.id_insumo)
        balances.append(row.stock_actual)
        ledger = db.scalar(select(func.coalesce(func.sum(MovimientoStock.cantidad), 0)).where(MovimientoStock.id_insumo == row.id_insumo))
        if row.stock_actual != ledger:
            db.add(MovimientoStock(id_insumo=row.id_insumo, cantidad=row.stock_actual - ledger,
                fecha_hora=at(plan["start"], 9), tipo="ajuste",
                motivo=f"{MARKER} Saldo de apertura preexistente sin movimientos: conciliación de stock guardado, no compra histórica."))
    for i, values in enumerate(plan["products"]):
        row = products.get(normalized(values["nombre"]))
        if row is None:
            row = Producto(id_restaurante=rid, **values)
            db.add(row); db.flush()
        else:
            # No afecta los snapshots de precio/costo de pedidos anteriores.
            for key, value in values.items():
                if key != "imagen_url":
                    setattr(row, key, value)
        product_ids.append(row.id_producto)
        expected = {ingredients[j]: Decimal(qty) for j, qty in CATALOG[i][3]}
        old = list(db.scalars(select(RecetaDetalle).where(RecetaDetalle.id_producto == row.id_producto)))
        if any(recipe.id_insumo not in expected for recipe in old):
            raise ValueError("Receta existente contiene insumos adicionales; no se eliminaron.")
        for j, qty in CATALOG[i][3]:
            recipe = db.get(RecetaDetalle, (row.id_producto, ingredients[j]))
            if recipe is None:
                recipe = RecetaDetalle(id_producto=row.id_producto, id_insumo=ingredients[j])
                db.add(recipe)
            recipe.cantidad, recipe.unidad = Decimal(qty), INVENTORY[j][1]
    credentials, clients, client_users, couriers, courier_users = [], [], [], [], []
    for kind, names, role in (("cliente", CLIENT_NAMES, "cliente"), ("repartidor", COURIER_NAMES, "repartidor")):
        for i, name in enumerate(names):
            email = account_email(rid, kind, i)
            if kind == "repartidor" and db.scalar(select(Usuario.id_usuario).where(
                    Usuario.id_restaurante == rid, Usuario.rol == role, Usuario.nombre == name)):
                raise ValueError("Ya existe un repartidor de ese nombre; revisar su identidad antes de cargar.")
            if db.scalar(select(Usuario.id_usuario).where(Usuario.correo == email)):
                raise ValueError("Cuenta reservada preexistente sin carga completa; no se sobrescribió.")
            password = secrets.token_urlsafe(15)
            user = Usuario(id_restaurante=rid, correo=email, nombre=name, rol=role,
                           activo=True, hash_contrasena=hash_password(password))
            db.add(user); db.flush()
            credentials.append(dict(correo=email, rol=role, contrasena=password))
            if kind == "cliente":
                child = Cliente(id_usuario=user.id_usuario, nombre=name, direccion="Belgrano 450")
                db.add(child); db.flush()
                clients.append(child.id_cliente); client_users.append(user.id_usuario)
            else:
                child = Repartidor(id_usuario=user.id_usuario, zona="Centro", estado_disponibilidad="No disponible")
                db.add(child); db.flush()
                couriers.append(child.id_repartidor); courier_users.append(user.id_usuario)
    actors = {}
    for role in ("propietario", "personal"):
        actor = db.scalar(select(Usuario.id_usuario).where(Usuario.id_restaurante == rid, Usuario.rol == role,
                                                         Usuario.activo.is_(True)).order_by(Usuario.id_usuario).limit(1))
        if actor is None:
            raise ValueError("Falta un propietario/personal activo en el restaurante existente.")
        actors["owner" if role == "propietario" else "staff"] = actor
    path = private_json(Path(output) / f"preparation-credentials-{rid}-{uuid4().hex}.json",
                        {"restaurant_id": rid, "accounts": credentials})
    return dict(products=product_ids, ingredients=ingredients, clients=clients, client_users=client_users,
                couriers=couriers, courier_users=courier_users, **actors), balances, str(path)


def snapshot(db):
    return {name: table_rows(db, table) for name, table in TABLES.items()}


def preserve(before, after, ids):
    allowed = {"producto": set(ids["products"]), "insumo": set(ids["ingredients"])}
    for name, rows in before.items():
        keys = [col.name for col in TABLES[name].primary_key.columns]
        current = {tuple(r[k] for k in keys): r for r in after[name]}
        for row in rows:
            key = tuple(row[k] for k in keys)
            other = current.get(key)
            if other is None:
                raise ValueError("Desapareció un registro preexistente; carga revertida.")
            excluded = set()
            if name in allowed and key[0] in allowed[name]:
                excluded = {"stock_actual"} if name == "insumo" else {"precio", "costo_unitario", "descripcion", "activo"}
            if name == "receta_detalle" and key[0] in ids["products"]:
                excluded = {"cantidad", "unidad"}
            if any(row[k] != other[k] for k in row if k not in excluded):
                raise ValueError(f"Cambió un registro preexistente protegido en {name}; carga revertida.")


def validate(db, rid, plan):
    from app.demo_history.preparation_validation import verify
    return verify(db, rid, bind_tariffs(target(db, rid), plan))


def bind_tariffs(restaurant, plan):
    from app.logistics.service import delivery_cost
    from types import SimpleNamespace
    plan = deepcopy(plan)
    for row in plan["orders"]:
        if "courier" in row:
            row["costo_repartidor"] = delivery_cost(restaurant, SimpleNamespace(distancia_km=row["distancia_km"]))
    plan["fingerprint"] = digest({k: v for k, v in plan.items() if k != "fingerprint"})
    return plan


def load(engine, rid, plan, output=DEFAULT_OUTPUT):
    with Session(engine) as db, db.begin():
        preflight(db)
        lock_order_relations(db)
        restaurant = target(db, rid)
        db.execute(text("SET LOCAL lock_timeout = '10s'"))
        db.refresh(restaurant, with_for_update=True)
        plan = bind_tariffs(restaurant, plan)
        existing = db.scalar(select(Pedido.id_pedido).where(Pedido.referencia_local.startswith(MARKER)).limit(1))
        if existing is not None:
            return {**validate(db, rid, plan), "action": "unchanged"}
        before = snapshot(db)
        backup = str(backup_scope(db, rid, output))
        ids, balances, credentials = setup(db, rid, plan, output)
        insert_history(db, rid, plan, ids)
        for i, iid in enumerate(ids["ingredients"]):
            db.get(Insumo, iid).stock_actual += balances[i]
        # Dos disponibles al cierre; se conserva intacto el repartidor anterior.
        for i in (0, 1):
            db.get(Repartidor, ids["couriers"][i]).estado_disponibilidad = "Disponible"
            db.add(HistorialRepartidor(id_repartidor=ids["couriers"][i], estado="Disponible",
                                      fecha_hora=at(plan["end"], 23, 50)))
        db.flush()
        db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        result = validate(db, rid, plan)
        preserve(before, snapshot(db), ids)
        result.update(action="created", existing_records_preserved=True, backup=backup, credentials=credentials)
        private_json(Path(output) / f"preparation-manifest-{rid}-{uuid4().hex}.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "check", "load", "validate"))
    parser.add_argument("--restaurant-id", required=True, type=int)
    parser.add_argument("--cutoff", type=date.fromisoformat, default=date(2026, 10, 31))
    parser.add_argument("--seed", type=int, default=20261031)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    engine = None
    try:
        plan = plan_for(args.cutoff, args.seed)
        if args.action == "plan" or args.action == "load" and not args.execute:
            result = dict(mode="offline", restaurant_id=args.restaurant_id, orders=len(plan["orders"]),
                          products=len(CATALOG), ingredients=len(INVENTORY), start=str(plan["start"]), end=str(plan["end"]), fingerprint=plan["fingerprint"])
        else:
            engine = build_engine()
            if args.action == "load":
                result = load(engine, args.restaurant_id, plan)
            else:
                with Session(engine) as db:
                    db.execute(text("SET TRANSACTION READ ONLY"))
                    preflight(db); target(db, args.restaurant_id)
                    result = validate(db, args.restaurant_id, plan) if args.action == "validate" else dict(restaurant_id=args.restaurant_id, mode="read only", target_verified=True)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, SQLAlchemyError, OSError) as error:
        print(str(error) if isinstance(error, ValueError) else "Error de conexión o almacenamiento; no se muestran datos privados. La carga no se confirmó.")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
