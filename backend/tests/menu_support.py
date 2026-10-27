"""Catálogo sintético para pruebas/QA; sin conexión a Supabase."""

from pathlib import Path

from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.models import AuthBase
from app.db.base import Base
from app.db.models import Insumo, Producto
from tests.auth_support import seed


def add_ingredients(db):
    db.add_all([
        Insumo(id_insumo=1, id_restaurante=1, nombre="Harina sintética", unidad="kg", stock_actual=20, costo_unitario=1000),
        Insumo(id_insumo=2, id_restaurante=1, nombre="Agua sintética", unidad="l", stock_actual=50, costo_unitario=10),
        Insumo(id_insumo=3, id_restaurante=2, nombre="Queso sintético", unidad="kg", stock_actual=10, costo_unitario=3000),
    ])
    db.commit()


def sqlite_menu_engine(database: Path | None = None):
    options = {"poolclass": StaticPool} if database is None else {}
    engine = create_engine(URL.create("sqlite", database=str(database) if database else None),
                           connect_args={"check_same_thread": False}, **options)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    AuthBase.metadata.create_all(engine)
    with Session(engine) as db:
        seed(db, include_order_details=True)
        add_ingredients(db)
        db.get(Producto, 1).nombre = "Pizza sintética"
        db.get(Producto, 2).nombre = "Producto de otro restaurante"
        db.commit()
    return engine
