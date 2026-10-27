"""HU-02: gestión interna; no publica costos, insumos o recetas a clientes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select

from app.auth.dependencies import DB, require_restaurant
from app.db.models import Insumo, Producto, Usuario
from app.menu.schemas import IngredientOutput, ProductInput, ProductOutput, RecipeInput, RecipeOutput
from app.menu.service import create_product, product_in_restaurant, recipe_output, save_recipe, update_product

router = APIRouter(prefix="/restaurantes/{id_restaurante}", tags=["Menú y recetas"])
RestaurantId = Annotated[int, Path(gt=0)]
ProductId = Annotated[int, Path(gt=0)]
MenuUser = Annotated[Usuario, Depends(require_restaurant("personal", "propietario"))]


@router.get("/productos", response_model=list[ProductOutput])
def products(id_restaurante: RestaurantId, db: DB, user: MenuUser):
    return db.scalars(select(Producto).where(Producto.id_restaurante == id_restaurante)
                      .order_by(Producto.nombre, Producto.id_producto)).all()


@router.post("/productos", response_model=ProductOutput, status_code=201)
def add_product(id_restaurante: RestaurantId, data: ProductInput, db: DB, user: MenuUser):
    return create_product(db, id_restaurante, data)


@router.put("/productos/{id_producto}", response_model=ProductOutput)
def edit_product(id_restaurante: RestaurantId, id_producto: ProductId, data: ProductInput, db: DB, user: MenuUser):
    return update_product(db, id_restaurante, id_producto, data)


@router.get("/insumos", response_model=list[IngredientOutput])
def ingredients(id_restaurante: RestaurantId, db: DB, user: MenuUser):
    return db.scalars(select(Insumo).where(Insumo.id_restaurante == id_restaurante)
                      .order_by(Insumo.nombre, Insumo.id_insumo)).all()


@router.get("/productos/{id_producto}/receta", response_model=RecipeOutput)
def read_recipe(id_restaurante: RestaurantId, id_producto: ProductId, db: DB, user: MenuUser):
    product_in_restaurant(db, id_restaurante, id_producto)
    return recipe_output(db, id_restaurante, id_producto)


@router.put("/productos/{id_producto}/receta", response_model=RecipeOutput)
def edit_recipe(id_restaurante: RestaurantId, id_producto: ProductId, data: RecipeInput, db: DB, user: MenuUser):
    return save_recipe(db, id_restaurante, id_producto, data)
