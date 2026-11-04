import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const {QueryClientProvider} = require('@tanstack/react-query');
const root = fileURLToPath(new URL('../', import.meta.url));
const bundle = await build({stdin:{contents:`
  export {CustomerProductCard} from './src/app/Orders';
  export {default as Preparation} from './src/app/Preparation';
  export {default as DeliveryTracking} from './src/app/DeliveryTracking';
  export {default as MenuManager} from './src/app/MenuManager';
  export {queryClient,apiKey} from './src/services/queryCache';`, resolveDir:root},
  bundle:true, write:false, platform:'node', format:'cjs', jsx:'automatic',
  external:['react','react/jsx-runtime','@tanstack/react-query'], logLevel:'silent'});
const module = {exports:{}};
vm.runInNewContext(bundle.outputFiles[0].text, {module, exports:module.exports, require, setTimeout, clearTimeout});
const {CustomerProductCard, Preparation, DeliveryTracking, MenuManager, queryClient, apiKey} = module.exports;
after(() => queryClient.clear());
const render = (component, props) => renderToStaticMarkup(React.createElement(QueryClientProvider,
  {client:queryClient}, React.createElement(component, props)));
const noop = () => {};

test('el menú del cliente muestra y bloquea productos sin stock', () => {
  const product = {id_producto:1, nombre:'Bebida', precio:'10', disponible_stock:false};
  const unavailable = render(CustomerProductCard, {product, busy:false, quantity:0, onAdd:noop});
  assert.match(unavailable, /No disponible/);
  assert.match(unavailable, /<button disabled=""/);
  const available = render(CustomerProductCard, {product:{...product, disponible_stock:true}, busy:false, quantity:0, onAdd:noop});
  assert.doesNotMatch(available, /No disponible|disabled=""/);
});

test('menú interno distingue el estado administrativo de la disponibilidad', () => {
  queryClient.setQueryData(apiKey('restaurantes/1/productos'), [
    {id_producto:1, id_restaurante:1, nombre:'Pizza', precio:'10', costo_unitario:'4', activo:true, disponible_stock:false, descripcion:null, imagen_url:null},
    {id_producto:2, id_restaurante:1, nombre:'Bebida', precio:'10', costo_unitario:'4', activo:false, disponible_stock:true, descripcion:null, imagen_url:null},
  ]);
  queryClient.setQueryData(apiKey('restaurantes/1/insumos'), []);
  const html = render(MenuManager, {restaurant:1, onSessionExpired:noop});
  assert.match(html, /product-state--unavailable">No disponible/);
  assert.match(html, /Inactivo/);
});

test('preparación presenta saldos y seguimiento oculta explicaciones técnicas', () => {
  queryClient.setQueryData(apiKey('restaurantes/1/pedidos/4/preparacion'), {estado:'Listo', version:1, historial:[], movimientos:[
    {id_movimiento:1, id_insumo:1, nombre:'Papas', unidad:'kg', cantidad:'-1', stock_antes:'2', stock_despues:'1', fecha_hora:'2026-11-04T12:00:00Z', motivo:'Preparación #42: Cambio técnico'},
  ]});
  const prep = render(Preparation, {restaurant:1, order:4, onSessionExpired:noop, onChanged:noop});
  assert.match(prep, /Papas: 2 kg antes → 1 kg después/);
  assert.doesNotMatch(prep, /Stock actual|Preparación #42/);
  queryClient.setQueryData(apiKey('pedidos/4/seguimiento'), {estado_pedido:'Asignado', entrega:{id_entrega:9, estado:'Asignado', repartidor:'Ana Martínez'}, historial:[
    {id_historial:1, fecha_hora:'2026-11-04T12:00:00Z', usuario:'Equipo', estado:'Asignado', detalle:'Repartidor asignado: Ana Martínez (#8). Elegido por tasa de éxito.'},
  ]});
  const tracking = render(DeliveryTracking, {order:4, onSessionExpired:noop});
  assert.match(tracking, /Repartidor asignado: Ana Martínez/);
  assert.doesNotMatch(tracking, /#8|tasa de éxito|Entrega #9/);
});
