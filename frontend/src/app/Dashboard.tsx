import { formatAlertDescription, formatCalendarDate, formatDateTime, formatMoney, localDate } from '../services/format';
import { useEffect, useState } from 'react';
import WarningBadge from './WarningBadge';
import { FoodPhoto, Icon, Status, displayText } from './ui';
import { operationRequest, type CourierPage, type Stock } from '../services/operations';
import { OrderError } from '../services/orders';
import type { Alert, Forecast, Metrics } from '../services/analytics';
import type { Delivery, PriorityPage } from '../services/logistics';

type Snapshot = {
  id_restaurante: number; actualizado_en: string; prioridades: PriorityPage; pedidos_por_estado: Record<string, number>;
  entregas_recientes: Delivery[]; stock: Stock[]; repartidores: CourierPage; alertas_activas: Alert[];
  indicadores: Pick<Metrics, 'inicio' | 'fin' | 'referencia_inicio' | 'referencia_fin' | 'promedios' | 'muestras' | 'promedios_referencia' | 'muestras_referencia'> | null;
  prediccion_guardada: Forecast | null;
};
type Props = { restaurant: number; owner: boolean; onSessionExpired: () => void };
const labels: Record<string, string> = { importe: 'Importe por pedido ($)', preparacion: 'Preparación (min)', entrega: 'Entrega (min)' };
const numeric = (value: string | null) => value === null ? 'Sin muestras' : Number(value).toLocaleString('es-AR', { maximumFractionDigits: 2 });
const indicator = (key: string, value: string | null) => value === null ? 'Sin muestras' : key === 'importe' ? formatMoney(value) : numeric(value);

export default function Dashboard({ restaurant, owner, onSessionExpired }: Props) {
  const [data, setData] = useState<Snapshot | null>(null);
  const [period, setPeriod] = useState({ inicio: localDate(-7), fin: localDate(-1) });
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  async function load(signal?: AbortSignal) {
    setBusy(true); setError('');
    try { setData(await operationRequest<Snapshot>(`restaurantes/${restaurant}/dashboard`, period, signal, 'POST')); }
    catch (failure) {
      if (!signal?.aborted) {
        if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
        else setError(failure instanceof Error ? failure.message : 'No se pudo consultar el dashboard.');
      }
    } finally { if (!signal?.aborted) setBusy(false); }
  }
  useEffect(() => {
    const controller = new AbortController(); void load(controller.signal);
    return () => controller.abort();
  }, [restaurant]);
  const total = data ? Object.values(data.pedidos_por_estado).reduce((sum, count) => sum + count, 0) : 0;
  const forecastMax = Math.max(0, ...(data?.prediccion_guardada?.predicciones.map((row) => Number(row.demanda_estimada)) ?? []));

  const available = data?.repartidores.repartidores.filter((row) => row.activo && row.estado_disponibilidad === 'Disponible').length ?? 0;
  const states = Object.entries(data?.pedidos_por_estado ?? {});
  const colors = ['#a9c7b1', '#dfc78f', '#a8bfce', '#bed3b7', '#b6c9bd'];
  const indicatorCards = data?.indicadores;
  return <section className="dashboard-page" aria-label="Resumen del restaurante">
    <form className="dashboard-toolbar" onSubmit={(event) => { event.preventDefault(); void load(); }}>
      {owner && <><div><label htmlFor="dashboard-start">Desde</label><input id="dashboard-start" type="date" required max={period.fin} disabled={busy} value={period.inicio} onChange={(event) => setPeriod({ ...period, inicio: event.target.value })}/></div>
        <div><label htmlFor="dashboard-end">Hasta</label><input id="dashboard-end" type="date" required min={period.inicio} max={localDate(0)} disabled={busy} value={period.fin} onChange={(event) => setPeriod({ ...period, fin: event.target.value })}/></div></>}
      <button disabled={busy}><Icon name="clock" size={14}/>{busy ? 'Actualizando…' : 'Actualizar resumen'}</button>
    </form>
    {owner && <p className="scope-note">Los períodos analíticos conservan su corte diario UTC. Las horas se muestran en horario local.</p>}
    {error && <p role="alert" className="auth-error">{error}</p>}
    {!data && !error && <div className="empty-state"><span className="loading-ring"/><p>Estamos reuniendo la información de tu restaurante…</p></div>}
    {data && <>
      {error && <p className="scope-note">Mostrando la última consulta disponible.</p>}
      <div className="stats-grid">
        {[
          ['orders', 'Pedidos activos', String(total), 'En atención, cocina o reparto'],
          owner ? ['chart', 'Ticket promedio', indicator('importe', indicatorCards?.promedios.importe ?? null), 'Pesos · período seleccionado'] : ['clock', 'Listos para entregar', String(data.pedidos_por_estado.Listo ?? 0), 'Esperando el próximo recorrido'],
          ['truck', 'Repartidores disponibles', String(available), data.repartidores.delivery_disponible ? 'Tu servicio de delivery está disponible' : 'Delivery no disponible por el momento'],
          ['spark', 'Alertas activas', String(data.alertas_activas.length), 'Entre las últimas alertas registradas'],
        ].map(([icon, label, value, note]) => <article className="stat-card" key={label}><div className="stat-heading"><span>{label}</span><span className="stat-icon"><Icon name={icon} size={17}/></span></div>
          <strong className={`stat-value${value === 'Sin muestras' ? ' stat-value--empty' : ''}`}>{value}</strong><span className="stat-note">{note}</span></article>)}
      </div>
      <div className="dashboard-grid">
        <article className="surface-card"><div className="card-heading"><div><h2>Pedidos en movimiento</h2><span className="card-caption">La distribución de tu servicio actual</span></div><a href="#/pedidos">Ver pedidos →</a></div>
          {total ? <div className="dashboard-distribution"><svg className="donut-chart" viewBox="0 0 120 120" role="img" aria-label={`${total} pedidos activos por estado`}>
            <circle cx="60" cy="60" r="43" fill="none" stroke="#f1f5f0" strokeWidth="12"/>
            {states.map(([state, count], index) => <circle key={state} cx="60" cy="60" r="43" fill="none" stroke={colors[index % colors.length]} strokeWidth="12" strokeDasharray={`${count / total * 270.18} ${270.18 - count / total * 270.18}`} strokeDashoffset={-states.slice(0,index).reduce((sum, [, n]) => sum+n, 0) / total * 270.18} transform="rotate(-90 60 60)"/>)}
            <text x="60" y="61" textAnchor="middle" className="donut-total">{total}</text><text x="60" y="75" textAnchor="middle" className="donut-label">PEDIDOS ACTIVOS</text>
          </svg><ul className="chart-legend">{states.map(([state,count],index) => <li key={state}><span className="legend-dot" style={{background:colors[index % colors.length]}}/>{state}<strong>{count}</strong></li>)}</ul></div>
          : <div className="empty-state"><Icon name="orders" size={30}/><h3>Un nuevo servicio por comenzar</h3><p>Cuando registres pedidos, vas a ver su estado aquí.</p><a href="#/nuevo-pedido">Crear un pedido →</a></div>}
        </article>
        <article className="surface-card"><div className="card-heading"><div><h2>Tu equipo de reparto</h2><span className="card-caption">Disponibilidad actual</span></div><Icon name="truck" size={17}/></div>
          {!data.repartidores.repartidores.length && <div className="empty-state"><Icon name="people" size={26}/><p>No hay repartidores registrados.</p></div>}
          {data.repartidores.repartidores.map((row) => <div className="stock-row" key={row.id_repartidor}><strong>{displayText(row.nombre)}</strong><Status value={row.activo ? row.estado_disponibilidad : 'Inactiva'}/></div>)}
          <a className="quick-link" href="#/repartidores">Gestionar repartidores<Icon name="arrow" size={14}/></a>
        </article>
      </div>
      <div className="dashboard-grid">
        <article className="surface-card"><div className="card-heading"><div><h2>Los próximos en tu cocina</h2><span className="card-caption">Ordenados por prioridad de atención</span></div><a href="#/prioridades">Ver todos →</a></div>
          {!data.prioridades.pedidos.length ? <div className="empty-state"><Icon name="check" size={28}/><h3>Todo al día</h3><p>No hay pedidos activos por atender.</p></div> : <div className="table-wrap"><table className="data-table"><thead><tr><th>Pedido</th><th>Estado</th><th>Prioridad</th><th>Registrado</th></tr></thead><tbody>
            {data.prioridades.pedidos.slice(0,6).map((row) => <tr key={row.id_pedido}><td><strong>#{row.id_pedido}</strong><WarningBadge message={row.advertencia_importe}/></td><td><Status value={row.estado}/></td><td>{numeric(row.puntaje_prioridad)} puntos</td><td>{formatDateTime(row.fecha_hora)}</td></tr>)}
          </tbody></table></div>}
        </article>
        <article className="surface-card"><div className="card-heading"><div><h2>{owner ? 'Una mirada al próximo servicio' : 'Alertas del servicio'}</h2><span className="card-caption">{owner ? 'Última previsión guardada' : 'Incidencias operativas activas'}</span></div><Icon name="spark" size={17}/></div>
          {owner && data.prediccion_guardada && <>
            {!data.prediccion_guardada.predicciones.length && <div className="empty-state"><Icon name="chart" size={28}/><h3>El próximo paso, con datos</h3><p>Todavía no hay una previsión guardada. Consultá el historial en Previsión de demanda.</p></div>}
            {data.prediccion_guardada.predicciones.slice(0,3).map((row) => <div className="prediction-teaser" key={row.id_prediccion}><FoodPhoto name={displayText(row.producto)}/><div><strong>{displayText(row.producto)}</strong><p>{numeric(row.demanda_estimada)} unidades estimadas</p><small>{formatCalendarDate(row.periodo_inicio)} a {formatCalendarDate(row.periodo_fin)}</small>
              {forecastMax > 0 && <meter className="dashboard-meter" min={0} max={forecastMax} value={Number(row.demanda_estimada)} aria-label={`Demanda de ${displayText(row.producto)}`}/>}</div></div>)}
            <a className="quick-link" href="#/demanda">Consultar previsiones<Icon name="arrow" size={14}/></a>
          </>}
          {!owner && <ul className="alert-list">{!data.alertas_activas.length && <li>No hay alertas activas guardadas.</li>}{data.alertas_activas.slice(0,3).map((row) => <li className={row.severidad === 'critica' ? 'alert-card--critical' : ''} key={row.id_alerta}><strong>{row.severidad === 'critica' ? 'Crítica' : 'Advertencia'}</strong> · {formatAlertDescription(displayText(row.descripcion))}</li>)}</ul>}
        </article>
      </div>
      {indicatorCards && <article className="surface-card dashboard-indicators"><div className="card-heading"><div><h2>El pulso de tu restaurante</h2><span className="card-caption">{formatCalendarDate(indicatorCards.inicio)} a {formatCalendarDate(indicatorCards.fin)} · referencia: {formatCalendarDate(indicatorCards.referencia_inicio)} a {formatCalendarDate(indicatorCards.referencia_fin)}</span></div><a href="#/indicadores">Ver análisis →</a></div>
        <div className="indicator-columns">{Object.entries(indicatorCards.promedios).map(([key,value]) => {
          const baseline = indicatorCards.promedios_referencia[key]; const maximum = Math.max(Number(value ?? 0), Number(baseline ?? 0));
          return <div key={key}><h3>{labels[key]}</h3><div className="comparison-row"><span>Este período</span><div className="comparison-bar"><span style={{width:maximum ? `${Number(value ?? 0)/maximum*100}%` : '0%'}}/></div><strong>{indicator(key, value)}</strong></div>
            <div className="comparison-row"><span>Referencia</span><div className="comparison-bar comparison-bar--reference"><span style={{width:maximum ? `${Number(baseline ?? 0)/maximum*100}%` : '0%'}}/></div><strong>{indicator(key, baseline)}</strong></div>
            <span className="card-caption">{indicatorCards.muestras[key]} observaciones del período</span></div>;
        })}</div>
      </article>}
      <div className="dashboard-grid">
        <article className="surface-card"><div className="card-heading"><div><h2>Entregas recientes</h2><span className="card-caption">Tus últimos recorridos, hasta 20 entregas</span></div><a href="#/entregas">Ver entregas →</a></div>
          {!data.entregas_recientes.length ? <div className="empty-state"><Icon name="truck" size={28}/><h3>El próximo recorrido empieza acá</h3><p>Las entregas aparecerán cuando asignes pedidos listos.</p></div> : <div className="table-wrap"><table className="data-table"><thead><tr><th>Pedido</th><th>Repartidor</th><th>Estado</th></tr></thead><tbody>{data.entregas_recientes.map((row) => <tr key={row.id_entrega}><td><strong>#{row.id_pedido}</strong><WarningBadge message={row.advertencia_entrega}/></td><td>{displayText(row.repartidor)}</td><td><Status value={row.estado}/></td></tr>)}</tbody></table></div>}
        </article>
        <article className="surface-card"><div className="card-heading"><div><h2>Tu despensa</h2><span className="card-caption">Existencias actuales</span></div><Icon name="food" size={17}/></div>
          {!data.stock.length && <div className="empty-state"><p>No hay insumos registrados.</p></div>}
          {data.stock.map((row) => <div className={`stock-row${Number(row.stock_actual)<0 ? ' stock-row--negative' : ''}`} key={row.id_insumo}><span>{displayText(row.nombre)}</span><strong>{numeric(row.stock_actual)} {row.unidad}</strong></div>)}
        </article>
      </div>
      {owner && <article className="surface-card"><div className="card-heading"><h2>Alertas que merecen tu atención</h2><a href="#/indicadores">Consultar alertas →</a></div><ul className="alert-list">{!data.alertas_activas.length && <li>No hay alertas activas entre las últimas registradas.</li>}{data.alertas_activas.map((row) => <li className={row.severidad === 'critica' ? 'alert-card--critical' : ''} key={row.id_alerta}><strong>{row.severidad === 'critica' ? 'Crítica' : 'Advertencia'}</strong> · {formatAlertDescription(displayText(row.descripcion))} · Valor: {indicator(row.tipo, row.valor_observado)} · Umbral: {indicator(row.tipo, row.valor_referencia)}</li>)}</ul></article>}
      <p className="snapshot-time">Última actualización: {formatDateTime(data.actualizado_en)}. Actualizá el resumen para consultar nuevos cambios.</p>
    </>}
  </section>;
}
