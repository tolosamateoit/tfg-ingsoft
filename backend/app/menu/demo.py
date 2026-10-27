"""SQL offline de catálogo SINTÉTICO para un restaurante existente. Nunca conecta."""

import argparse
from pathlib import Path


def demo_catalog_sql(restaurant_id: int) -> str:
    if isinstance(restaurant_id, bool) or not isinstance(restaurant_id, int) or not 1 <= restaurant_id <= 2147483647:
        raise ValueError("Indicá un ID de restaurante válido.")
    return f"""-- HU-02: CATÁLOGO SINTÉTICO. Revisar restaurante de destino antes de ejecutar.
-- No es una migración ni se ejecuta automáticamente. No sobrescribe registros.
BEGIN;
DO $demo_menu$
DECLARE harina integer; queso integer; salsa integer; pizza integer; pan integer;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.restaurante WHERE id_restaurante={restaurant_id}) THEN
        RAISE EXCEPTION 'El restaurante de destino no existe';
    END IF;
    IF EXISTS (SELECT 1 FROM public.insumo WHERE id_restaurante={restaurant_id} AND nombre LIKE '[HU02 SINTETICO]%')
       OR EXISTS (SELECT 1 FROM public.producto WHERE id_restaurante={restaurant_id} AND nombre LIKE '[HU02 SINTETICO]%') THEN
        RAISE EXCEPTION 'El catálogo sintético HU-02 ya existe; no se sobrescribió';
    END IF;
    INSERT INTO public.insumo (id_restaurante,nombre,unidad,stock_actual,costo_unitario)
        VALUES ({restaurant_id},'[HU02 SINTETICO] Harina','kg',20,1000) RETURNING id_insumo INTO harina;
    INSERT INTO public.insumo (id_restaurante,nombre,unidad,stock_actual,costo_unitario)
        VALUES ({restaurant_id},'[HU02 SINTETICO] Queso','kg',10,3000) RETURNING id_insumo INTO queso;
    INSERT INTO public.insumo (id_restaurante,nombre,unidad,stock_actual,costo_unitario)
        VALUES ({restaurant_id},'[HU02 SINTETICO] Salsa','kg',5,1500) RETURNING id_insumo INTO salsa;
    INSERT INTO public.producto (id_restaurante,nombre,precio,costo_unitario,activo)
        VALUES ({restaurant_id},'[HU02 SINTETICO] Pizza',6500,620,true) RETURNING id_producto INTO pizza;
    INSERT INTO public.producto (id_restaurante,nombre,precio,costo_unitario,activo)
        VALUES ({restaurant_id},'[HU02 SINTETICO] Pan de pizza',3000,195,true) RETURNING id_producto INTO pan;
    INSERT INTO public.receta_detalle (id_producto,id_insumo,cantidad,unidad) VALUES
        (pizza,harina,0.2,'kg'),(pizza,queso,0.1,'kg'),(pizza,salsa,0.08,'kg'),
        (pan,harina,0.15,'kg'),(pan,salsa,0.03,'kg');
END;
$demo_menu$;
COMMIT;
"""


def main():
    parser = argparse.ArgumentParser(description="Generar SQL de catálogo sintético HU-02, sin conexión a base de datos.")
    parser.add_argument("--restaurant-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        sql = demo_catalog_sql(args.restaurant_id)
    except ValueError as error:
        parser.error(str(error))
    try:
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(sql)
    except FileExistsError:
        parser.error("El archivo ya existe; elegí otra ruta para no sobrescribirlo.")
    print("SQL de catálogo sintético generado. No se ejecutaron escrituras en la base de datos.")


if __name__ == "__main__":
    main()
