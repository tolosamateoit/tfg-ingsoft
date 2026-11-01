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
const bundled = await build({ stdin: { contents: "export { OperationalDetails } from './src/app/OperationalAnalytics'; export { default as WarningBadge } from './src/app/WarningBadge';", resolveDir: root },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react/jsx-runtime'], logLevel: 'silent' });
const module = { exports: {} };
vm.runInNewContext(bundled.outputFiles[0].text, { module, exports: module.exports, require: createRequire(import.meta.url) });
const { OperationalDetails, WarningBadge } = module.exports;
const source = `
import sys
sys.stdout.reconfigure(encoding='utf-8')
from sqlalchemy.orm import Session
from datetime import timedelta
from tests.menu_support import sqlite_menu_engine
from tests.test_analytics import historical_orders
from tests.test_operational_analytics import delivery, DAY
from app.analytics.operational import operational_dashboard
from app.db.models import Insumo, Pedido, RecetaDetalle, Usuario
engine = sqlite_menu_engine()
with Session(engine) as db:
    ids = historical_orders(db, days=42, count=84)
    db.get(Pedido, ids[-1]).importe_total = 10000
    db.get(Insumo, 1).stock_actual = 1
    db.add(RecetaDetalle(id_producto=1, id_insumo=1, cantidad=.2, unidad='kg'))
    for i in range(10):
        delivery(db, DAY - timedelta(days=i+1))
    delivery(db, DAY, 58)
    db.commit()
    print(operational_dashboard(db, db.get(Usuario, 7), 1).model_dump_json())
engine.dispose()
`;
const data = JSON.parse(execFileSync(python, ['-c', source], { cwd: backend, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }));
const render = (value = data) => renderToStaticMarkup(React.createElement(OperationalDetails, { data: value }));

test('dashboard React presenta indicadores reales, siete dias y top sin tecnicismos', () => {
  const html = render();
  assert.match(html, /Tu día, de un vistazo/);
  assert.match(html, /max="2026-10-26"/);
  assert.match(html, /value="2026-10-26"/);
  assert.match(html, /Pedidos del día/);
  assert.match(html, /Ventas del día/);
  assert.match(html, /Ticket promedio/);
  assert.match(html, /58 min/);
  assert.equal((html.match(/class="operational-day"/g) || []).length, 7);
  assert.match(html, /Pizza sintética/);
  assert.doesNotMatch(html, /MAE|percentil|desviación|fórmula|entrenamiento|umbral|RIC/);
});

test('las tres alertas muestran mensajes y valores calculados por backend', () => {
  const html = render();
  for (const type of ['stock', 'entrega', 'importe']) assert.ok(data.alertas.some((a) => a.tipo === type));
  for (const a of data.alertas) assert.ok(html.includes(a.mensaje));
  assert.match(html, /10.000,00/);
  assert.match(html, /30 minutos/);
  assert.match(html, /58 minutos/);
  assert.match(html, /Ver pedido/);
});

test('el icono accesible permite consultar las mismas cifras reales del aviso', () => {
  const message = data.alertas.find((a) => a.tipo === 'importe').mensaje;
  const html = renderToStaticMarkup(React.createElement(WarningBadge, { message }));
  assert.match(html, /<details/);
  assert.match(html, /Consultar advertencia/);
  assert.ok(html.includes(message));
  assert.equal(renderToStaticMarkup(React.createElement(WarningBadge, { message: null })), '');
});

test('sin alertas ni tiempos suficientes no se inventan incidencias', () => {
  const html = render({ ...data, alertas: [], total_alertas: 0, entrega_minutos: null, entregas_con_tiempo: 0 });
  assert.match(html, /Todo en orden/);
  assert.match(html, /Sin datos/);
  assert.doesNotMatch(html, /Una entrega tardó más|Un pedido de importe alto/);
});
