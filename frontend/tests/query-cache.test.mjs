import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { QueryObserver } from '@tanstack/react-query';

const root = fileURLToPath(new URL('../', import.meta.url));
const bundled = await build({stdin:{contents:"export * from './src/services/queryCache'; export {operationRequest} from './src/services/operations'; export {orderRequest} from './src/services/orders'; export {updateProduct, saveRecipe} from './src/services/menu';",resolveDir:root},
  bundle:true,write:false,platform:'node',format:'cjs',packages:'external',logLevel:'silent'});
const module = {exports:{}};
new Function('require','module','exports',bundled.outputFiles[0].text)(createRequire(import.meta.url),module,module.exports);
const {queryClient:client,apiKey,apiOptions,ensureApiQuery,startQuerySession,clearQuerySession,cacheScope,invalidateMutation,affectedByMutation} = module.exports;
client.setDefaultOptions({queries:{...client.getDefaultOptions().queries,gcTime:Infinity}});
const owner = {id_usuario:1,id_restaurante:2,rol:'propietario'};
test.beforeEach(() => startQuerySession(owner));
test.afterEach(() => clearQuerySession());
const deferred = () => { let resolve,reject; const promise=new Promise((a,b)=>{resolve=a;reject=b;}); return {promise,resolve,reject}; };

test('carga progresiva: no consulta antes de visitar y comparte solicitudes simultaneas', async () => {
  let calls=0; const pending=deferred();
  const path='restaurantes/2/productos';
  const options=apiOptions(path,()=>{calls++;return pending.promise;});
  assert.equal(calls,0);
  const first=client.fetchQuery(options), second=client.fetchQuery(options);
  assert.equal(calls,1);
  pending.resolve([{id:1}]);
  assert.deepEqual(await first,await second);
  await ensureApiQuery(path,()=>{calls++;return [];});
  assert.equal(calls,1);
});

test('volver a una seccion fresca entrega datos sin carga ni nueva consulta', async () => {
  let calls=0;
  const options=apiOptions('restaurantes/2/insumos',async()=>{calls++;return [{stock:10}];});
  await client.fetchQuery(options);
  const observer=new QueryObserver(client,options);
  const result=observer.getOptimisticResult(options);
  assert.equal(result.isPending,false);
  assert.deepEqual(result.data,[{stock:10}]);
  const stop=observer.subscribe(()=>{});
  assert.equal(calls,1);
  stop();
});

test('indicadores se actualizan en segundo plano manteniendo los datos visibles incluso ante errores', async () => {
  const path='restaurantes/2/indicadores';
  client.setQueryData(apiKey(path),{ventas:12});
  const pending=deferred(); let calls=0;
  const options=apiOptions(path,()=>{calls++;return pending.promise;});
  const observer=new QueryObserver(client,options);
  const stop=observer.subscribe(()=>{});
  assert.equal(observer.getCurrentResult().isFetching,true);
  assert.equal(observer.getCurrentResult().isPending,false);
  assert.deepEqual(observer.getCurrentResult().data,{ventas:12});
  const inFlight=client.fetchQuery(options);
  assert.equal(calls,1);
  pending.reject(new Error('Sin conexion'));
  await assert.rejects(inFlight,/Sin conexion/);
  assert.deepEqual(client.getQueryData(apiKey(path)),{ventas:12});
  assert.equal(client.getQueryState(apiKey(path)).status,'error');
  await client.fetchQuery(apiOptions(path,async()=>({ventas:15})));
  assert.deepEqual(client.getQueryData(apiKey(path)),{ventas:15});
  stop();
});

test('paginas, filtros, fechas y restaurantes tienen entradas independientes', async () => {
  const paths=['pedidos?periodo=historial&offset=0','pedidos?periodo=historial&offset=20',
    'restaurantes/2/alertas?tipo=stock','restaurantes/2/alertas?tipo=entrega',
    'restaurantes/2/predicciones/diaria?fecha=2026-11-01','restaurantes/2/predicciones/diaria?fecha=2026-11-02',
    'restaurantes/3/predicciones/diaria?fecha=2026-11-01'];
  for(const path of paths) await ensureApiQuery(path,async()=>({path}));
  for(const path of paths) assert.deepEqual(client.getQueryData(apiKey(path)),{path});
  assert.equal(client.getQueryCache().getAll().length,paths.length);
});

test('confirmar o entregar invalida ranking, historial, stock, repartidores e indicadores sin precargar otras pantallas', async () => {
  let reads=0;
  const active='restaurantes/2/pedidos/operacion?offset=0';
  const options=apiOptions(active,async()=>({version:++reads}));
  await client.fetchQuery(options);
  const observer=new QueryObserver(client,options); const stop=observer.subscribe(()=>{});
  const related=['pedidos?periodo=historial&offset=20','entregas?offset=0','repartidores/me/resumen-diario',
    'restaurantes/2/insumos','restaurantes/2/stock','restaurantes/2/prioridades','restaurantes/2/indicadores',
    'restaurantes/2/predicciones/diaria?fecha=2026-11-02'];
  for(const path of related) client.setQueryData(apiKey(path),{version:1});
  const before=client.getQueryCache().getAll().length;
  await invalidateMutation('entregas/7/estado',cacheScope());
  assert.equal(reads,2);
  for(const path of related) assert.equal(client.getQueryState(apiKey(path)).isInvalidated,true,path);
  assert.equal(client.getQueryCache().getAll().length,before);
  assert.deepEqual(client.getQueryData(apiKey(active)),{version:2});
  stop();
});

test('matriz de invalidacion cubre catalogo, recetas, movimientos, asignaciones y tarifas', () => {
  const cases=[
    ['restaurantes/2/productos/8','pedidos?periodo=historial'],
    ['restaurantes/2/productos/8/receta','restaurantes/2/predicciones/diaria?fecha=2026-11-02'],
    ['restaurantes/2/insumos/5/movimientos','restaurantes/2/movimientos-stock?offset=30'],
    ['restaurantes/2/entregas/asignar','restaurantes/2/repartidores'],
    ['restaurantes/2/repartidores/3','restaurantes/2/pedidos/operacion?offset=0'],
    ['restaurantes/2/tarifas','pedidos/9'],
  ];
  for(const [change,path] of cases) assert.equal(affectedByMutation(change,path),true,`${change} -> ${path}`);
  assert.equal(affectedByMutation('entregas/7/estado','restaurantes/2/productos'),false);
});

test('cerrar sesion o cambiar usuario/restaurante elimina datos y cancela respuestas tardias', async () => {
  const path='restaurantes/2/productos';
  const pending=deferred(); const oldScope=cacheScope(); let aborted=false;
  const work=ensureApiQuery(path,async signal=>{signal.addEventListener('abort',()=>{aborted=true;}); return pending.promise;});
  const settled=work.catch(()=>{});
  client.setQueryData(apiKey('pedidos?offset=0'),{private:true});
  startQuerySession({...owner,id_usuario:4,id_restaurante:3});
  assert.equal(aborted,true);
  assert.notEqual(cacheScope(),oldScope);
  assert.equal(client.getQueryCache().getAll().length,0);
  pending.resolve({old:true}); await settled;
  assert.equal(client.getQueryData(apiKey(path)),undefined);
  client.setQueryData(apiKey(path),{new:true});
  await invalidateMutation('restaurantes/2/productos',oldScope);
  assert.equal(client.getQueryState(apiKey(path)).isInvalidated,false);
  clearQuerySession();
  assert.equal(client.getQueryCache().getAll().length,0);
});

test('los servicios HTTP invalidan la cache solo despues de mutaciones exitosas y conservan validaciones y CSRF', async (t) => {
  const {operationRequest,orderRequest,updateProduct,saveRecipe}=module.exports;
  const savedWindow=globalThis.window;
  globalThis.window={sessionStorage:{getItem:()=>null,setItem:()=>{}},addEventListener:()=>{}};
  let status=200; const requests=[];
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    requests.push({url,options});
    return new Response(JSON.stringify(status===200 ? {ok:true} : {detail:'Version desactualizada'}),{status});
  });
  try {
    const path='pedidos?periodo=historial&offset=20';
    const actions=[
      ()=>operationRequest('restaurantes/2/pedidos/1/preparacion',{estado:'Listo',version:2}),
      ()=>operationRequest('restaurantes/2/entregas/asignar',undefined,undefined,'POST'),
      ()=>operationRequest('entregas/1/estado',{estado:'Entregado'}),
      ()=>orderRequest('restaurantes/2/pedidos',{direccion_entrega:'Prueba',detalles:[]}),
      ()=>updateProduct(2,1,{nombre:'Producto de prueba'}),
      ()=>saveRecipe(2,1,[]),
    ];
    for(const action of actions) {
      client.setQueryData(apiKey(path),{version:1});
      await action();
      assert.equal(client.getQueryState(apiKey(path)).isInvalidated,true);
    }
    for(const {options} of requests) {
      assert.equal(options.headers['X-CSRF-Protection'],'1');
      assert.ok(options.headers['X-Oliva-Tab']);
      assert.equal(options.credentials,'same-origin');
    }
    client.setQueryData(apiKey(path),{version:1}); status=409;
    await assert.rejects(actions[0],error=>error.status===409 && error.message==='Version desactualizada');
    assert.equal(client.getQueryState(apiKey(path)).isInvalidated,false);
  } finally { if(savedWindow===undefined) delete globalThis.window; else globalThis.window=savedWindow; }
});
