"""Unificar la disponibilidad de los repartidores.

Revision ID: 0005_disponibilidad_repartidor
Revises: 0004_insumo_activo
"""
from alembic import op

revision = '0005_disponibilidad_repartidor'
down_revision = '0004_insumo_activo'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("UPDATE repartidor SET estado_disponibilidad = 'No disponible' WHERE estado_disponibilidad = 'Ocupado'")
    op.execute("UPDATE historial_repartidor SET estado = 'No disponible' WHERE estado = 'Ocupado'")
    op.execute("""UPDATE repartidor r SET estado_disponibilidad = 'No disponible'
        WHERE EXISTS (SELECT 1 FROM entrega e WHERE e.id_repartidor = r.id_repartidor
                      AND e.estado IN ('Asignado', 'En camino', 'asignada'))""")
    op.create_check_constraint('ck_repartidor_disponibilidad', 'repartidor', "estado_disponibilidad IN ('Disponible', 'No disponible')")

def downgrade():
    op.drop_constraint('ck_repartidor_disponibilidad', 'repartidor', type_='check')
