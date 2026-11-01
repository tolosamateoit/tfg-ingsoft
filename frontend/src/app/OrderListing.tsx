import { useApiQuery } from '../services/useApiQuery';
import { useState } from 'react';
import { formatCalendarDate, formatDateTime } from '../services/format';
import { formatMoney } from '../services/menu';
import { orderRequest, type OrderPage } from '../services/orders';
import { displayText, Status } from './ui';
import WarningBadge from './WarningBadge';
import DailyOrders from './DailyOrders';

type Props = { restaurant: number | null; refresh: number; deliveries?: boolean;
  onOpen: (id: number) => void; onSessionExpired: () => void };

export function OrderTable({page,restaurant,deliveries=false,onOpen}: Pick<Props,'restaurant'|'deliveries'|'onOpen'> & {page:OrderPage}) {
  return <div className="table-wrap">
        <table className="data-table"><thead><tr><th>Número</th><th>Fecha y hora</th><th>Resumen del pedido</th>
          <th>Importe</th><th>Estado del pedido</th><th>Repartidor</th>{deliveries && <th>Entrega</th>}<th>Detalle</th></tr></thead>
          <tbody>{page.pedidos.map((row) => <tr key={row.id_pedido}>
            <td>#{row.id_pedido}<WarningBadge message={row.advertencia_importe}/></td><td>{formatDateTime(row.fecha_hora)}</td>
            <td>{row.resumen_productos || 'Sin productos registrados'}{restaurant === null && <p className="muted">{displayText(row.restaurante)}</p>}</td>
            <td>{formatMoney(row.importe_total)}</td><td><Status value={row.estado}/></td>
            <td>{row.repartidor ? displayText(row.repartidor) : 'Sin asignar'}</td>
            {deliveries && <td>{row.id_entrega !== null ? <>#{row.id_entrega} · {row.estado_entrega}<WarningBadge message={row.advertencia_entrega}/></> : 'Sin asignar'}</td>}
            <td><button onClick={() => onOpen(row.id_pedido)}>{deliveries ? 'Ver seguimiento' : 'Ver detalle'} #{row.id_pedido}</button></td>
          </tr>)}</tbody>
        </table>
      </div>;
}

/** Una fuente y los mismos filtros para Pedidos y Entregas del restaurante. */
export default function OrderListing({ restaurant, refresh, deliveries = false, onOpen, onSessionExpired }: Props) {
  const [period, setPeriod] = useState<'dia' | 'historial'>(restaurant === null ? 'historial' : 'dia');
  const [offset, setOffset] = useState(0);
  const operational = restaurant !== null && !deliveries && period === 'dia';
  const path = `pedidos?periodo=${period}&limit=20&offset=${offset}`;
  const query = useApiQuery<OrderPage>(path, (signal) => orderRequest(path, undefined, signal), onSessionExpired,
    {enabled:!operational});
  const page = query.data;
  const error = query.error?.message;
  const loading = query.isPending;
  return <section aria-label={deliveries ? 'Pedidos y entregas asociadas' : 'Listado de pedidos'}>
    {restaurant !== null && <div className="tabs" role="tablist" aria-label="Período de pedidos">
      <button role="tab" aria-selected={period === 'dia'} onClick={() => { setPeriod('dia'); setOffset(0); }}>Pedidos del día</button>
      <button role="tab" aria-selected={period === 'historial'} onClick={() => { setPeriod('historial'); setOffset(0); }}>Historial de pedidos</button>
    </div>}
    {operational ? <DailyOrders restaurant={restaurant} refresh={refresh} onOpen={onOpen} onSessionExpired={onSessionExpired}/> : <>
    <h3>{period === 'dia' ? 'Pedidos del día' : 'Historial de pedidos'}</h3>
    {error && <p role="alert" className="auth-error">{error}</p>}
    {loading && <p role="status">Cargando pedidos…</p>}
    {!loading && page && <>
      {restaurant !== null && <p>Fecha operativa: {page.fecha_operativa ? formatCalendarDate(page.fecha_operativa) : 'Sin pedidos registrados'}.</p>}
      <p>{page.total} pedido(s){period === 'dia' ? ' en la fecha operativa' : ' en el historial'}.</p>
      {deliveries && <p>Se muestran los mismos pedidos que en Pedidos para este período, con su entrega asociada o sin asignar.</p>}
      {!page.pedidos.length ? <p>No hay pedidos para este período.</p> : <OrderTable page={page} restaurant={restaurant} deliveries={deliveries} onOpen={onOpen}/>}
      <div className="menu-actions" aria-label="Paginación de pedidos">
        <button disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - page.limit))}>Página anterior</button>
        <span>Página {page.total ? Math.floor(page.offset / page.limit) + 1 : 0} de {Math.ceil(page.total / page.limit)}</span>
        <button disabled={loading || offset + page.limit >= page.total} onClick={() => setOffset(offset + page.limit)}>Página siguiente</button>
      </div>
    </>}
    </>}
  </section>;
}
