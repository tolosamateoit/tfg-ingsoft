"""python -m app.demo_history plan|check|load|validate; nunca carga al importar."""

import argparse
from datetime import date, datetime
import json
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.engine import build_engine
from app.demo_history.plan import LOCAL, build_plan
from app.demo_history.storage import DEFAULT_OUTPUT, find_restaurant, load_dataset, preflight
from app.demo_history.validation import validate_dataset


def main():
    parser = argparse.ArgumentParser(description="Historial sintético de 90 días en un restaurante independiente.")
    parser.add_argument("action", choices=["plan", "check", "load", "validate"])
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(LOCAL).date())
    parser.add_argument("--seed", type=int, default=20261031)
    parser.add_argument("--execute", action="store_true", help="Confirmación explícita para escribir el dataset.")
    parser.add_argument("--reset", action="store_true", help="Recrear únicamente el historial dedicado, con respaldo.")
    parser.add_argument("--restaurant-id", type=int)
    parser.add_argument("--clear-derived", action="store_true", help="Permitir retirar predicciones/alertas del restaurante dedicado al reiniciar.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.as_of > datetime.now(LOCAL).date():
        parser.error("El período no puede contener días futuros.")
    if args.as_of.year < 2000:
        parser.error("Usá una fecha de corte posterior al año 2000.")
    if (args.reset or args.clear_derived) and args.action != "load":
        parser.error("--reset y --clear-derived solo se usan con load.")
    if args.clear_derived and not args.reset:
        parser.error("--clear-derived requiere --reset.")
    plan = build_plan(args.as_of, args.seed)
    if args.action == "plan" or args.action == "load" and not args.execute:
        print(json.dumps({"mode": "offline; no se abrió ninguna conexión", "seed": args.seed, "as_of": str(args.as_of),
            "start": str(plan["start"]), "end": str(plan["end"]), "orders": len(plan["orders"]),
            "products": len(plan["products"]), "movements": len(plan["movements"]), "states": plan["counts"],
            "fingerprint": plan["fingerprint"]}, ensure_ascii=False, indent=2))
        return 0
    engine = build_engine()
    try:
        if args.action == "load":
            result = load_dataset(engine, plan, reset=args.reset, restaurant_id=args.restaurant_id,
                                  clear_derived=args.clear_derived, output=args.output_dir)
        else:
            with Session(engine) as db:
                db.execute(text("SET TRANSACTION READ ONLY"))
                preflight(db)
                rid = find_restaurant(db)
                if args.restaurant_id is not None and rid != args.restaurant_id:
                    raise ValueError("El ID no coincide con el restaurante dedicado.")
                if args.action == "check":
                    result = {"migration": "0003_producto_presentacion", "restaurant_id": rid,
                              "mode": "solo lectura", "new_restaurant_required": rid is None}
                else:
                    if rid is None:
                        raise ValueError("Todavía no existe el restaurante histórico dedicado.")
                    result = validate_dataset(db, rid, plan)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ValueError as error:
        print(f"Operación rechazada: {error}")
        return 1
    except SQLAlchemyError:
        print("Error de PostgreSQL. La transacción de carga se revirtió; se omitieron los detalles privados de conexión.")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
