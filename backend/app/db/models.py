"""Entidades de docs/der/der.png, pendientes de aprobación para Supabase.

No crear tablas al importar. La revisión 0001 agrega los triggers de pertenencia
aprobados y preserva esta estructura sin columnas adicionales.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Identity, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def primary_key():
    return mapped_column(Integer, Identity(), primary_key=True)


def reference(target: str, *, nullable: bool = False, unique: bool = False):
    return mapped_column(
        ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=nullable, unique=unique, index=not unique,
    )


class Restaurante(Base):
    __tablename__ = "restaurante"
    __table_args__ = (
        CheckConstraint("costo_fijo_entrega >= 0", name="costo_fijo_entrega_no_negativo"),
        CheckConstraint("costo_por_km >= 0", name="costo_por_km_no_negativo"),
    )

    id_restaurante: Mapped[int] = primary_key()
    nombre: Mapped[str] = mapped_column(Text)
    direccion: Mapped[str] = mapped_column(Text)
    horario_atencion: Mapped[str] = mapped_column(Text)
    abierto: Mapped[bool] = mapped_column(Boolean)
    costo_fijo_entrega: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    costo_por_km: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="restaurante")
    productos: Mapped[list["Producto"]] = relationship(back_populates="restaurante")
    insumos: Mapped[list["Insumo"]] = relationship(back_populates="restaurante")
    pedidos: Mapped[list["Pedido"]] = relationship(back_populates="restaurante")
    alertas: Mapped[list["Alerta"]] = relationship(back_populates="restaurante")


class Usuario(Base):
    __tablename__ = "usuario"

    id_usuario: Mapped[int] = primary_key()
    id_restaurante: Mapped[int | None] = reference("restaurante.id_restaurante", nullable=True)
    correo: Mapped[str] = mapped_column(Text, unique=True)
    nombre: Mapped[str] = mapped_column(Text)
    hash_contrasena: Mapped[str] = mapped_column(Text)
    telefono: Mapped[str | None] = mapped_column(Text)
    rol: Mapped[str] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(Boolean)

    restaurante: Mapped["Restaurante | None"] = relationship(back_populates="usuarios")
    cliente: Mapped["Cliente | None"] = relationship(back_populates="usuario")
    repartidor: Mapped["Repartidor | None"] = relationship(back_populates="usuario")
    eventos_pedido: Mapped[list["HistorialPedido"]] = relationship(back_populates="usuario")


class Cliente(Base):
    __tablename__ = "cliente"

    id_cliente: Mapped[int] = primary_key()
    id_usuario: Mapped[int] = reference("usuario.id_usuario", unique=True)
    nombre: Mapped[str] = mapped_column(Text)
    telefono: Mapped[str | None] = mapped_column(Text)
    direccion: Mapped[str | None] = mapped_column(Text)
    referencia_local: Mapped[str | None] = mapped_column(Text)
    zona_entrega: Mapped[str | None] = mapped_column(Text)

    usuario: Mapped["Usuario"] = relationship(back_populates="cliente")
    pedidos: Mapped[list["Pedido"]] = relationship(back_populates="cliente")


class Producto(Base):
    __tablename__ = "producto"
    __table_args__ = (
        CheckConstraint("precio >= 0", name="precio_no_negativo"),
        CheckConstraint("costo_unitario >= 0", name="costo_unitario_no_negativo"),
    )

    id_producto: Mapped[int] = primary_key()
    id_restaurante: Mapped[int] = reference("restaurante.id_restaurante")
    nombre: Mapped[str] = mapped_column(Text)
    precio: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    activo: Mapped[bool] = mapped_column(Boolean)

    restaurante: Mapped["Restaurante"] = relationship(back_populates="productos")
    receta: Mapped[list["RecetaDetalle"]] = relationship(back_populates="producto")
    detalles_pedido: Mapped[list["DetallePedido"]] = relationship(back_populates="producto")
    predicciones: Mapped[list["PrediccionDemanda"]] = relationship(back_populates="producto")


class Insumo(Base):
    __tablename__ = "insumo"
    __table_args__ = (CheckConstraint("costo_unitario >= 0", name="costo_unitario_no_negativo"),)

    id_insumo: Mapped[int] = primary_key()
    id_restaurante: Mapped[int] = reference("restaurante.id_restaurante")
    nombre: Mapped[str] = mapped_column(Text)
    unidad: Mapped[str] = mapped_column(Text)
    # El stock negativo debe poder registrarse para detectar la anomalía de HU-09.
    stock_actual: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    restaurante: Mapped["Restaurante"] = relationship(back_populates="insumos")
    recetas: Mapped[list["RecetaDetalle"]] = relationship(back_populates="insumo")
    movimientos: Mapped[list["MovimientoStock"]] = relationship(back_populates="insumo")


class RecetaDetalle(Base):
    __tablename__ = "receta_detalle"
    __table_args__ = (CheckConstraint("cantidad > 0", name="cantidad_positiva"),)

    id_producto: Mapped[int] = mapped_column(
        ForeignKey("producto.id_producto", ondelete="RESTRICT", onupdate="RESTRICT"), primary_key=True,
    )
    id_insumo: Mapped[int] = mapped_column(
        ForeignKey("insumo.id_insumo", ondelete="RESTRICT", onupdate="RESTRICT"), primary_key=True, index=True,
    )
    cantidad: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    unidad: Mapped[str] = mapped_column(Text)

    producto: Mapped["Producto"] = relationship(back_populates="receta")
    insumo: Mapped["Insumo"] = relationship(back_populates="recetas")


class Pedido(Base):
    __tablename__ = "pedido"
    __table_args__ = (
        CheckConstraint("importe_total >= 0", name="importe_total_no_negativo"),
        CheckConstraint("costo_total >= 0", name="costo_total_no_negativo"),
        CheckConstraint("distancia_km >= 0", name="distancia_no_negativa"),
        CheckConstraint("puntaje_prioridad >= 0", name="puntaje_no_negativo"),
    )

    id_pedido: Mapped[int] = primary_key()
    id_restaurante: Mapped[int] = reference("restaurante.id_restaurante")
    id_cliente: Mapped[int] = reference("cliente.id_cliente")
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    estado: Mapped[str] = mapped_column(Text)
    direccion_entrega: Mapped[str] = mapped_column(Text)
    referencia_local: Mapped[str | None] = mapped_column(Text)
    medio_pago: Mapped[str] = mapped_column(Text)
    estado_pago: Mapped[str] = mapped_column(Text)
    importe_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    puntaje_prioridad: Mapped[Decimal | None] = mapped_column(Numeric)
    factores_prioridad: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    zona_entrega: Mapped[str | None] = mapped_column(Text)
    distancia_km: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    costo_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    restaurante: Mapped["Restaurante"] = relationship(back_populates="pedidos")
    cliente: Mapped["Cliente"] = relationship(back_populates="pedidos")
    detalles: Mapped[list["DetallePedido"]] = relationship(back_populates="pedido")
    historial: Mapped[list["HistorialPedido"]] = relationship(back_populates="pedido")
    entrega: Mapped["Entrega | None"] = relationship(back_populates="pedido")
    movimientos: Mapped[list["MovimientoStock"]] = relationship(back_populates="pedido")


class DetallePedido(Base):
    __tablename__ = "detalle_pedido"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="cantidad_positiva"),
        CheckConstraint("precio_unitario >= 0", name="precio_unitario_no_negativo"),
    )

    id_detalle: Mapped[int] = primary_key()
    id_pedido: Mapped[int] = reference("pedido.id_pedido")
    id_producto: Mapped[int] = reference("producto.id_producto")
    cantidad: Mapped[int] = mapped_column(Integer)
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    pedido: Mapped["Pedido"] = relationship(back_populates="detalles")
    producto: Mapped["Producto"] = relationship(back_populates="detalles_pedido")


class Repartidor(Base):
    __tablename__ = "repartidor"

    id_repartidor: Mapped[int] = primary_key()
    id_usuario: Mapped[int] = reference("usuario.id_usuario", unique=True)
    zona: Mapped[str | None] = mapped_column(Text)
    estado_disponibilidad: Mapped[str] = mapped_column(Text)

    usuario: Mapped["Usuario"] = relationship(back_populates="repartidor")
    historial: Mapped[list["HistorialRepartidor"]] = relationship(back_populates="repartidor")
    entregas: Mapped[list["Entrega"]] = relationship(back_populates="repartidor")


class HistorialRepartidor(Base):
    __tablename__ = "historial_repartidor"

    id_historial_disp: Mapped[int] = primary_key()
    id_repartidor: Mapped[int] = reference("repartidor.id_repartidor")
    estado: Mapped[str] = mapped_column(Text)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    repartidor: Mapped["Repartidor"] = relationship(back_populates="historial")


class Entrega(Base):
    __tablename__ = "entrega"
    __table_args__ = (CheckConstraint("costo_repartidor >= 0", name="costo_repartidor_no_negativo"),)

    id_entrega: Mapped[int] = primary_key()
    id_pedido: Mapped[int] = reference("pedido.id_pedido", unique=True)
    id_repartidor: Mapped[int] = reference("repartidor.id_repartidor")
    fecha_asignacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    estado: Mapped[str] = mapped_column(Text)
    costo_repartidor: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    pedido: Mapped["Pedido"] = relationship(back_populates="entrega")
    repartidor: Mapped["Repartidor"] = relationship(back_populates="entregas")


class HistorialPedido(Base):
    __tablename__ = "historial_pedido"

    id_historial: Mapped[int] = primary_key()
    id_pedido: Mapped[int] = reference("pedido.id_pedido")
    id_usuario: Mapped[int] = reference("usuario.id_usuario")
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    tipo_evento: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(Text)
    detalle: Mapped[str | None] = mapped_column(Text)

    pedido: Mapped["Pedido"] = relationship(back_populates="historial")
    usuario: Mapped["Usuario"] = relationship(back_populates="eventos_pedido")


class MovimientoStock(Base):
    __tablename__ = "movimiento_stock"

    id_movimiento: Mapped[int] = primary_key()
    id_insumo: Mapped[int] = reference("insumo.id_insumo")
    id_pedido: Mapped[int | None] = reference("pedido.id_pedido", nullable=True)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    tipo: Mapped[str] = mapped_column(Text)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    motivo: Mapped[str | None] = mapped_column(Text)

    insumo: Mapped["Insumo"] = relationship(back_populates="movimientos")
    pedido: Mapped["Pedido | None"] = relationship(back_populates="movimientos")


class PrediccionDemanda(Base):
    __tablename__ = "prediccion_demanda"
    __table_args__ = (
        CheckConstraint("periodo_fin >= periodo_inicio", name="periodo_valido"),
        CheckConstraint("demanda_estimada >= 0", name="demanda_no_negativa"),
    )

    id_prediccion: Mapped[int] = primary_key()
    id_producto: Mapped[int] = reference("producto.id_producto")
    periodo_inicio: Mapped[date] = mapped_column(Date)
    periodo_fin: Mapped[date] = mapped_column(Date)
    demanda_estimada: Mapped[Decimal] = mapped_column(Numeric)
    modelo: Mapped[str] = mapped_column(Text)
    nombre_metrica: Mapped[str | None] = mapped_column(Text)
    valor_metrica: Mapped[Decimal | None] = mapped_column(Numeric)
    generada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    producto: Mapped["Producto"] = relationship(back_populates="predicciones")


class Alerta(Base):
    __tablename__ = "alerta"

    id_alerta: Mapped[int] = primary_key()
    id_restaurante: Mapped[int] = reference("restaurante.id_restaurante")
    tipo: Mapped[str] = mapped_column(Text)
    descripcion: Mapped[str] = mapped_column(Text)
    valor_observado: Mapped[Decimal] = mapped_column(Numeric)
    valor_referencia: Mapped[Decimal] = mapped_column(Numeric)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    estado: Mapped[str] = mapped_column(Text)

    restaurante: Mapped["Restaurante"] = relationship(back_populates="alertas")
