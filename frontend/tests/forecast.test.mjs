import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const root = fileURLToPath(new URL('../', import.meta.url));
const backend = fileURLToPath(new URL('../../backend/', import.meta.url));
const python = fileURLToPath(new URL('../../backend/.venv/Scripts/python.exe', import.meta.url));
const result = await build({ stdin: { contents: "export { ForecastDetails } from './src/app/Analytics';", resolveDir: root },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react/jsx-runtime'], logLevel: 'silent' });
const module = { exports: {} };
vm.runInNewContext(result.outputFiles[0].text, { module, exports: module.exports, require: createRequire(import.meta.url) });
const { ForecastDetails } = module.exports;
const source = `
from sqlalchemy.orm import Session
from tests.menu_support import sqlite_menu_engine
from tests.test_analytics import historical_orders
from app.analytics.forecast import day_forecast
from app.db.models import RecetaDetalle, Insumo
engine = sqlite_menu_engine()
with Session(engine) as db:
    historical_orders(db, days=42, count=84)
    db.add(RecetaDetalle(id_producto=1, id_insumo=1, cantidad=.2, unidad='kg'))
    db.get(Insumo, 1).stock_actual = .25
    db.commit()
    print(day_forecast(db, 1).model_dump_json())
engine.dispose()
`;
const data = JSON.parse(execFileSync(python, ['-c', source], { cwd: backend, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }));
const render = (forecast = data, props = {}) => renderToStaticMarkup(React.createElement(ForecastDetails, { forecast, ...props }));

test('React presenta ocho fechas y solo la preparacion y compras del dia calculadas por backend', () => {
  const html = render();
  assert.match(html, /Para el 26\/10\/2026/);
  assert.match(html, /<strong>28<\/strong><span>unidades/);
  assert.match(html, /<strong>2<\/strong><span>pedidos estimados/);
  assert.match(html, /<strong>1<\/strong><span>insumos con faltantes/);
  assert.match(html, /Disponible: 0,25 kg/);
  assert.match(html, /5,35 kg/);
  assert.equal((html.match(/aria-pressed=/g) || []).length, 8);
  assert.equal((html.match(/aria-pressed="true"/g) || []).length, 1);
  assert.match(html, /<span>Lun<\/span><strong>26\/10/);
  assert.match(html, /<span>Lun<\/span><strong>02\/11/);
  assert.doesNotMatch(html, /MAE|lift|frecuencia relativa|observaciones|entrenamiento|algoritmo/);
  assert.equal(data.evaluacion.predicciones[0].nombre_metrica, 'MAE');
});

test('React muestra solo faltantes, cantidades de compra legibles y mensaje de stock suficiente', () => {
  const covered = { ...data, cantidad_faltantes: 0, insumos: data.insumos.map((i) => ({ ...i, faltante: '0' })) };
  const html = render(covered);
  assert.match(html, /stock suficiente/);
  assert.doesNotMatch(html, /Harina/);
  const partial = render({ ...covered, compras_completas: false });
  assert.doesNotMatch(partial, /stock suficiente/);
  assert.match(partial, /Complet/);
});

test('React informa historial insuficiente sin inventar resumen ni precision', () => {
  const empty = { ...data, productos: [], insumos: [], pedidos_estimados: null,
    aviso: 'Todavía no hay suficiente historial para recomendar cuánto preparar.' };
  const html = render(empty);
  assert.match(html, /suficiente historial/);
  assert.doesNotMatch(html, /pedidos estimados|MAE|stock suficiente/);
});

test('al cambiar fecha se ocultan las cifras previas durante la carga', () => {
  const html = render(data, { selectedDate: data.fechas_disponibles[1].fecha, busy: true });
  assert.match(html, /Calculando/);
  assert.doesNotMatch(html, /pedidos estimados|Harina|Pizza/);
  assert.equal((html.match(/aria-pressed="true"/g) || []).length, 1);
});
