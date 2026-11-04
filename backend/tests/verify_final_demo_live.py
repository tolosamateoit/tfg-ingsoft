"""Verificación real: seis accesos y consultas; no crea pedidos ni modifica historia."""
from pathlib import Path
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from app.main import app
from app.auth.config import get_auth_settings
from app.auth.database import get_engine
from app.db.models import Usuario, Restaurante, Pedido, Producto, Insumo
from app.analytics.forecast import calculate_forecast
from app.analytics.operational import operational_dashboard
from app.logistics.priority import priority_preview


def main():
    env = dotenv_values(Path(__file__).resolve().parents[2] / 'frontend' / '.env.development.local')
    headers = {'Origin': sorted(get_auth_settings().allowed_origins)[0], 'X-CSRF-Protection':'1'}
    client = TestClient(app)  # Sin lifespan: esta verificación no inicia el simulador.
    for role in ('PROPIETARIO', 'PERSONAL', 'CLIENTE', 'REPARTIDOR', 'REPARTIDOR_2', 'REPARTIDOR_3'):
        result = client.post('/api/auth/login', headers=headers, json={
            'correo':env[f'LOCAL_ACCOUNT_{role}_EMAIL'], 'contrasena':env['LOCAL_ACCOUNT_PASSWORD']})
        assert result.status_code == 200, (role, result.status_code)
        assert result.json()['restaurante'] == 'Rotisería del Pueblo'
        assert client.get('/api/auth/me').status_code == 200
        assert client.post('/api/auth/logout', headers=headers).status_code == 204
    client.close()
    print('Accesos de los seis usuarios: OK', flush=True)
    with Session(get_engine()) as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        assert db.scalars(select(Restaurante.id_restaurante)).all() == [1]
        assert db.scalar(select(func.count()).select_from(Usuario)) == 6
        assert db.scalar(select(func.count()).select_from(Pedido)) == 4834
        for model in (Usuario, Pedido, Producto, Insumo):
            assert db.scalar(select(func.count()).select_from(model).where(model.id_restaurante != 1)) == 0
        owner = db.scalar(select(Usuario).where(Usuario.rol == 'propietario'))
        forecast = calculate_forecast(db, owner.id_restaurante)
        assert forecast.predicciones
        dashboard = operational_dashboard(db, owner, owner.id_restaurante)
        assert dashboard.pedidos >= 0
        priority_preview(db, owner.id_restaurante)
        print(f'Historial: 4834 pedidos. Previsión: {len(forecast.predicciones)} productos. Indicadores, alertas y prioridades: OK.', flush=True)


if __name__ == '__main__':
    main()
