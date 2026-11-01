"""Dos atributos opcionales autorizados para la carta del cliente.

Sin tablas nuevas, sin cambios a registros existentes. No aplicada a Supabase.
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_producto_presentacion"
down_revision = "0002_hu01_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("producto", sa.Column("descripcion", sa.Text(), nullable=True), schema="public")
    op.add_column("producto", sa.Column("imagen_url", sa.Text(), nullable=True), schema="public")


def downgrade():
    op.drop_column("producto", "imagen_url", schema="public")
    op.drop_column("producto", "descripcion", schema="public")
