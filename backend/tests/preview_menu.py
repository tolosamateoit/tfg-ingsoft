"""QA visual HU-02 exclusivamente local, con catálogo SINTÉTICO SQLite.

python -m uvicorn tests.preview_menu:app --host 127.0.0.1 --port 8001
No usar para desplegar; nunca conecta a Supabase ni aplica migraciones.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.auth import router as auth_router
from app.api.menu import router as menu_router
from app.main import private_responses, validation_error
from tests.auth_support import override_database
from tests.menu_support import sqlite_menu_engine


@asynccontextmanager
async def lifespan(app):
    # Archivo temporal: cada petición usa su conexión, incluso con GET paralelos.
    with TemporaryDirectory(prefix="tfg-menu-qa-") as directory:
        engine = sqlite_menu_engine(Path(directory) / "qa.sqlite")
        override_database(app, engine)
        with patch("app.auth.service.lock_email"), patch("app.menu.service.lock_recipe_relations"):
            try:
                yield
            finally:
                engine.dispose()


app = FastAPI(title="QA HU-02 — SINTÉTICO SQLite, sin Supabase", lifespan=lifespan)
app.include_router(auth_router, prefix="/api")
app.include_router(menu_router, prefix="/api")
app.add_exception_handler(RequestValidationError, validation_error)
app.middleware("http")(private_responses)
