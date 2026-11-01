import { useApiQuery } from '../services/useApiQuery';
import { useState } from 'react';
import { operationRequest } from '../services/operations';
import type { Alert, AlertPage } from '../services/analytics';
import { formatAlertDescription, formatDateTime, formatMoney } from '../services/format';

const labels: Record<string, string> = { importe: 'Importe por pedido', preparacion: 'Preparación (min)', entrega: 'Entrega (min)', stock: 'Stock' };
const numeric = (value: string) => Number(value).toLocaleString('es-AR', { maximumFractionDigits: 6 });
export function AlertCard({ row }: { row: Alert }) {
  const critical = row.severidad === 'critica';
  const value = row.tipo === 'importe' ? formatMoney : numeric;
  return <article className={`product-card alert-card ${critical ? 'alert-card--critical' : 'alert-card--warning'}`}>
    <span className={`alert-severity ${critical ? 'alert-severity--critical' : ''}`}>{critical ? 'Crítica' : 'Advertencia'}</span>
    <h3>{labels[row.tipo] ?? row.tipo} · {row.estado}</h3><p>{formatAlertDescription(row.descripcion)}</p>
    <p>Valor observado: {value(row.valor_observado)} · Umbral: {value(row.valor_referencia)}</p>
    <p>Primera detección: {formatDateTime(row.fecha_hora)}</p>
  </article>;
}

export default function Alerts({ restaurant, onSessionExpired }: { restaurant: number; revision: number; onSessionExpired: () => void }) {
  const [query, setQuery] = useState({ tipo: '', severidad: '', estado: '', offset: 0 });
  const params = new URLSearchParams({ limit:'25', offset:String(query.offset) });
  for (const key of ['tipo', 'severidad', 'estado'] as const) if (query[key]) params.set(key, query[key]);
  const path = `restaurantes/${restaurant}/alertas?${params}`;
  const request = useApiQuery<AlertPage>(path, (signal) => operationRequest(path, undefined, signal), onSessionExpired);
  const page = request.data;
  const busy = request.isFetching;
  const error = request.error?.message;
  return <section aria-label="Alertas guardadas">
    <h3>Alertas guardadas del restaurante</h3>
    <div className="alert-filters">
      {([
        ['tipo', 'Tipo', [['importe', 'Importe'], ['preparacion', 'Preparación'], ['entrega', 'Entrega'], ['stock', 'Stock']]],
        ['severidad', 'Severidad', [['critica', 'Crítica'], ['advertencia', 'Advertencia']]],
        ['estado', 'Estado', [['Activa', 'Activa'], ['Resuelta', 'Resuelta']]],
      ] as const).map(([key, label, options]) => <div key={key}><label htmlFor={`alert-${key}`}>{label}</label>
        <select id={`alert-${key}`} value={query[key]} onChange={(event) => setQuery({ ...query, [key]: event.target.value, offset: 0 })}>
          <option value="">Todas</option>{options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
        </select></div>)}
      <button disabled={busy} onClick={() => void request.refetch()}>Consultar alertas guardadas</button>
    </div>
    <p className="scope-note">Clasificación visual: crítica para stock negativo o un valor observado superior al doble del umbral; advertencia para las demás. Los controles conservan sus reglas de detección.</p>
    {error && <p className="auth-error" role="alert">{error}</p>}
    <p role="status">{busy ? 'Consultando alertas…' : page ? `${page.total} alertas · Página ${Math.floor(query.offset / 25) + 1} de ${Math.max(1, Math.ceil(page.total / 25))}` : ''}</p>
    {page && !page.total && <p>No hay alertas que coincidan con los filtros.</p>}
    <div className="catalog-grid" aria-busy={busy}>{page?.alertas.map((row) => <AlertCard key={row.id_alerta} row={row}/>)}</div>
    <nav className="menu-actions" aria-label="Paginación de alertas">
      <button disabled={busy || query.offset === 0} onClick={() => setQuery({ ...query, offset: Math.max(0, query.offset - 25) })}>Alertas anteriores</button>
      <button disabled={busy || !page || query.offset + 25 >= page.total} onClick={() => setQuery({ ...query, offset: query.offset + 25 })}>Más alertas</button>
    </nav>
  </section>;
}
