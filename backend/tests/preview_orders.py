"""QA HU-03 local con datos sintéticos descartables; nunca conecta a Supabase.

python -m uvicorn tests.preview_orders:app --host 127.0.0.1 --port 8001
"""

from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.auth import router as auth_router
from app.api.menu import router as menu_router
from app.api.orders import router as orders_router
from app.main import private_responses, validation_error
from tests.auth_support import override_database
from tests.menu_support import sqlite_menu_engine


@asynccontextmanager
async def lifespan(app):
    with TemporaryDirectory(prefix="tfg-orders-qa-") as directory:
        engine = sqlite_menu_engine(Path(directory) / "qa.sqlite")
        override_database(app, engine)
        with patch("app.auth.service.lock_email"), patch("app.menu.service.lock_recipe_relations"), \
                patch("app.orders.service.lock_order_relations"):
            try:
                yield
            finally:
                engine.dispose()


app = FastAPI(title="QA HU-03 — SINTÉTICO SQLite, sin Supabase", lifespan=lifespan)
for router in (auth_router, menu_router, orders_router):
    app.include_router(router, prefix="/api")
app.add_exception_handler(RequestValidationError, validation_error)
app.middleware("http")(private_responses)
