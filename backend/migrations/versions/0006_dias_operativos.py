"""Fechas operativas por restaurante y reconstrucción desde pedidos históricos."""
from alembic import op
import sqlalchemy as sa

revision = '0006_dias_operativos'
down_revision = '0005_disponibilidad_repartidor'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('dia_operativo',
        sa.Column('id_restaurante', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(['id_restaurante'], ['public.restaurante.id_restaurante'], ondelete='RESTRICT', onupdate='RESTRICT'),
        sa.PrimaryKeyConstraint('id_restaurante', 'fecha'), schema='public')
    op.execute("""INSERT INTO public.dia_operativo (id_restaurante, fecha)
        SELECT DISTINCT id_restaurante, (fecha_hora AT TIME ZONE 'America/Argentina/Buenos_Aires')::date
        FROM public.pedido ON CONFLICT DO NOTHING""")
    op.execute("""INSERT INTO public.dia_operativo (id_restaurante, fecha)
        SELECT id_restaurante, (now() AT TIME ZONE 'America/Argentina/Buenos_Aires')::date
        FROM public.restaurante WHERE abierto ON CONFLICT DO NOTHING""")
    op.execute('ALTER TABLE public.dia_operativo ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON TABLE public.dia_operativo FROM PUBLIC, anon, authenticated, service_role')

def downgrade():
    op.drop_table('dia_operativo', schema='public')
