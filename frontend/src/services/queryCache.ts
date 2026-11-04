import { QueryClient } from '@tanstack/react-query';

// Solo memoria de esta pestaña. Ningún dato operativo se persiste en el navegador.
export const queryClient = new QueryClient({ defaultOptions: { queries: {
  retry: false, gcTime: 30 * 60_000, refetchOnWindowFocus: true,
} } });
let generation = 0;
let scope = 'anonymous';
export const cacheScope = () => scope;
export function clearQuerySession() {
  scope = `anonymous:${++generation}`;
  queryClient.clear();
}
export function startQuerySession(user: {id_usuario:number; id_restaurante:number|null; rol:string}) {
  clearQuerySession();
  scope = `${generation}:${user.id_usuario}:${user.id_restaurante}:${user.rol}`;
}
export const apiKey = (path: string) => [scope, 'api', path] as const;
export function freshness(path: string) {
  if (/\/(productos|insumos|stock|movimientos-stock|tarifas)(\/|\?|$)/.test(path)) return Infinity;
  if (path.includes('/predicciones/')) return 5 * 60_000;
  if (/\/(indicadores|alertas)(\?|$)/.test(path)) return 0;
  return 30_000;
}
export function apiOptions<T>(path: string, read: (signal:AbortSignal)=>Promise<T>) {
  return { queryKey: apiKey(path), queryFn: ({signal}:{signal:AbortSignal}) => read(signal), staleTime: freshness(path) };
}
export function ensureApiQuery<T>(path:string, read:(signal:AbortSignal)=>Promise<T>) {
  return queryClient.fetchQuery(apiOptions(path, read));
}

export function affectedByMutation(changed: string, cached: string) {
  const restaurant = changed.match(/^restaurantes\/(\d+)\//)?.[1];
  const cachedRestaurant = cached.match(/^restaurantes\/(\d+)\//)?.[1];
  if (restaurant && cachedRestaurant && restaurant !== cachedRestaurant) return false;
  const order = changed.match(/(?:^|\/)pedidos\/(\d+)(?:\/|$)/)?.[1];
  const cachedOrder = cached.match(/(?:^|\/)pedidos\/(\d+)(?:\/|$)/)?.[1];
  if (order && cachedOrder && order !== cachedOrder) return false;
  if (changed.endsWith('/distancia'))
    return /(^|\/)(pedidos|entregas|prioridades)(\/|\?|$)/.test(cached);
  const catalog = /\/(productos|insumos)(\/|$)/.test(changed);
  if (catalog) return /^(pedidos|entregas)(\/|\?|$)/.test(cached) || /\/(productos|insumos|stock|movimientos-stock|menu|predicciones|indicadores|alertas|pedidos|prioridades)(\/|\?|$)/.test(cached);
  if (/(^|\/)(pedidos|entregas)(\/|$)/.test(changed))
    return /^(pedidos|entregas|repartidores)(\/|\?|$)/.test(cached) || /\/(pedidos|prioridades|repartidores|stock|insumos|movimientos-stock|predicciones|indicadores|alertas)(\/|\?|$)/.test(cached);
  if (/\/(repartidores|tarifas)(\/|$)/.test(changed) || changed.startsWith('repartidores/'))
    return /^(pedidos|entregas|repartidores)(\/|\?|$)/.test(cached) || /\/(repartidores|pedidos|tarifas|indicadores|alertas)(\/|\?|$)/.test(cached);
  return cached === changed;
}
export async function invalidateMutation(path: string, requestScope: string) {
  if (requestScope !== scope) return;
  await queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] === requestScope
    && query.queryKey[1] === 'api' && affectedByMutation(path, String(query.queryKey[2])) }, {cancelRefetch:false, throwOnError:true});
}

// Se llama únicamente después de recibir una respuesta exitosa del servidor.
// Cancelar lecturas anteriores impide que sobrescriban la versión confirmada.
export async function confirmMutation(path: string, requestScope: string, result: unknown) {
  if (requestScope !== scope) return;
  await queryClient.cancelQueries({ predicate: query => query.queryKey[0] === requestScope
    && query.queryKey[1] === 'api' && affectedByMutation(path, String(query.queryKey[2])) });
  if (requestScope !== scope) return;
  let confirmedPath: string | undefined;
  if (result && typeof result === 'object' && 'id_pedido' in result) {
    if (path.endsWith('/preparacion') && 'version' in result && 'historial' in result) confirmedPath = path;
    else if ('estado_pedido' in result && 'historial' in result) confirmedPath = `pedidos/${result.id_pedido}/seguimiento`;
    else if ('detalles' in result) confirmedPath = `pedidos/${result.id_pedido}`;
  }
  if (confirmedPath) queryClient.setQueryData(apiKey(confirmedPath), result);
  // Las consultas conservan su estado de error y los datos visibles si falla la actualización.
  void queryClient.invalidateQueries({ predicate: query => query.queryKey[0] === requestScope
    && query.queryKey[1] === 'api' && query.queryKey[2] !== confirmedPath
    && affectedByMutation(path, String(query.queryKey[2])) }).catch(() => {});
}
