"""Marca técnica de cambio de contraseña obligatorio tras un incidente."""
from alembic import op
import sqlalchemy as sa

revision = '0007_cambio_clave_pendiente'
down_revision = '0006_dias_operativos'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('auth_cambio_clave_pendiente',
        sa.Column('id_usuario', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['id_usuario'], ['public.usuario.id_usuario'], ondelete='RESTRICT', onupdate='RESTRICT'),
        sa.PrimaryKeyConstraint('id_usuario'), schema='public')
    op.execute('ALTER TABLE public.auth_cambio_clave_pendiente ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON TABLE public.auth_cambio_clave_pendiente FROM PUBLIC, anon, authenticated, service_role')

def downgrade():
    op.drop_table('auth_cambio_clave_pendiente', schema='public')
