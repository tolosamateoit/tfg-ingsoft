import { useEffect, useState } from 'react';
import { useApiQuery } from '../services/useApiQuery';
import { operationRequest } from '../services/operations';
import { formatCalendarDate, formatMoney } from '../services/format';

type Performance = {fecha: string; asignados: number; entregados: number; ganancia: string; promedio_minutos: number | null; tasa_completados: number | null;
  evolucion: {fecha: string; ganancias: string; promedio_minutos: number | null}[]};
export default function CourierPerformance({path, daily = false, selectedDate, onSessionExpired}: {path: string; daily?: boolean; selectedDate?: string; onSessionExpired: () => void}) {
  const [date, setDate] = useState('');
  useEffect(() => { if (selectedDate !== undefined) setDate(selectedDate); }, [selectedDate]);
  const [metric, setMetric] = useState<'ganancias' | 'promedio_minutos'>('ganancias');
  const url = `${path}${date && daily ? `?fecha=${date}` : ''}`;
  const query = useApiQuery<Performance>(url, signal => operationRequest(url, undefined, signal), onSessionExpired, {interval: 10000});
  const data = query.data;
  const values = data?.evolucion.map(row => Number(row[metric] ?? 0)) ?? [];
  const max = Math.max(1, ...values);
  return <section className="surface-card"><h3>Desempeño · últimos 30 días</h3>
    {query.error && <p role="alert">{query.error.message}</p>}
    {data && <><p>Tiempo promedio de entrega: <strong>{data.promedio_minutos === null ? 'Sin datos' : `${data.promedio_minutos} min`}</strong> · Pedidos completados: <strong>{data.tasa_completados === null ? 'Sin datos' : `${data.tasa_completados}%`}</strong></p>
      {daily && <><label>Fecha seleccionada <input type="date" value={date || data.fecha} onChange={event => setDate(event.target.value)}/></label>
        <p>Asignados: {data.asignados} · Entregados: {data.entregados} · Ganancia estimada: {formatMoney(data.ganancia)}</p></>}
      <label>Últimos 7 días <select value={metric} onChange={event => setMetric(event.target.value as typeof metric)}><option value="ganancias">Ganancias estimadas</option><option value="promedio_minutos">Tiempo promedio</option></select></label>
      <div className="courier-chart">{data.evolucion.map((row, i) => <div key={row.fecha} title={formatCalendarDate(row.fecha)}><span>{row[metric] === null ? 'Sin datos' : metric === 'ganancias' ? formatMoney(row.ganancias) : `${row.promedio_minutos} min`}</span><div className="courier-bar" style={{height: `${Math.max(2, values[i] / max * 70)}px`}}/><small>{formatCalendarDate(row.fecha)}</small></div>)}</div>
    </>}
  </section>;
}
