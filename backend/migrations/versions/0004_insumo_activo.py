"""Baja lógica de insumos conservando sus relaciones históricas."""
from alembic import op
import sqlalchemy as sa

revision = "0004_insumo_activo"
down_revision = "0003_producto_presentacion"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("insumo", sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()), schema="public")

def downgrade():
    op.drop_column("insumo", "activo", schema="public")
