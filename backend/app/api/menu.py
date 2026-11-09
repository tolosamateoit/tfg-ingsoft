"""HU-02: gestión interna; no publica costos, insumos o recetas a clientes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select

from app.auth.dependencies import DB, require_restaurant
from app.db.models import Insumo, MovimientoStock, Producto, Usuario
from app.menu.inventory import IngredientInput, MovementInput, record_movement, save_ingredient, deactivate_ingredient
from app.menu.schemas import IngredientOutput, ProductInput, ProductOutput, RecipeInput, RecipeOutput
from app.menu.service import create_product, product_in_restaurant, recipe_output, save_recipe, update_product
from app.menu.availability import product_availability, missing_ingredients

router = APIRouter(prefix="/restaurantes/{id_restaurante}", tags=["Menú y recetas"])
RestaurantId = Annotated[int, Path(gt=0)]
ProductId = Annotated[int, Path(gt=0)]
MenuUser = Annotated[Usuario, Depends(require_restaurant("personal", "propietario"))]
Owner = Annotated[Usuario, Depends(require_restaurant("propietario"))]


@router.get("/productos", response_model=list[ProductOutput])
def products(id_restaurante: RestaurantId, db: DB, user: MenuUser):
    rows = db.scalars(select(Producto).where(Producto.id_restaurante == id_restaurante)
                      .order_by(Producto.nombre, Producto.id_producto)).all()
    available = product_availability(db, id_restaurante)
    missing = missing_ingredients(db, id_restaurante)
    return [ProductOutput.model_validate(row).model_copy(update={'disponible_stock': available.get(row.id_producto, False), 'insumos_faltantes': missing.get(row.id_producto, [])}) for row in rows]


@router.post("/productos", response_model=ProductOutput, status_code=201)
def add_product(id_restaurante: RestaurantId, data: ProductInput, db: DB, user: Owner):
    return create_product(db, id_restaurante, data)


@router.put("/productos/{id_producto}", response_model=ProductOutput)
def edit_product(id_restaurante: RestaurantId, id_producto: ProductId, data: ProductInput, db: DB, user: Owner):
    return update_product(db, id_restaurante, id_producto, data, allow_activation=user.rol == "propietario")


@router.get("/insumos", response_model=list[IngredientOutput])
def ingredients(id_restaurante: RestaurantId, db: DB, user: MenuUser):
    return db.scalars(select(Insumo).where(Insumo.id_restaurante == id_restaurante, Insumo.activo.is_(True))
                      .order_by(Insumo.nombre, Insumo.id_insumo)).all()


@router.post("/insumos", response_model=IngredientOutput, status_code=201)
def add_ingredient(id_restaurante: RestaurantId, data: IngredientInput, db: DB, user: MenuUser):
    return save_ingredient(db, id_restaurante, data)


@router.put("/insumos/{id_insumo}", response_model=IngredientOutput)
def edit_ingredient(id_restaurante: RestaurantId, id_insumo: ProductId, data: IngredientInput, db: DB, user: MenuUser):
    return save_ingredient(db, id_restaurante, data, id_insumo)


@router.post("/insumos/{id_insumo}/movimientos", response_model=IngredientOutput, status_code=201)
def add_movement(id_restaurante: RestaurantId, id_insumo: ProductId, data: MovementInput, db: DB, user: MenuUser):
    return record_movement(db, id_restaurante, id_insumo, data, user.id_usuario)


@router.get("/movimientos-stock")
def movements(id_restaurante: RestaurantId, db: DB, user: MenuUser,
              offset: Annotated[int, Query(ge=0)] = 0):
    return [dict(row) for row in db.execute(select(
        MovimientoStock.id_movimiento, MovimientoStock.id_insumo, Insumo.nombre, Insumo.unidad,
        MovimientoStock.id_pedido, MovimientoStock.fecha_hora, MovimientoStock.tipo,
        MovimientoStock.cantidad, MovimientoStock.motivo,
    ).join(Insumo).where(Insumo.id_restaurante == id_restaurante)
      .order_by(MovimientoStock.fecha_hora.desc(), MovimientoStock.id_movimiento.desc())
      .offset(offset).limit(30)).mappings()]


@router.get("/productos/{id_producto}/receta", response_model=RecipeOutput)
def read_recipe(id_restaurante: RestaurantId, id_producto: ProductId, db: DB, user: MenuUser):
    product_in_restaurant(db, id_restaurante, id_producto)
    return recipe_output(db, id_restaurante, id_producto)


@router.put("/productos/{id_producto}/receta", response_model=RecipeOutput)
def edit_recipe(id_restaurante: RestaurantId, id_producto: ProductId, data: RecipeInput, db: DB, user: Owner):
    return save_recipe(db, id_restaurante, id_producto, data)


@router.delete("/insumos/{id_insumo}", response_model=IngredientOutput)
def remove_ingredient(id_restaurante: RestaurantId, id_insumo: ProductId, db: DB, user: Owner):
    return deactivate_ingredient(db, id_restaurante, id_insumo)


@router.delete("/productos/{id_producto}", response_model=ProductOutput)
def remove_product(id_restaurante: RestaurantId, id_producto: ProductId, db: DB, user: Owner):
    from app.menu.service import lock_recipe_relations
    lock_recipe_relations(db)
    product = product_in_restaurant(db, id_restaurante, id_producto, lock=True)
    product.activo = False
    db.commit()
    return product
