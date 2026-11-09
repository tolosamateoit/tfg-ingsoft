import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const { QueryClient, QueryClientProvider } = createRequire(import.meta.url)('@tanstack/react-query');
const root = fileURLToPath(new URL('../', import.meta.url));
const backend = fileURLToPath(new URL('../../backend/', import.meta.url));
const python = fileURLToPath(new URL('../../backend/.venv/Scripts/python.exe', import.meta.url));
const bundled = await build({ stdin: { contents: "export { PriorityDetails } from './src/app/PriorityBoard'; export { pagesFor } from './src/app/navigation'; export { default as Couriers } from './src/app/Couriers';", resolveDir: root },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react/jsx-runtime', '@tanstack/react-query'], logLevel: 'silent' });
const module = { exports: {} };
vm.runInNewContext(bundled.outputFiles[0].text, { module, exports: module.exports, require: createRequire(import.meta.url) });
const { PriorityDetails, pagesFor, Couriers } = module.exports;
const source = `
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from sqlalchemy.orm import Session
from tests.menu_support import sqlite_menu_engine
from tests.test_logistics import add_order
from app.logistics.priority import priority_preview
from app.db.models import Pedido, HistorialPedido
from app.orders.distance import PENDING_DISTANCE
engine = sqlite_menu_engine()
now = datetime(2026,11,1,12,tzinfo=UTC)
with Session(engine) as db:
    first=db.get(Pedido,1)
    first.fecha_hora=now-timedelta(minutes=5)
    first.importe_total,first.costo_total,first.distancia_km=2000,1000,2
    second=add_order(db,estado='Nuevo',fecha_hora=now-timedelta(minutes=10),distancia_km=4,importe_total=3000,costo_total=1000)
    db.add(HistorialPedido(id_pedido=1,id_usuario=1,tipo_evento='registro',estado='Nuevo',detalle=PENDING_DISTANCE,fecha_hora=now))
    db.commit()
    with patch('app.logistics.priority.priority_time',return_value=now):
        print(priority_preview(db,1).model_dump_json())
engine.dispose()
`;
const data = JSON.parse(execFileSync(python, ['-c', source], { cwd: backend, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }));
const render = (page = data) => renderToStaticMarkup(React.createElement(PriorityDetails, { page }));

test('ranking muestra posiciones consecutivas del backend y datos del pedido sin formulas', () => {
  const html = render();
  assert.match(html, /Prioridad<\/span><strong>1<\/strong>/);
  assert.match(html, /Prioridad<\/span><strong>2<\/strong>/);
  assert.ok(html.indexOf('Pedido #4') < html.indexOf('Pedido #1'));
  assert.match(html, /Pizza sintética/);
  assert.match(html, /Se priorizó principalmente por su tiempo de espera/);
  assert.doesNotMatch(html, /P =|T:|G:|puntaje|normalizaci/);
});

test('desglose usa la distancia registrada sin pedir confirmacion', () => {
  const html = render();
  for (const factor of data.pedidos[0].factores) assert.ok(html.includes(`width:${factor.barra}%`));
  assert.match(html, /<details class="priority-breakdown">/);
  assert.match(html, /max="10"/);
  assert.doesNotMatch(html, /Confirmá la distancia|Distancia sin confirmar|Sin confirmar/);
  assert.match(html, /Distancia no disponible/);
  assert.match(html, /4,00 km registrados/);
  assert.doesNotMatch(html, />0(?:,00)? km registrados/);
  assert.ok(html.indexOf('Tiempo de espera') < html.indexOf('Cercanía'));
});

test('cambios del ranking actualizan posiciones mostradas y el caso vacio es claro', () => {
  const changed = { ...data, pedidos: [...data.pedidos].reverse().map((r, i) => ({...r,posicion:i+1})) };
  assert.ok(render(changed).indexOf('Pedido #1') < render(changed).indexOf('Pedido #4'));
  assert.match(render({ ...data,pedidos:[] }), /No hay pedidos nuevos esperando/);
});

test('personal accede al analisis y el alta de repartidor queda para propietario', () => {
  const staff = {rol:'personal',id_restaurante:1};
  const paths = pagesFor(staff).map((p) => p.path);
  for (const path of ['pedidos','catalogo','stock','repartidores']) assert.ok(paths.includes(path));
  assert.ok(!paths.includes('entregas'));
  for (const path of ['demanda','indicadores']) assert.ok(paths.includes(path));
  const ownerPaths = pagesFor({...staff,rol:'propietario'}).map((p) => p.path);
  assert.ok(ownerPaths.includes('demanda') && ownerPaths.includes('indicadores'));
  const staffHtml = renderToStaticMarkup(React.createElement(QueryClientProvider,{client:new QueryClient()},React.createElement(Couriers,{restaurant:1,owner:false,onSessionExpired:()=>{}})));
  const ownerHtml = renderToStaticMarkup(React.createElement(QueryClientProvider,{client:new QueryClient()},React.createElement(Couriers,{restaurant:1,owner:true,onSessionExpired:()=>{}})));
  assert.doesNotMatch(staffHtml, /Incorporar repartidor|Guardar tarifas/);
  assert.match(ownerHtml, /Incorporar repartidor/);
});
