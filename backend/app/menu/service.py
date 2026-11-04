"""Pertenencia verificada en las consultas; guardado atómico de la receta."""

from fastapi import HTTPException
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import delete, select, text, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Insumo, Producto, RecetaDetalle
from app.menu.schemas import ProductInput, RecipeInput, RecipeItemOutput, RecipeOutput


def product_in_restaurant(db: Session, restaurant_id: int, product_id: int, *, lock=False) -> Producto:
    query = select(Producto).where(Producto.id_producto == product_id, Producto.id_restaurante == restaurant_id)
    if lock:
        query = query.with_for_update()
    product = db.scalar(query)
    if product is None:
        raise HTTPException(404, "Producto no disponible en este restaurante.")
    return product


def create_product(db: Session, restaurant_id: int, data: ProductInput) -> Producto:
    product = Producto(id_restaurante=restaurant_id, **data.model_dump())
    db.add(product)
    db.commit()
    return product


def update_product(db: Session, restaurant_id: int, product_id: int, data: ProductInput) -> Producto:
    lock_recipe_relations(db)
    product = product_in_restaurant(db, restaurant_id, product_id, lock=True)
    for name, value in data.model_dump().items():
        if name == 'costo_unitario' and db.scalar(select(RecetaDetalle.id_producto).where(RecetaDetalle.id_producto == product_id).limit(1)):
            continue
        setattr(product, name, value)
    refresh_recipe_costs(db, restaurant_id)
    db.commit()
    return product


def recipe_output(db: Session, restaurant_id: int, product_id: int) -> RecipeOutput:
    rows = db.execute(
        select(RecetaDetalle.id_insumo, Insumo.nombre, RecetaDetalle.cantidad, RecetaDetalle.unidad)
        .join(Insumo, Insumo.id_insumo == RecetaDetalle.id_insumo)
        .join(Producto, Producto.id_producto == RecetaDetalle.id_producto)
        .where(RecetaDetalle.id_producto == product_id, Producto.id_restaurante == restaurant_id,
               Insumo.id_restaurante == restaurant_id)
        .order_by(Insumo.nombre, Insumo.id_insumo)
    ).mappings()
    return RecipeOutput(id_producto=product_id, detalles=[RecipeItemOutput(**row) for row in rows])


def lock_recipe_relations(db: Session):
    # Mismo orden que los triggers 0001: lock de relaciones ANTES de locks de filas.
    # Evita interbloqueos con cambios concurrentes de pertenencia de producto/insumo.
    db.execute(text("SELECT pg_advisory_xact_lock(1647042, 1)"))


def save_recipe(db: Session, restaurant_id: int, product_id: int, data: RecipeInput) -> RecipeOutput:
    lock_recipe_relations(db)
    product_in_restaurant(db, restaurant_id, product_id, lock=True)
    ingredient_ids = [item.id_insumo for item in data.detalles]
    ingredients = db.scalars(
        select(Insumo).where(Insumo.id_restaurante == restaurant_id, Insumo.id_insumo.in_(ingredient_ids))
        .order_by(Insumo.id_insumo).with_for_update(read=True)
    ).all() if ingredient_ids else []
    by_id = {ingredient.id_insumo: ingredient for ingredient in ingredients}
    if len(by_id) != len(ingredient_ids):
        raise HTTPException(422, "Todos los insumos deben pertenecer al restaurante autorizado.")
    if any(item.unidad != by_id[item.id_insumo].unidad for item in data.detalles):
        # No hay conversiones de unidades definidas en el prototipo.
        raise HTTPException(422, "Usá la unidad registrada de cada insumo.")
    from app.db.models import DetallePedido, Pedido
    has_pending = db.scalar(select(DetallePedido.id_detalle).join(Pedido).where(
        DetallePedido.id_producto == product_id, Pedido.id_restaurante == restaurant_id,
        Pedido.estado == 'Nuevo').limit(1)) is not None
    if has_pending and not data.detalles:
        raise HTTPException(409, 'Hay pedidos pendientes con este producto; su receta no puede quedar vacía.')
    try:
        db.execute(delete(RecetaDetalle).where(RecetaDetalle.id_producto == product_id))
        db.add_all([RecetaDetalle(id_producto=product_id, **item.model_dump()) for item in data.detalles])
        if not data.detalles:
            product_in_restaurant(db, restaurant_id, product_id).costo_unitario = Decimal(0)
        db.flush()
        if has_pending:
            from app.menu.availability import reserved_ingredients
            reserved = reserved_ingredients(restaurant_id)
            insufficient = db.scalar(select(Insumo.id_insumo).join(reserved, reserved.c.id_insumo == Insumo.id_insumo)
                .where(Insumo.id_restaurante == restaurant_id, Insumo.stock_actual < reserved.c.reservado).limit(1))
            if insufficient:
                raise HTTPException(409, 'La receta requiere más stock del disponible para los pedidos pendientes.')
        refresh_recipe_costs(db, restaurant_id)
        result = recipe_output(db, restaurant_id, product_id)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo guardar la receta. Actualizá los datos y volvé a intentar.") from None


def refresh_recipe_costs(db: Session, restaurant_id: int):
    """Cantidad expresada en la unidad del insumo; envasados admiten equivalencia 1:1."""
    db.flush()
    rows = db.execute(select(Producto, func.sum(RecetaDetalle.cantidad * Insumo.costo_unitario))
        .join(RecetaDetalle).join(Insumo)
        .where(Producto.id_restaurante == restaurant_id, Insumo.id_restaurante == restaurant_id)
        .group_by(Producto.id_producto)).all()
    for product, cost in rows:
        if cost > Decimal('9999999999999999.99'):
            raise HTTPException(422, 'El costo de la receta supera el máximo permitido.')
        product.costo_unitario = cost.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
