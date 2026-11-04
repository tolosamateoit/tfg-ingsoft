import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const root=fileURLToPath(new URL('../',import.meta.url));
const backend=fileURLToPath(new URL('../../backend/',import.meta.url));
const python=fileURLToPath(new URL('../../backend/.venv/Scripts/python.exe',import.meta.url));
const bundle=await build({stdin:{contents:"export {DailyOrderCard,DailyOrdersView} from './src/app/DailyOrders'; export {OrderTable} from './src/app/OrderListing'; export {pagesFor,canonicalPath} from './src/app/navigation';",resolveDir:root},
  bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
const module={exports:{}};
vm.runInNewContext(bundle.outputFiles[0].text,{module,exports:module.exports,require:createRequire(import.meta.url)});
const {DailyOrderCard,DailyOrdersView,OrderTable,pagesFor,canonicalPath}=module.exports;
const source=`
import sys,json
sys.stdout.reconfigure(encoding='utf-8')
from sqlalchemy.orm import Session
from tests.test_daily_orders import DailyOperationTests, STAMP
from tests.test_logistics import add_order
from app.db.models import Entrega,HistorialPedido
from app.orders.distance import PENDING_DISTANCE
case=DailyOperationTests()
case.setUp()
try:
    with Session(case.engine) as db:
        db.add(HistorialPedido(id_pedido=1,id_usuario=1,tipo_evento='registro',estado='Nuevo',fecha_hora=STAMP,detalle=PENDING_DISTANCE))
        for state in ('En preparación','Listo','Entregado','Cancelado'):
            add_order(db,estado=state,fecha_hora=STAMP)
        route=add_order(db,estado='Asignado',fecha_hora=STAMP)
        db.add(Entrega(id_pedido=route.id_pedido,id_repartidor=1,fecha_asignacion=STAMP,estado='Asignado',costo_repartidor=0))
        db.commit()
    print(json.dumps({'day':case.day(),'history':case.client.get('/api/pedidos?periodo=historial').json()},ensure_ascii=True))
finally:
    case.doCleanups()
`;
const data=JSON.parse(execFileSync(python,['-c',source],{cwd:backend,encoding:'utf8',stdio:['pipe','pipe','pipe']}));
const no=()=>{};
const actions={onOpen:no,onState:no,onReject:no,onAssign:no,onDelivery:no,onPage:no};
const card=(row,busy=false)=>renderToStaticMarkup(React.createElement(DailyOrderCard,{row,couriers:data.day.repartidores,busy,...actions}));

test('Pedidos es la entrada por defecto y las rutas viejas redirigen sin aparecer en el menu',()=>{
  for(const rol of ['propietario','personal']) {
    const paths=pagesFor({rol,id_restaurante:2}).map(p=>p.path);
    assert.equal(paths[0],'pedidos');
    assert.ok(!paths.includes('resumen')&&!paths.includes('prioridades'));
    assert.equal(paths.includes('indicadores'),rol==='propietario');
  }
  assert.equal(canonicalPath('resumen'),'pedidos');
  assert.equal(canonicalPath('prioridades'),'pedidos');
  assert.equal(canonicalPath('stock'),'stock');
});

test('el dia muestra tarjetas agrupadas y prioridades consecutivas del backend',()=>{
  const html=renderToStaticMarkup(React.createElement(DailyOrdersView,{data:data.day,busy:false,...actions}));
  assert.match(html,/31\/10\/2026/);
  assert.doesNotMatch(html,/<table/);
  assert.equal((html.match(/¿Por qué esta prioridad\?/g)||[]).length,data.day.activos.length + data.day.listos.length);
  assert.equal((html.match(/class="daily-order-rank"/g)||[]).length,data.day.activos.length + data.day.listos.length);
  assert.match(html,/Listos para entregar/);
  assert.match(html,/En reparto/);
  assert.match(html,/Finalizados y rechazados/);
  assert.match(html,/Prioridad <strong>1/);
  assert.match(html,/Prioridad <strong>2/);
});

test('cada estado muestra solo sus acciones validas y no inventa distancia pendiente',()=>{
  const fresh=data.day.activos.find(r=>r.estado==='Nuevo');
  const preparing=data.day.activos.find(r=>r.estado==='En preparación');
  assert.match(card(fresh),/Confirmar pedido/); assert.match(card(fresh),/Rechazar/);
  assert.doesNotMatch(card(fresh),/Marcar como listo|Enviar a entrega|0 km registrados/);
  assert.match(card(fresh),/Distancia no disponible/);
  assert.match(card(preparing),/Marcar como listo/); assert.doesNotMatch(card(preparing),/Confirmar pedido|Rechazar/);
  assert.match(card(data.day.listos[0]),/Enviar a entrega/);
  assert.match(card(data.day.listos[0]),/Elegí un repartidor/);
  assert.match(card(data.day.listos[0]),/¿Por qué esta prioridad/);
  assert.match(card(data.day.en_entrega[0]),/Iniciar entrega/);
  assert.doesNotMatch(card(data.day.finalizados[0]),/Confirmar pedido|Rechazar|Enviar a entrega|Prioridad/);
  assert.match(card(fresh,true),/disabled=""/);
});

test('historial conserva tabla, detalle y orden del backend sin rankings',()=>{
  const html=renderToStaticMarkup(React.createElement(OrderTable,{page:data.history,restaurant:1,onOpen:no}));
  assert.match(html,/<table/);
  assert.match(html,/Ver detalle/);
  assert.doesNotMatch(html,/Prioridad|Confirmar pedido|Marcar como listo/);
  const rows=data.history.pedidos;
  for(let i=1;i<rows.length;i++) assert.ok(html.indexOf(`#${rows[i-1].id_pedido}<`) < html.indexOf(`#${rows[i].id_pedido}<`));
});
