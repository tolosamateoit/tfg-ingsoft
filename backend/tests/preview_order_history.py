"""QA de listados con más de una página; SQLite temporal, nunca Supabase."""

from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta

from app.auth.config import AuthSettings
from app.auth.database import get_db
from app.auth.dependencies import auth_settings
from app.db.models import DetallePedido, Pedido
from tests.preview_completion import app

previous = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    async with previous(application):
        app.dependency_overrides[auth_settings] = lambda: AuthSettings(frozenset({"http://127.0.0.1:5178"}), False)
        with contextmanager(app.dependency_overrides[get_db])() as db:
            for i in range(45):
                row = Pedido(id_restaurante=1, id_cliente=1,
                    fecha_hora=datetime(2026, 10, 31 if i < 22 else 30, 15, tzinfo=UTC) + timedelta(minutes=i),
                    estado="Nuevo", direccion_entrega="Dirección de QA", medio_pago="efectivo",
                    estado_pago="pendiente", importe_total=19000, costo_total=6400, distancia_km=1)
                db.add(row); db.flush()
                db.add(DetallePedido(id_pedido=row.id_pedido, id_producto=1, cantidad=2, precio_unitario=9500))
            db.commit()
        yield


app.router.lifespan_context = lifespan
