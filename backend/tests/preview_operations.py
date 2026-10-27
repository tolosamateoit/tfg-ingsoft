"""QA visual HU-04 a HU-07: datos sintéticos locales descartables, nunca Supabase.

python -m uvicorn tests.preview_operations:app --host 127.0.0.1 --port 8001
"""

from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session
from sqlalchemy import delete

from app.api.auth import router as auth_router
from app.api.menu import router as menu_router
from app.api.orders import router as orders_router
from app.api.preparation import router as preparation_router
from app.api.couriers import router as couriers_router
from app.api.logistics import router as logistics_router
from app.auth.config import AuthSettings
from app.auth.dependencies import auth_settings
from app.db.models import Entrega, RecetaDetalle
from app.main import private_responses, validation_error
from tests.auth_support import override_database
from tests.menu_support import sqlite_menu_engine


@asynccontextmanager
async def lifespan(app):
    with TemporaryDirectory(prefix="tfg-operations-qa-") as directory:
        engine = sqlite_menu_engine(Path(directory) / "qa.sqlite")
        with Session(engine) as db:
            db.execute(delete(Entrega))  # Solo fixture: empezar con pedidos sin asignación.
            db.add_all([RecetaDetalle(id_producto=1, id_insumo=1, cantidad=Decimal("0.2"), unidad="kg"),
                        RecetaDetalle(id_producto=1, id_insumo=2, cantidad=Decimal("0.1"), unidad="l")])
            db.commit()
        override_database(app, engine)
        app.dependency_overrides[auth_settings] = lambda: AuthSettings(
            frozenset({"http://127.0.0.1:5173", "http://127.0.0.2:5174"}), False)
        with patch("app.auth.service.lock_email"), patch("app.menu.service.lock_recipe_relations"), \
                patch("app.orders.service.lock_order_relations"), patch("app.preparation.service.lock_order_relations"), \
                patch("app.couriers.service.lock_order_relations"), patch("app.logistics.priority.lock_order_relations"), \
                patch("app.logistics.service.lock_order_relations"):
            try:
                yield
            finally:
                engine.dispose()


app = FastAPI(title="QA HU-04 a HU-07 — SINTÉTICO SQLite, sin Supabase", lifespan=lifespan)
for router in (auth_router, menu_router, orders_router, preparation_router, couriers_router, logistics_router):
    app.include_router(router, prefix="/api")
app.add_exception_handler(RequestValidationError, validation_error)
app.middleware("http")(private_responses)
