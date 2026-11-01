"""QA descartable de cuatro roles y 901 alertas. Nunca usa Supabase."""
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime

from app.auth.config import AuthSettings
from app.auth.database import get_db
from app.auth.dependencies import auth_settings
from app.db.models import Alerta
from tests.preview_completion import app

previous = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    async with previous(application):
        app.dependency_overrides[auth_settings] = lambda: AuthSettings(frozenset({"http://127.0.0.1:5176"}), False)
        with contextmanager(app.dependency_overrides[get_db])() as db:
            for i in range(901):
                db.add(Alerta(id_restaurante=1, tipo=("importe", "entrega", "preparacion", "stock")[i % 4],
                              descripcion=f"qa:{i} | Incidencia operativa registrada #{i + 1}.",
                              valor_observado=3 if i % 3 == 0 else 2, valor_referencia=1,
                              estado="Resuelta" if i % 5 == 0 else "Activa",
                              fecha_hora=datetime(2026, 10, 30, 12, tzinfo=UTC)))
            db.commit()
        yield


app.router.lifespan_context = lifespan
