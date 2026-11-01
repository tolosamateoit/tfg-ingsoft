"""QA local de esta etapa, sin Supabase ni historial masivo.

python -m uvicorn tests.preview_completion:app --host 127.0.0.1 --port 8003
"""

from contextlib import asynccontextmanager, contextmanager
from unittest.mock import patch

from app.auth.config import AuthSettings
from app.auth.database import get_db
from app.auth.dependencies import auth_settings
from app.db.models import Cliente, Insumo, Producto, Restaurante, Usuario
from tests.preview_operations import app
from app.api.analytics import router as analytics_router
from app.api.dashboard import router as dashboard_router
from app.api.support import router as support_router

for router in (analytics_router, dashboard_router, support_router):
    app.include_router(router, prefix="/api")

original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    async with original_lifespan(application):
        app.dependency_overrides[auth_settings] = lambda: AuthSettings(frozenset({"http://127.0.0.1:5174"}), False)
        with contextmanager(app.dependency_overrides[get_db])() as db:
            names = {1: "Martín Acosta", 2: "Sofía Torres", 3: "Valentina López", 4: "Joaquín Pérez",
                     5: "Diego Ramírez", 6: "Bruno Castro", 7: "Lucía Fernández", 8: "Carolina Méndez", 9: "Ana Silva"}
            for id, name in names.items():
                db.get(Usuario, id).nombre = name
            for id, name in ((1, "Rotisería del Pueblo"), (2, "La Esquina de Julia")):
                db.get(Restaurante, id).nombre = name
            db.get(Cliente, 1).nombre = names[3]
            db.get(Cliente, 2).nombre = names[4]
            product = db.get(Producto, 1)
            product.nombre = "Pizza Margarita"
            product.descripcion = "Mozzarella, tomate y albahaca fresca."
            product.precio = 9500
            product.costo_unitario = 3200
            for id, name in ((1, "Harina de trigo"), (2, "Agua"), (3, "Queso mozzarella")):
                db.get(Insumo, id).nombre = name
            db.commit()
        with patch("app.menu.inventory.lock_recipe_relations"), patch("app.couriers.service.lock_email"), \
                patch("app.analytics.forecast.lock_order_relations"), patch("app.analytics.metrics.lock_order_relations"):
            yield


app.router.lifespan_context = lifespan
