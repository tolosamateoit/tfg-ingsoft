"""Carga transaccional y reinicio limitado a una identidad reservada del dataset."""

from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import secrets
from uuid import uuid4

from sqlalchemy import delete, inspect, insert, select, text
from sqlalchemy.orm import Session

from app.auth.models import AuthBase
from app.auth.security import digest as email_digest, hash_password
from app.db.base import Base
from app.db.models import (Alerta, Cliente, DetallePedido, Entrega, HistorialPedido, HistorialRepartidor,
                           Insumo, MovimientoStock, Pedido, PrediccionDemanda, Producto, RecetaDetalle,
                           Repartidor, Restaurante, Usuario)
from app.orders.service import lock_order_relations
from app.demo_history.plan import (CLIENT_NAMES, COURIER_NAMES, DOMAIN, FIXED, INGREDIENTS, MARKER,
                                   OWNER_EMAIL, PER_KM, PRODUCTS, VERSION, digest)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / ".tools" / "history-demo"
TABLES = {**Base.metadata.tables, **AuthBase.metadata.tables}
HOURS = f"11:00 a 23:00 | {MARKER}"


def account_specs():
    return [(OWNER_EMAIL, "Lucía Fernández", "propietario"), (f"martin@{DOMAIN}", "Martín Acosta", "personal")] + [
        (f"cliente{i + 1:02}@{DOMAIN}", name, "cliente") for i, name in enumerate(CLIENT_NAMES)
    ] + [(f"repartidor{i + 1:02}@{DOMAIN}", name, "repartidor") for i, name in enumerate(COURIER_NAMES)]


def preflight(db):
    if db.bind.dialect.name != "postgresql":
        raise ValueError("La carga requiere PostgreSQL con las migraciones y restricciones reales.")
    revision = db.scalar(text("SELECT version_num FROM public.alembic_version"))
    if revision != "0003_producto_presentacion":
        raise ValueError("Se requiere la revisión autorizada 0003_producto_presentacion; no se migró nada.")
    columns = {row["name"]: row for row in inspect(db.connection()).get_columns("producto", schema="public")}
    if any(name not in columns or not columns[name]["nullable"] for name in ("descripcion", "imagen_url")):
        raise ValueError("Faltan los atributos opcionales autorizados de producto.")
    expected = {"tfg_validar_receta", "tfg_validar_detalle", "tfg_validar_entrega", "tfg_validar_movimiento",
                "tfg_validar_repartidor", "tfg_validar_historial", "tfg_pedido_con_detalles"}
    actual = set(db.scalars(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgenabled <> 'D' AND tgrelid IN (SELECT oid FROM pg_class WHERE relnamespace='public'::regnamespace)")))
    if not expected <= actual:
        raise ValueError("Faltan triggers de integridad de las migraciones aprobadas; no se cargaron datos.")


def find_restaurant(db):
    account = db.scalar(select(Usuario).where(Usuario.correo == OWNER_EMAIL))
    if account is None:
        if db.scalar(select(Usuario.id_usuario).where(Usuario.correo.in_([row[0] for row in account_specs()])).limit(1)):
            raise ValueError("Existen cuentas reservadas sin el propietario del dataset; se requiere revisión.")
        return None
    restaurant = db.get(Restaurante, account.id_restaurante) if account.id_restaurante else None
    if (account.rol != "propietario" or restaurant is None or restaurant.horario_atencion != HOURS
            or restaurant.nombre != "Rotisería del Pueblo"):
        raise ValueError("La identidad reservada no corresponde al dataset. Se rechazó la carga.")
    return restaurant.id_restaurante


def table_rows(db, table, predicate=None):
    query = select(table).order_by(*table.primary_key.columns)
    return [dict(row) for row in db.execute(query.where(predicate) if predicate is not None else query).mappings()]


def scope(db, restaurant_id):
    """Respaldo completo del restaurante y sus cuentas, incluyendo resultados derivados."""
    users = select(Usuario.id_usuario).where(Usuario.id_restaurante == restaurant_id)
    products = select(Producto.id_producto).where(Producto.id_restaurante == restaurant_id)
    ingredients = select(Insumo.id_insumo).where(Insumo.id_restaurante == restaurant_id)
    orders = select(Pedido.id_pedido).where(Pedido.id_restaurante == restaurant_id)
    couriers = select(Repartidor.id_repartidor).where(Repartidor.id_usuario.in_(users))
    predicates = {
        "restaurante": Restaurante.id_restaurante == restaurant_id, "usuario": Usuario.id_restaurante == restaurant_id,
        "cliente": Cliente.id_usuario.in_(users), "repartidor": Repartidor.id_usuario.in_(users),
        "producto": Producto.id_restaurante == restaurant_id, "insumo": Insumo.id_restaurante == restaurant_id,
        "receta_detalle": RecetaDetalle.id_producto.in_(products), "pedido": Pedido.id_restaurante == restaurant_id,
        "detalle_pedido": DetallePedido.id_pedido.in_(orders), "entrega": Entrega.id_pedido.in_(orders),
        "historial_pedido": HistorialPedido.id_pedido.in_(orders), "historial_repartidor": HistorialRepartidor.id_repartidor.in_(couriers),
        "movimiento_stock": MovimientoStock.id_insumo.in_(ingredients),
        "prediccion_demanda": PrediccionDemanda.id_producto.in_(products), "alerta": Alerta.id_restaurante == restaurant_id,
        "auth_sesion": AuthBase.metadata.tables["auth_sesion"].c.id_usuario.in_(users),
        "auth_estado_acceso": AuthBase.metadata.tables["auth_estado_acceso"].c.clave_correo.in_(
            [email_digest(email) for email in db.scalars(select(Usuario.correo).where(Usuario.id_restaurante == restaurant_id))]),
    }
    return {name: table_rows(db, TABLES[name], predicate) for name, predicate in predicates.items()}


def outside_fingerprint(db, own=None):
    own = own or {}
    result = {}
    for name, table in TABLES.items():
        owned = {tuple(row[col.name] for col in table.primary_key.columns) for row in own.get(name, [])}
        result[name] = [row for row in table_rows(db, table)
                       if tuple(row[col.name] for col in table.primary_key.columns) not in owned]
    return digest(result)


def encode(value):
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    raise TypeError(type(value).__name__)


def decode(value):
    if set(value) == {"$datetime"}:
        return datetime.fromisoformat(value["$datetime"])
    if set(value) == {"$date"}:
        return date.fromisoformat(value["$date"])
    if set(value) == {"$decimal"}:
        return Decimal(value["$decimal"])
    return value


def private_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Nunca sobrescribir un respaldo ni una entrega anterior de credenciales.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, default=encode, ensure_ascii=False, indent=2)
    path.chmod(0o600)
    return path


def backup_scope(db, restaurant_id, output):
    data = scope(db, restaurant_id)
    path = Path(output) / f"backup-restaurante-{restaurant_id}-{uuid4().hex}.json"
    private_json(path, {"format": VERSION, "restaurant_id": restaurant_id, "tables": data, "fingerprint": digest(data)})
    saved = json.loads(path.read_text(encoding="utf-8"), object_hook=decode)
    if digest(saved["tables"]) != saved["fingerprint"]:
        raise ValueError("No se pudo verificar el respaldo; no se reinició el dataset.")
    return path


def bulk(db, model, rows, returning=False):
    if not rows:
        return []
    table = model.__table__
    statement = insert(table)
    if returning:
        statement = statement.returning(next(iter(table.primary_key.columns)), sort_by_parameter_order=True)
    result = db.execute(statement, rows)
    return list(result.scalars()) if returning else []


def create_setup(db, plan):
    restaurant = Restaurante(nombre="Rotisería del Pueblo", direccion="San Martín 1240, Villa Oliva",
        horario_atencion=HOURS, abierto=False, costo_fijo_entrega=FIXED, costo_por_km=PER_KM)
    db.add(restaurant); db.flush()
    rid = restaurant.id_restaurante
    credentials = []
    users = []
    for email, name, role in account_specs():
        password = secrets.token_urlsafe(15)  # 20 caracteres, diferente para cada cuenta.
        users.append(dict(id_restaurante=rid, correo=email, nombre=name, rol=role, activo=True,
                          hash_contrasena=hash_password(password)))
        credentials.append(dict(correo=email, nombre=name, rol=role, contrasena=password))
    user_ids = bulk(db, Usuario, users, True)
    bulk(db, Cliente, [dict(id_usuario=user_ids[2 + i], nombre=name, direccion="Belgrano 450, Villa Oliva") for i, name in enumerate(CLIENT_NAMES)])
    bulk(db, Repartidor, [dict(id_usuario=user_ids[2 + len(CLIENT_NAMES) + i], estado_disponibilidad="No disponible", zona="Villa Oliva") for i in range(4)])
    ingredients = bulk(db, Insumo, [dict(id_restaurante=rid, nombre=row[0], unidad=row[1], costo_unitario=Decimal(row[2]), stock_actual=Decimal(0)) for row in INGREDIENTS], True)
    products = bulk(db, Producto, [dict(id_restaurante=rid, **row) for row in plan["products"]], True)
    bulk(db, RecetaDetalle, [dict(id_producto=products[i], id_insumo=ingredients[ingredient], cantidad=Decimal(qty), unidad=INGREDIENTS[ingredient][1])
                           for i, product in enumerate(PRODUCTS) for ingredient, qty in product[3]])
    return rid, credentials


def bindings(db, rid, plan):
    accounts = {row.correo: row for row in db.scalars(select(Usuario).where(Usuario.id_restaurante == rid))}
    if set(accounts) != {spec[0] for spec in account_specs()}:
        raise ValueError("Hay cuentas ajenas o faltantes en el restaurante dedicado; no se modificó nada.")
    for email, name, role in account_specs():
        if accounts[email].rol != role or accounts[email].nombre != name:
            raise ValueError("Las cuentas dedicadas fueron modificadas; no se reinició la carga.")
    products = {row.nombre: row for row in db.scalars(select(Producto).where(Producto.id_restaurante == rid))}
    ingredients = {row.nombre: row for row in db.scalars(select(Insumo).where(Insumo.id_restaurante == rid))}
    if set(products) != {row[0] for row in PRODUCTS} or set(ingredients) != {row[0] for row in INGREDIENTS}:
        raise ValueError("El catálogo contiene elementos ajenos o faltantes; no se reinició la carga.")
    product_ids = [products[row[0]].id_producto for row in PRODUCTS]
    ingredient_ids = [ingredients[row[0]].id_insumo for row in INGREDIENTS]
    for i, row in enumerate(plan["products"]):
        if any(getattr(products[row["nombre"]], key) != value for key, value in row.items()):
            raise ValueError("El catálogo fue editado; se requiere revisar esos cambios antes del reinicio.")
    expected = {(product_ids[i], ingredient_ids[j], Decimal(qty), INGREDIENTS[j][1]) for i, product in enumerate(PRODUCTS) for j, qty in product[3]}
    actual = set(db.execute(select(RecetaDetalle.id_producto, RecetaDetalle.id_insumo, RecetaDetalle.cantidad, RecetaDetalle.unidad).where(RecetaDetalle.id_producto.in_(product_ids))).all())
    if actual != expected:
        raise ValueError("Las recetas fueron editadas; se rechazó el reinicio.")
    clients = {row.id_usuario: row.id_cliente for row in db.scalars(select(Cliente).where(Cliente.id_usuario.in_([a.id_usuario for a in accounts.values()]))) }
    couriers = {row.id_usuario: row.id_repartidor for row in db.scalars(select(Repartidor).where(Repartidor.id_usuario.in_([a.id_usuario for a in accounts.values()]))) }
    return dict(products=product_ids, ingredients=ingredient_ids,
                clients=[clients[accounts[f"cliente{i + 1:02}@{DOMAIN}"].id_usuario] for i in range(len(CLIENT_NAMES))],
                couriers=[couriers[accounts[f"repartidor{i + 1:02}@{DOMAIN}"].id_usuario] for i in range(4)],
                courier_users=[accounts[f"repartidor{i + 1:02}@{DOMAIN}"].id_usuario for i in range(4)],
                owner=accounts[OWNER_EMAIL].id_usuario, staff=accounts[f"martin@{DOMAIN}"].id_usuario,
                client_users=[accounts[f"cliente{i + 1:02}@{DOMAIN}"].id_usuario for i in range(len(CLIENT_NAMES))])


def ownership_guard(db, rid, own):
    clients = {row["id_cliente"] for row in own["cliente"]}
    couriers = {row["id_repartidor"] for row in own["repartidor"]}
    users = {row["id_usuario"] for row in own["usuario"]}
    orders = {row["id_pedido"] for row in own["pedido"]}
    # Las FK de pertenencia no impiden que un cliente compre en otro restaurante.
    if db.scalar(select(Pedido.id_pedido).where(Pedido.id_cliente.in_(clients), Pedido.id_restaurante != rid).limit(1)):
        raise ValueError("Un cliente dedicado tiene pedidos externos; se rechazó el reinicio.")
    if db.scalar(select(Entrega.id_entrega).where(Entrega.id_repartidor.in_(couriers), Entrega.id_pedido.not_in(orders)).limit(1)):
        raise ValueError("Un repartidor dedicado tiene entregas externas.")
    if db.scalar(select(HistorialPedido.id_historial).where(HistorialPedido.id_usuario.in_(users), HistorialPedido.id_pedido.not_in(orders)).limit(1)):
        raise ValueError("Una cuenta dedicada tiene historial externo.")
    if any(MARKER not in (row["referencia_local"] or "") for row in own["pedido"]):
        raise ValueError("Hay pedidos sin marca del generador; no se borraron.")
    if any(MARKER not in (row["motivo"] or "") for row in own["movimiento_stock"]):
        raise ValueError("Hay movimientos posteriores ajenos al generador; no se borraron.")
    if any(MARKER not in (row["detalle"] or "") for row in own["historial_pedido"]):
        raise ValueError("Hay eventos posteriores ajenos al generador; no se borraron.")


def reset_history(db, rid, own, clear_derived):
    if (own["prediccion_demanda"] or own["alerta"]) and not clear_derived:
        raise ValueError("Existen resultados de la aplicación. Revisá el respaldo y usá --clear-derived para retirarlos del restaurante dedicado.")
    orders = [row["id_pedido"] for row in own["pedido"]]
    ingredients = [row["id_insumo"] for row in own["insumo"]]
    products = [row["id_producto"] for row in own["producto"]]
    couriers = [row["id_repartidor"] for row in own["repartidor"]]
    for model, predicate in ((MovimientoStock, MovimientoStock.id_insumo.in_(ingredients)),
            (HistorialPedido, HistorialPedido.id_pedido.in_(orders)), (Entrega, Entrega.id_pedido.in_(orders)),
            (DetallePedido, DetallePedido.id_pedido.in_(orders)), (Pedido, Pedido.id_pedido.in_(orders)),
            (HistorialRepartidor, HistorialRepartidor.id_repartidor.in_(couriers)),
            (PrediccionDemanda, PrediccionDemanda.id_producto.in_(products)), (Alerta, Alerta.id_restaurante == rid)):
        db.execute(delete(model).where(predicate))


def reference(plan, index):
    return f"{plan['marker']} seed={plan['seed']};as_of={plan['as_of']};fp={plan['fingerprint']};order={index}"


def insert_history(db, rid, plan, ids):
    marker = plan["marker"]
    courier_names = plan.get("courier_names", COURIER_NAMES)
    order_ids = bulk(db, Pedido, [dict(id_restaurante=rid, id_cliente=ids["clients"][row["client"]],
        fecha_hora=row["fecha_hora"], estado=row["estado"], direccion_entrega=row["direccion_entrega"],
        referencia_local=reference(plan, row["local_id"]), zona_entrega="Villa Oliva", medio_pago=row["medio_pago"],
        estado_pago=row["estado_pago"], importe_total=row["importe_total"], costo_total=row["costo_total"],
        distancia_km=row["distancia_km"], puntaje_prioridad=row.get("puntaje_prioridad"), factores_prioridad=row.get("factores_prioridad")) for row in plan["orders"]], True)
    bulk(db, DetallePedido, [dict(id_pedido=order_ids[row["local_id"]], id_producto=ids["products"][product],
        cantidad=qty, precio_unitario=plan["products"][product]["precio"]) for row in plan["orders"] for product, qty in row["items"]])
    events, cycle_indexes = [], {}
    for row in plan["orders"]:
        index = row["local_id"]
        def event(timestamp, kind, state, actor, detail):
            events.append(dict(id_pedido=order_ids[index], id_usuario=actor, fecha_hora=timestamp,
                               tipo_evento=kind, estado=state, detalle=f"{marker} {detail}"))
        tags = "; ".join(row["tags"]) or "Operación histórica generada."
        event(row["fecha_hora"], "registro", "Nuevo", ids["client_users"][row["client"]], tags)
        if row["estado"] == "Nuevo":
            continue
        cycle_indexes[index, 0] = len(events)
        event(row["prep_start"], "preparacion", "En preparación", ids["staff"], "Preparación según receta.")
        if row["repeat"]:
            from datetime import timedelta
            cycle_indexes[index, 1] = len(events)
            event(row["prep_start"] + timedelta(minutes=8), "nueva_preparacion", "En preparación", ids["staff"], "Cocción arruinada; nueva preparación explícita.")
        if row["estado"] == "En preparación":
            continue
        event(row["ready"], "estado", "Listo", ids["staff"], tags)
        if "courier" in row:
            event(row["assigned"], "asignacion", "Asignado", ids["owner"], f"Repartidor: {courier_names[row['courier']]}.")
            event(row["departure"], "entrega", "En camino", ids["courier_users"][row["courier"]], "Salida a reparto.")
            event(row["end"], "entrega", row["estado"], ids["courier_users"][row["courier"]], tags)
    event_ids = bulk(db, HistorialPedido, events, True)
    bulk(db, Entrega, [dict(id_pedido=order_ids[row["local_id"]], id_repartidor=ids["couriers"][row["courier"]],
        fecha_asignacion=row["assigned"], estado=row["estado"], costo_repartidor=row["costo_repartidor"]) for row in plan["orders"] if "courier" in row])
    movements = []
    for row in plan["movements"]:
        reason = row["motivo"]
        if row["order"] is not None:
            reason = f"Preparación #{event_ids[cycle_indexes[row['order'], row['cycle']]]}: {reason}"
        movements.append(dict(id_insumo=ids["ingredients"][row["ingredient"]],
            id_pedido=order_ids[row["order"]] if row["order"] is not None else None,
            fecha_hora=row["fecha_hora"], tipo=row["tipo"], cantidad=row["cantidad"], motivo=reason))
    bulk(db, MovimientoStock, sorted(movements, key=lambda row: row["fecha_hora"]))
    bulk(db, HistorialRepartidor, [dict(id_repartidor=ids["couriers"][row["courier"]], estado=row["estado"], fecha_hora=row["fecha_hora"]) for row in plan["courier_events"]])
    for i, ingredient in enumerate(ids["ingredients"]):
        db.get(Insumo, ingredient).stock_actual = plan["stock"][i]
    for courier in ids["couriers"]:
        db.get(Repartidor, courier).estado_disponibilidad = "No disponible"
    db.flush()


def load_dataset(engine, plan, *, reset=False, restaurant_id=None, clear_derived=False, output=DEFAULT_OUTPUT):
    from app.demo_history.validation import validate_dataset
    credentials_path = backup = None
    run_id = uuid4().hex
    with Session(engine) as db, db.begin():
        preflight(db)
        lock_order_relations(db)
        rid = find_restaurant(db)
        if restaurant_id is not None and rid != restaurant_id:
            raise ValueError("El ID solicitado no coincide con la identidad reservada del dataset.")
        own = scope(db, rid) if rid is not None else None
        baseline = outside_fingerprint(db, own)
        if rid is not None:
            backup = backup_scope(db, rid, output)
            ownership_guard(db, rid, own)
            if not reset:
                if any(row["referencia_local"] != reference(plan, i) for i, row in enumerate(own["pedido"])) or len(own["pedido"]) != len(plan["orders"]):
                    raise ValueError("Ya existe un historial de otra semilla/período. Para reemplazarlo usá --reset y su ID explícito.")
                result = validate_dataset(db, rid, plan)
                return {**result, "action": "unchanged", "backup": str(backup)}
            if restaurant_id is None:
                raise ValueError("El reinicio exige --restaurant-id con el ID dedicado.")
            bindings(db, rid, plan)
            reset_history(db, rid, own, clear_derived)
        else:
            if reset:
                raise ValueError("No existe un dataset dedicado que reiniciar.")
            rid, credentials = create_setup(db, plan)
            credentials_path = private_json(Path(output) / f"credentials-{rid}-{run_id}.json", {"restaurant_id": rid, "accounts": credentials})
        ids = bindings(db, rid, plan)
        insert_history(db, rid, plan, ids)
        result = validate_dataset(db, rid, plan)
        db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        if outside_fingerprint(db, scope(db, rid)) != baseline:
            raise ValueError("Cambió información externa durante la carga; el dataset no se confirmó.")
        result.update(action="reset" if reset else "created", backup=str(backup) if backup else None,
                      credentials=str(credentials_path) if credentials_path else None, outside_unchanged=True)
    private_json(Path(output) / f"manifest-{rid}-{run_id}.json", result)
    return result
