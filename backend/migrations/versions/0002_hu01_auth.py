"""HU-01: dos tablas técnicas aprobadas, sin cambios a las tablas del DER.

Preparada para revisión. No aplicada a Supabase por el agente.
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_hu01_auth"
down_revision = "0001_der_inicial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_estado_acceso",
        sa.Column("clave_correo", sa.Text(), nullable=False),
        sa.Column("intentos_fallidos", sa.Integer(), nullable=False),
        sa.Column("bloqueado_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("clave_correo", name="pk_auth_estado_acceso"),
        sa.CheckConstraint("clave_correo ~ '^[0-9a-f]{64}$'", name="ck_auth_estado_acceso_hash_hexadecimal"),
        sa.CheckConstraint("intentos_fallidos BETWEEN 0 AND 5", name="ck_auth_estado_acceso_intentos_rango"),
        schema="public",
    )
    op.create_index("ix_auth_estado_acceso_actualizado_en", "auth_estado_acceso", ["actualizado_en"], schema="public")
    op.create_table(
        "auth_sesion",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("id_usuario", sa.Integer(), nullable=False),
        sa.Column("creada_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("token_hash", name="pk_auth_sesion"),
        sa.ForeignKeyConstraint(["id_usuario"], ["public.usuario.id_usuario"],
                                name="fk_auth_sesion_id_usuario_usuario", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_auth_sesion_hash_hexadecimal"),
        sa.CheckConstraint("expira_en > creada_en", name="ck_auth_sesion_vencimiento_valido"),
        schema="public",
    )
    op.create_index("ix_auth_sesion_id_usuario", "auth_sesion", ["id_usuario"], schema="public")
    op.create_index("ix_auth_sesion_expira_en", "auth_sesion", ["expira_en"], schema="public")
    for name in ("auth_estado_acceso", "auth_sesion"):
        op.execute(f"ALTER TABLE public.{name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE public.{name} FROM PUBLIC, anon, authenticated, service_role")


def downgrade():
    op.drop_table("auth_sesion", schema="public")
    op.drop_table("auth_estado_acceso", schema="public")
