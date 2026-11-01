"""Auditoría reproducible de fase 3; los resultados se calculan con los servicios reales.

Desde backend/: python -m app.analytics.experiment run --execute
Auditoría offline posterior: python -m app.analytics.experiment audit RUTA_JSON
No importa el generador de operaciones ni modifica el historial.
"""

import argparse
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
from importlib.metadata import version
import json
from math import ceil
from pathlib import Path
import platform
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.forecast import generate_forecast, utc_today
from app.analytics.metrics import metrics, observations
from app.analytics.schemas import PeriodInput
from app.orders.operational_date import OPERATIONAL_ZONE, operational_day_bounds
from app.auth.service import as_utc
from app.db.engine import build_engine
from app.db.models import Pedido, Usuario
from app.demo_history.storage import (DEFAULT_OUTPUT, ROOT, backup_scope, find_restaurant,
                                     outside_fingerprint, preflight, scope)
from app.demo_history.plan import digest
from app.logistics.priority import ACTIVE, calculate
from app.logistics.service import ranked_couriers

PERIOD = PeriodInput(inicio=date(2026, 10, 1), fin=date(2026, 10, 30))


def check(condition, message):
    if not condition:
        raise ValueError(message)


def linear_fit(values):
    """Mínimos cuadrados independientes, con aritmética decimal y x=0..n-1."""
    n = Decimal(len(values))
    check(n >= 2, "La auditoría requiere al menos dos días de entrenamiento.")
    xs = [Decimal(i) for i in range(len(values))]
    ys = [Decimal(y) for y in values]
    sx, sy = sum(xs), sum(ys)
    slope = (n * sum(x * y for x, y in zip(xs, ys)) - sx * sy) / (n * sum(x * x for x in xs) - sx * sx)
    return slope, (sy - slope * sx) / n


def linear_audit(values):
    days = len(values)
    validation_days = max(2, ceil(days * .2))
    split = days - validation_days
    slope, intercept = linear_fit(values[:split])
    validation = [max(Decimal(0), intercept + slope * day) for day in range(split, days)]
    mae = sum(abs(Decimal(value) - estimated) for value, estimated in zip(values[split:], validation)) / validation_days
    final_slope, final_intercept = linear_fit(values)
    future = [max(Decimal(0), final_intercept + final_slope * day) for day in range(days, days + 7)]
    return dict(training_days=split, validation_days=validation_days, mae=mae,
                validation_predictions=validation, validation_actual=values[split:], future_daily=future,
                forecast_total=sum(future), final_slope=final_slope, zero_days=values.count(0))


def mean_audit(values):
    """Auditoría independiente Decimal; índices módulo 7 equivalen a días de semana."""
    n = len(values)
    check(n >= 35, "Se requieren 35 días para auditar promedios.")
    def estimates(end, offsets, weekly):
        return [sum(Decimal(values[i]) for i in range(end) if not weekly or i % 7 == j % 7)
                / sum(1 for i in range(end) if not weekly or i % 7 == j % 7) for j in offsets]
    scores = [sum(abs(Decimal(values[i]) - p) for i, p in zip(range(n - 14, n - 7),
              estimates(n - 14, range(n - 14, n - 7), weekly))) / 7 for weekly in (False, True)]
    weekly = scores[1] < scores[0]
    validation = estimates(n - 7, range(n - 7, n), weekly)
    future = [p.quantize(Decimal('.000001')) for p in estimates(n, range(n, n + 7), weekly)]
    return dict(training_days=n - 7, validation_days=7,
                mae=sum(abs(Decimal(v) - p) for v, p in zip(values[-7:], validation)) / 7,
                validation_predictions=validation, validation_actual=values[-7:], future_daily=future,
                forecast_total=sum(future), zero_days=values.count(0))


def forecast_audit(own, forecast, today):
    if forecast.fecha_operativa is not None:
        today = forecast.fecha_operativa
        cutoff = operational_day_bounds(today)[1]
        calendar = lambda value: as_utc(value).astimezone(OPERATIONAL_ZONE).date()
        end = today
        future_start = today + timedelta(days=1)
    else:  # Compatibilidad con evidencias de la regresión anterior.
        cutoff = datetime.combine(today, datetime.min.time(), UTC)
        calendar = lambda value: as_utc(value).date()
        end = today - timedelta(days=1)
        future_start = today
    orders = {row["id_pedido"]: row for row in own["pedido"] if row["estado"] == "Entregado"
              and as_utc(row["fecha_hora"]) < cutoff}
    start = min(calendar(row["fecha_hora"]) for row in orders.values())
    days = (end - start).days + 1
    products = {row["id_producto"]: row for row in own["producto"] if row["activo"]}
    sales = defaultdict(lambda: [0] * days)
    for row in own["detalle_pedido"]:
        if row["id_pedido"] in orders and row["id_producto"] in products:
            day = (calendar(orders[row["id_pedido"]]["fecha_hora"]) - start).days
            sales[row["id_producto"]][day] += row["cantidad"]
    result = []
    check(len(forecast.predicciones) == len(sales), "El número de productos pronosticados no coincide con las ventas.")
    for predicted in forecast.predicciones:
        values = sales[predicted.id_producto]
        audit = mean_audit(values) if forecast.fecha_operativa is not None else linear_audit(values)
        check(abs(predicted.valor_metrica - audit["mae"]) <= Decimal(".000001"), "El MAE no coincide con la auditoría independiente.")
        check(abs(predicted.demanda_estimada - audit["forecast_total"]) <= Decimal(".000001"), "La predicción no coincide con el cálculo independiente.")
        first = sum(values[:30]); last = sum(values[-30:])
        audit["independent_mae"] = audit.pop("mae")
        result.append(dict(product_id=predicted.id_producto, product=predicted.producto,
            prediction_id=predicted.id_prediccion, daily_sales=values, forecast=predicted.demanda_estimada,
            mae=predicted.valor_metrica, first_30_units=first, last_30_units=last,
            last_7_units=sum(values[-7:]), **audit))
    return dict(start=start, end=end, days=days,
        completed_orders=len(orders), training_end=start + timedelta(days=result[0]["training_days"] - 1),
        validation_start=start + timedelta(days=result[0]["training_days"]),
        forecast_start=future_start, forecast_end=future_start + timedelta(days=6), products=result,
        omitted=[dict(product_id=id, product=row["nombre"], reason="Sin ventas entregadas; no se inventa una serie de demanda.")
                 for id, row in products.items() if id not in sales])


def stock_audit(own, forecast):
    expected = defaultdict(Decimal)
    predicted = {row.id_producto: row.demanda_estimada for row in forecast.predicciones}
    for recipe in own["receta_detalle"]:
        if recipe["id_producto"] in predicted:
            expected[recipe["id_insumo"]] += predicted[recipe["id_producto"]] * recipe["cantidad"]
    returned = {row.id_insumo: row for row in forecast.insumos}
    ledger = defaultdict(Decimal)
    for row in own["movimiento_stock"]:
        ledger[row["id_insumo"]] += row["cantidad"]
    result = []
    for ingredient in own["insumo"]:
        id = ingredient["id_insumo"]
        check(ingredient["stock_actual"] == ledger[id], "El stock de Supabase no coincide con los movimientos.")
        required = expected[id].quantize(Decimal(".000001"), rounding=ROUND_CEILING) if id in expected else None
        shortage = max(Decimal(0), required - ingredient["stock_actual"]) if required is not None else None
        if id in expected:
            check(id in returned and returned[id].cantidad_necesaria == required and returned[id].faltante == shortage,
                  "Las necesidades de insumos no coinciden con las recetas persistidas.")
            check(returned[id].stock_actual == ingredient["stock_actual"], "El motor usó otro stock.")
        else:
            check(id not in returned, "Se inventó una necesidad sin pronóstico de producto.")
        result.append(dict(ingredient_id=id, ingredient=ingredient["nombre"], unit=ingredient["unidad"],
                           stock=ingredient["stock_actual"], required=required, shortage=shortage))
    return result


def alert_audit(db, rid, own, calculated):
    start = datetime.combine(calculated.inicio, datetime.min.time(), UTC)
    end = datetime.combine(calculated.fin + timedelta(days=1), datetime.min.time(), UTC)
    reference_start = datetime.combine(calculated.referencia_inicio, datetime.min.time(), UTC)
    samples = observations(db, rid, reference_start, end)
    alerts = own["alerta"]
    by_key = {row["descripcion"].partition(" | ")[0]: row for row in alerts}
    check(len(by_key) == len(alerts), "Existen alertas duplicadas para una misma observación.")
    rows, summaries = [], []
    for kind, observations_ in samples.items():
        reference = [row[1] for row in observations_ if row[2] < start]
        current = [row for row in observations_ if row[2] >= start]
        mean = sum(reference, Decimal(0)) / len(reference) if reference else None
        current_mean = sum((row[1] for row in current), Decimal(0)) / len(current) if current else None
        check(mean == calculated.promedios_referencia[kind] and current_mean == calculated.promedios[kind], "Los promedios no coinciden con las observaciones temporales.")
        threshold = mean * Decimal("1.10") if mean is not None else None
        detected = 0
        for identity, value, timestamp, label in current:
            key = f"HU09:{kind}:{identity}"
            actual = by_key.get(key)
            expected = threshold is not None and value > threshold
            check(bool(actual and actual["estado"] == "Activa") == expected, "Una alerta no coincide con la regla estricta del 10 %.")
            if expected:
                check(actual["valor_observado"] == value and actual["valor_referencia"] == threshold, "Valor o umbral de alerta incorrecto.")
                detected += 1
            rows.append(dict(kind=kind, identity=identity, value=value, threshold=threshold, timestamp=timestamp,
                             detected=expected, alert_id=actual["id_alerta"] if actual else None, label=label))
        summaries.append(dict(kind=kind, reference_mean=mean, current_mean=current_mean, threshold=threshold,
                              reference_n=len(reference), current_n=len(current), detected=detected))
    negative = [row for row in own["insumo"] if row["stock_actual"] < 0]
    for ingredient in own["insumo"]:
        key = f"HU09:stock:insumo:{ingredient['id_insumo']}"
        actual = by_key.get(key)
        check(bool(actual and actual["estado"] == "Activa") == (ingredient["stock_actual"] < 0), "Alerta de stock negativo incoherente.")
    # Reconocer los casos plantados desde su historial persistido, sin volver a generarlos.
    order_lookup = {row["id_pedido"]: row for row in own["pedido"]}
    event_to_order = {row["id_historial"]: row["id_pedido"] for row in own["historial_pedido"]}
    by_order = defaultdict(list)
    for row in rows:
        prefix, id = row["identity"].split(":")
        oid = int(id) if prefix == "pedido" else event_to_order[int(id)]
        by_order[oid, row["kind"]].append(row)
    cases = []
    markers = {"preparacion_lenta": "preparacion", "entrega_lenta": "entrega", "importe_alto": "importe"}
    for event in own["historial_pedido"]:
        if event["tipo_evento"] != "registro":
            continue
        for marker, kind in markers.items():
            if marker not in (event["detalle"] or ""):
                continue
            oid = event["id_pedido"]
            observed = by_order.get((oid, kind), [])
            if observed:
                entry = max(observed, key=lambda row: row["value"])
                reason = "Supera el umbral." if entry["detected"] else "El valor no supera el umbral de referencia."
                cases.append(dict(order_id=oid, case=marker, state=order_lookup[oid]["estado"], value=entry["value"],
                    threshold=entry["threshold"], detected=entry["detected"], alert_id=entry["alert_id"], reason=reason))
            else:
                reason = "Entrega no completada: el indicador solo mide En camino → Entregado." if kind == "entrega" and order_lookup[oid]["estado"] == "No entregado" else "No hay observación finalizada dentro del período UTC seleccionado."
                cases.append(dict(order_id=oid, case=marker, state=order_lookup[oid]["estado"], value=None,
                                  threshold=calculated.promedios_referencia[kind] * Decimal("1.10"), detected=False, alert_id=None, reason=reason))
    counts = dict(Counter(row["tipo"] for row in alerts if row["estado"] == "Activa"))
    return dict(summaries=summaries, observations=rows, cases=cases, stored_active_by_type=counts,
                stored_total=len(alerts), visible_count=len(calculated.alertas), stock_negative=negative,
                no_unexpected_alerts=sum(summary["detected"] for summary in summaries) + len(negative) == len(alerts))


def prospective_logistics(db, own, timestamp):
    """Copias en memoria: no persiste prioridades ni modifica repartidores reales."""
    result = []
    for row in own["pedido"]:
        if row["estado"] not in ACTIVE:
            continue
        order = Pedido(**{name: row[name] for name in ("id_pedido", "fecha_hora", "distancia_km", "importe_total", "costo_total")})
        calculate(order, timestamp)
        result.append(dict(order_id=order.id_pedido, state=row["estado"], created=as_utc(row["fecha_hora"]),
                           distance=row["distancia_km"], factors=order.factores_prioridad, priority=order.puntaje_prioridad))
    result.sort(key=lambda row: (-row["priority"], row["created"], row["order_id"]))
    # La consulta real de candidatos no cambia estados ni realiza asignaciones.
    available = ranked_couriers(db, 3)
    return dict(calculated_at=timestamp, orders=result, available_couriers=len(available),
                ready_orders=sum(row["state"] == "Listo" for row in result), persisted=False)


def run_experiment(engine, output_dir, backup_dir=DEFAULT_OUTPUT):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    target = output_dir / f"fase3-{stamp}.json"
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                preflight(db)
                from app.orders.service import lock_order_relations
                lock_order_relations(db)
                check(find_restaurant(db) == 3, "El restaurante 3 no coincide con la identidad histórica reservada.")
                before = scope(db, 3)
                check((len(before["pedido"]), len(before["producto"]), len(before["insumo"]), len(before["movimiento_stock"])) == (2407, 8, 15, 12416), "El tamaño del historial difiere del conjunto aprobado.")
                before_business = {name: rows for name, rows in before.items() if name not in {"prediccion_demanda", "alerta"}}
                business_hash = digest(before_business)
                outside_hash = outside_fingerprint(db, before)
                backup = backup_scope(db, 3, backup_dir)
                today = utc_today(db)
                started = as_utc(db.scalar(select(func.now())))
                forecast = generate_forecast(db, 3)
                audited_forecast = forecast_audit(before, forecast, today)
                audited_stock = stock_audit(before, forecast)
                owner = db.scalar(select(Usuario).where(Usuario.id_restaurante == 3, Usuario.rol == "propietario"))
                indicators = metrics(db, owner, 3, PERIOD)
                first = scope(db, 3)
                first_alerts = first["alerta"]
                indicators_again = metrics(db, owner, 3, PERIOD)
                after = scope(db, 3)
                check(digest(first_alerts) == digest(after["alerta"]), "El segundo control modificó o duplicó alertas con entradas iguales.")
                audited_alerts = alert_audit(db, 3, after, indicators_again)
                check(audited_alerts["no_unexpected_alerts"], "Existen alertas fuera del conjunto de observaciones evaluadas.")
                logistics = prospective_logistics(db, before, started)
                after_business = {name: rows for name, rows in after.items() if name not in {"prediccion_demanda", "alerta"}}
                check(digest(after_business) == business_hash, "Se alteraron entradas históricas; se revierte la evaluación.")
                check(outside_fingerprint(db, after) == outside_hash, "Cambió información externa; se revierte la evaluación.")
                report = dict(experiment="Oliva fase 3", restaurant_id=3, source="Supabase PostgreSQL; historial sintético",
                    executed_at=started, data_start="2026-08-02", data_end="2026-10-30", business_sha256=business_hash,
                    outside_sha256=outside_hash, history_unchanged=True, outside_unchanged=True,
                    dataset_counts={name: len(rows) for name, rows in before.items() if not name.startswith("auth_")},
                    previous_predictions=len(before["prediccion_demanda"]), previous_alerts=len(before["alerta"]),
                    forecast=forecast.model_dump(mode="json"), forecast_audit=audited_forecast, stock=audited_stock,
                    indicators=indicators.model_dump(mode="json"), alert_audit=audited_alerts,
                    deduplication=dict(first_count=len(first_alerts), second_count=len(after["alerta"]), duplicate_keys=0, identical_ids_and_values=True),
                    logistics=logistics, backup_file=str(backup),
                    versions={"python": platform.python_version(), **{package: version(package) for package in ("scikit-learn", "SQLAlchemy", "psycopg")}},
                    source_sha256={name: sha256((ROOT / "backend/app" / name).read_bytes()).hexdigest() for name in
                        ("analytics/forecast.py", "analytics/metrics.py", "analytics/experiment.py", "logistics/priority.py", "logistics/service.py")})
            transaction.commit()
        except BaseException:
            transaction.rollback()
            raise
    target.write_text(json.dumps(report, default=lambda value: str(value), ensure_ascii=False, indent=2), encoding="utf-8")
    return target, report


def audit_saved(path):
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    for row in report["forecast_audit"]["products"]:
        audited = (mean_audit if report.get('forecast', {}).get('fecha_operativa') else linear_audit)(row["daily_sales"])
        check(abs(audited["mae"] - Decimal(row["mae"])) <= Decimal(".000001"), "MAE inválido en evidencia guardada.")
        check(abs(audited["forecast_total"] - Decimal(row["forecast"])) <= Decimal(".000001"), "Predicción inválida en evidencia guardada.")
    return {"products_checked": len(report["forecast_audit"]["products"]), "mode": "auditoría offline; sin conexión ni escrituras"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    run = commands.add_parser("run")
    run.add_argument("--execute", action="store_true")
    run.add_argument("--output-dir", type=Path, default=ROOT / "docs/experimentos")
    audit = commands.add_parser("audit")
    audit.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.action == "audit":
        print(json.dumps(audit_saved(args.path), ensure_ascii=False))
        return
    if not args.execute:
        parser.error("La ejecución persiste predicciones/alertas del restaurante 3; requiere --execute.")
    engine = build_engine()
    try:
        path, report = run_experiment(engine, args.output_dir)
        print(json.dumps(dict(evidence_file=str(path), predictions=len(report["forecast"]["predicciones"]),
            alerts=report["alert_audit"]["stored_active_by_type"], deduplication=report["deduplication"],
            history_unchanged=report["history_unchanged"]), ensure_ascii=False, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
