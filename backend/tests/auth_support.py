"""Fixture sintética SQLite para lógica/API, NO integración PostgreSQL."""

from datetime import UTC, datetime
from functools import lru_cache

from fastapi import Depends, FastAPI
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.config import AuthSettings
from app.auth.dependencies import (
    accessible_order, assigned_delivery, auth_settings, own_client,
    require_restaurant, require_roles,
)
from app.auth.models import AuthBase
from app.auth.security import hash_password
from app.db.base import Base
from app.db.models import Cliente, DetallePedido, Entrega, Pedido, Producto, Repartidor, Restaurante, Usuario

PASSWORD = "Frase demo segura 42"
ORIGIN = "http://127.0.0.1:5173"
HEADERS = {"Origin": ORIGIN, "X-CSRF-Protection": "1"}


@compiles(JSONB, "sqlite")
def sqlite_jsonb(element, compiler, **kw):
    return "JSON"


@lru_cache(maxsize=1)
def fixture_hash():
    return hash_password(PASSWORD)


def seed(db, *, include_order_details=False):
    for number in (1, 2):
        db.add(Restaurante(id_restaurante=number, nombre=f"Sintético {number}",
                           direccion="Prueba", horario_atencion="Prueba", abierto=True,
                           costo_fijo_entrega=0, costo_por_km=0))
    db.flush()
    users = [
        (1, 1, "personal"), (2, 2, "personal"), (3, None, "cliente"),
        (4, None, "cliente"), (5, 1, "repartidor"), (6, 2, "repartidor"),
        (7, 1, "propietario"), (8, None, "administrador_plataforma"), (9, 1, "repartidor"),
    ]
    for number, restaurant, role in users:
        db.add(Usuario(id_usuario=number, id_restaurante=restaurant, correo=f"u{number}@test.invalid",
                       nombre=f"Usuario sintético {number}", rol=role, activo=True,
                       hash_contrasena=fixture_hash()))
    db.flush()
    db.add_all([Cliente(id_cliente=1, id_usuario=3, nombre="Cliente sintético 1"),
                Cliente(id_cliente=2, id_usuario=4, nombre="Cliente sintético 2")])
    for number, user in ((1, 5), (2, 6), (3, 9)):
        db.add(Repartidor(id_repartidor=number, id_usuario=user, estado_disponibilidad="Disponible"))
    db.flush()
    if include_order_details:
        for number in (1, 2):
            db.add(Producto(id_producto=number, id_restaurante=number, nombre=f"Producto sintético {number}",
                            precio=100, costo_unitario=10, activo=True))
        db.flush()
    for number, restaurant, client in ((1, 1, 1), (2, 2, 2), (3, 2, 1)):
        db.add(Pedido(id_pedido=number, id_restaurante=restaurant, id_cliente=client,
                      fecha_hora=datetime(2026, 10, 26, tzinfo=UTC), estado="Nuevo",
                      direccion_entrega="Prueba", medio_pago="efectivo", estado_pago="pendiente",
                      importe_total=100, distancia_km=1, costo_total=10))
    db.flush()
    if include_order_details:
        for number, product in ((1, 1), (2, 2), (3, 2)):
            db.add(DetallePedido(id_detalle=number, id_pedido=number, id_producto=product,
                                 cantidad=1, precio_unitario=100))
    db.add_all([Entrega(id_entrega=1, id_pedido=1, id_repartidor=1, estado="asignada", costo_repartidor=0),
                Entrega(id_entrega=2, id_pedido=2, id_repartidor=2, estado="asignada", costo_repartidor=0)])
    db.commit()


def sqlite_engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    selected = [Restaurante, Usuario, Cliente, Repartidor, Pedido, Entrega]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in selected])
    AuthBase.metadata.create_all(engine)
    with Session(engine) as db:
        seed(db)
    return engine


def mount_test_routes(app: FastAPI):
    # Solo fixture de pruebas: nunca se montan en app.main ni publican otras HU.
    @app.get("/api/test/restaurant/{id_restaurante}")
    def restaurant(user=Depends(require_restaurant("personal", "propietario"))):
        return {"id_usuario": user.id_usuario}

    @app.post("/api/test/restaurant/{id_restaurante}")
    def change_restaurant(user=Depends(require_restaurant("personal", "propietario"))):
        return {"id_usuario": user.id_usuario}

    @app.get("/api/test/owner")
    def owner(user=Depends(require_roles("propietario"))):
        return {"id_usuario": user.id_usuario}

    @app.get("/api/test/client/{id_cliente}")
    def client(value=Depends(own_client)):
        return {"id_cliente": value.id_cliente}

    @app.get("/api/test/order/{id_pedido}")
    def order(value=Depends(accessible_order)):
        return {"id_pedido": value.id_pedido}

    @app.get("/api/test/delivery/{id_entrega}")
    def delivery(value=Depends(assigned_delivery)):
        return {"id_entrega": value.id_entrega}


def override_database(app, engine, *, secure=False):
    from app.auth.database import get_db

    def db_override():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[auth_settings] = lambda: AuthSettings(frozenset({ORIGIN}), secure)
