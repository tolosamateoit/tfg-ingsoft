import { useApiQuery } from '../services/useApiQuery';
import { useState } from 'react';
import { operationRequest } from '../services/operations';
import { formatCalendarDate, formatMoney } from '../services/format';
import type { OperationalDashboard } from '../services/analytics';
import Orders from './Orders';

type Props = { restaurant: number; onSessionExpired: () => void };
const minutes = (value: string | null) => value === null ? 'Sin datos' : `${Number(value).toLocaleString('es-AR', { maximumFractionDigits: 1 })} min`;
const shortDate = (value: string) => formatCalendarDate(value).slice(0, 5);
const chartAmount = (value: string) => Number(value).toLocaleString('es-AR', { notation: 'compact', maximumFractionDigits: 1 });

export function OperationalDetails({ data, onDate, onOpen }: { data: OperationalDashboard; onDate?: (date: string) => void; onOpen?: (id: number) => void }) {
  return <div className="operational-dashboard">
    <header className="operational-heading"><div><h2>Tu día, de un vistazo</h2><p>Las ventas, las entregas y lo que necesita tu atención.</p></div>
      {data.fecha && <div className="operational-date"><label htmlFor="operational-date">Día a consultar</label>
        <input id="operational-date" type="date" value={data.fecha} min={data.primera_fecha ?? undefined} max={data.fecha_operativa ?? undefined}
          onChange={(event) => { if (event.target.value && event.target.validity.valid) onDate?.(event.target.value); }}/></div>}
    </header>
    {!data.fecha ? <p className="operational-positive">Todavía no hay pedidos registrados para mostrar indicadores.</p> : <>
      <div className="operational-cards">
        <article><span>Pedidos del día</span><strong>{data.pedidos}</strong><small>Todos los estados</small></article>
        <article className="operational-sales"><span>Ventas del día</span><strong>{formatMoney(data.ventas)}</strong><small>{data.pedidos_confirmados} pedidos confirmados</small></article>
        <article><span>Ticket promedio</span><strong>{data.ticket_promedio === null ? 'Sin ventas' : formatMoney(data.ticket_promedio)}</strong><small>Por pedido confirmado</small></article>
        <article><span>Tiempos promedio</span><div className="operational-state-times">{data.tiempos_promedio.map((row) =>
          <div key={row.estado}><span>{row.estado}</span><strong>{minutes(row.minutos)}</strong></div>)}</div></article>
      </div>
      <div className="operational-delivery-note"><span><strong>{data.pedidos_dentro_habitual}</strong> pedidos dentro de lo habitual</span>
        <span className={data.pedidos_con_demora ? 'operational-delayed' : ''}><strong>{data.pedidos_con_demora}</strong> con demoras</span>
        <small>Se cuenta cada pedido con al menos una alerta de demora en la fecha consultada.</small>
      </div>
      <div className="operational-grid">
        <section className="operational-panel"><h3>Ventas confirmadas de los últimos 7 días operativos ($)</h3>
          <div className="operational-chart" aria-label="Importes de pedidos confirmados por día">{data.evolucion.map((day) =>
            <div className="operational-day" key={day.fecha} title={`${formatCalendarDate(day.fecha)}: ${formatMoney(day.ventas)}`}><span className="operational-chart-value">{chartAmount(day.ventas)}</span>
              <div className="operational-bar-track"><div className="operational-bar" style={{ height: `${day.proporcion}%` }}/></div>
              <span>{shortDate(day.fecha)}</span></div>)}</div>
        </section>
        <section className="operational-panel"><h3>Lo más vendido del día</h3>
          {!data.productos.length ? <p className="operational-muted">Todavía no hay pedidos confirmados para este día.</p> :
            <ol className="operational-top">{data.productos.map((row) => <li key={row.id_producto}><span>{row.nombre}</span><strong>{row.cantidad}<small> un.</small></strong></li>)}</ol>}
        </section>
      </div>
      <section className="operational-panel operational-alerts"><div className="operational-alert-heading"><h3>Para prestar atención</h3>
        {data.fecha_stock && <span>Stock previsto: {formatCalendarDate(data.fecha_stock)}</span>}</div>
        {data.aviso_stock && <p className="operational-stock-note">{data.aviso_stock}</p>}
        {!data.alertas.length ? <p className="operational-positive">¡Todo en orden! No detectamos alertas con los datos disponibles.</p> :
          <ul>{data.alertas.map((alert) => <li key={alert.clave} className={`operational-alert operational-alert--${alert.tipo}`}>
            <span className="operational-alert-icon" aria-hidden="true">⚠</span><div><strong>{alert.tipo === 'stock' ? 'Revisá las compras' : alert.tipo === 'demora' ? `Pedido #${alert.id_pedido} — Demoras detectadas` : alert.tipo === 'entrega' ? 'Una entrega tardó más' : alert.tipo === 'demanda' ? 'Menos pedidos de lo habitual' : `Pedido #${alert.id_pedido} — Importe inusualmente elevado`}</strong>
              {alert.tipo !== 'demora' && <p>{alert.mensaje}</p>}
              {alert.tipo === 'demora' && <ul className="operational-delay-list">{alert.demoras.map(row => <li key={row.estado}>{row.estado}: {minutes(row.minutos)} (habitual: {minutes(row.habitual)}).</li>)}</ul>}
              {alert.id_pedido !== null && <button className="operational-open" onClick={() => onOpen?.(alert.id_pedido!)}>Ver pedido #{alert.id_pedido} →</button>}</div></li>)}</ul>}
        {data.total_alertas > data.alertas.length && <p className="operational-muted">Mostramos las {data.alertas.length} alertas prioritarias de {data.total_alertas}. Los avisos también aparecen junto a cada pedido y entrega.</p>}
        <p className="operational-footnote">El stock es el disponible ahora. Las ventas y los tiempos por estado corresponden a los pedidos de la fecha seleccionada.</p>
      </section>
    </>}
  </div>;
}

export default function OperationalAnalytics({ restaurant, onSessionExpired }: Props) {
  const [date, setDate] = useState<string | null>(null);
  const [selectedOrder, setSelectedOrder] = useState<number | null>(null);
  const path = `restaurantes/${restaurant}/indicadores${date ? `?fecha=${date}` : ''}`;
  const query = useApiQuery<OperationalDashboard>(path,
    (signal) => operationRequest(path, undefined, signal, 'GET', 30000), onSessionExpired);
  const data = query.data;
  const loading = query.isPending;
  const error = query.error?.message;
  return <section className="menu-manager" aria-label="Indicadores y alertas" aria-busy={loading}>
    {error && <p role="alert" className="auth-error">{error} <button onClick={() => void query.refetch()}>Reintentar</button>
      {date && <button onClick={() => setDate(null)}>Volver al día operativo</button>}</p>}
    {loading ? <p className="operational-loading" role="status">Reuniendo las ventas y las entregas de tu rotisería…</p>
      : data && <OperationalDetails data={data} onDate={setDate} onOpen={setSelectedOrder}/>}
    {selectedOrder !== null && <Orders key={selectedOrder} restaurant={restaurant} view="detail" initialOrder={selectedOrder}
      onCloseDetail={() => setSelectedOrder(null)} onSessionExpired={onSessionExpired}/>}
  </section>;
}
