"""Tablas técnicas aprobadas. Metadatos separados del DER de negocio."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, MetaData, Text, column
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.base import Base
from app.db.models import Usuario


class AuthBase(DeclarativeBase):
    metadata = MetaData(naming_convention=Base.metadata.naming_convention)


class EstadoAcceso(AuthBase):
    __tablename__ = "auth_estado_acceso"
    __table_args__ = (
        CheckConstraint(column("clave_correo").regexp_match("^[0-9a-f]{64}$"), name="hash_hexadecimal"),
        CheckConstraint("intentos_fallidos BETWEEN 0 AND 5", name="intentos_rango"),
    )

    clave_correo: Mapped[str] = mapped_column(Text, primary_key=True)
    intentos_fallidos: Mapped[int] = mapped_column(Integer)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Sesion(AuthBase):
    __tablename__ = "auth_sesion"
    __table_args__ = (
        CheckConstraint(column("token_hash").regexp_match("^[0-9a-f]{64}$"), name="hash_hexadecimal"),
        CheckConstraint("expira_en > creada_en", name="vencimiento_valido"),
    )

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    id_usuario: Mapped[int] = mapped_column(
        ForeignKey(Usuario.id_usuario, ondelete="RESTRICT", onupdate="RESTRICT"), index=True,
    )
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
