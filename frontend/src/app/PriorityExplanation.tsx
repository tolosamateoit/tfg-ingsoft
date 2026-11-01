import type { Priority } from '../services/logistics';
import { formatDistance } from '../services/format';

export default function PriorityExplanation({ priority }: { priority: Priority }) {
  return <div className="order-priority-explanation"><p>{priority.explicacion}</p>
    <div className="priority-factors">{priority.factores.map((factor) => <div className="priority-factor" key={factor.codigo}>
      <div><strong>{factor.nombre}</strong><span>{factor.codigo === 'D' && priority.distancia_km !== null
        ? `${formatDistance(priority.distancia_km)} km registrados` : factor.detalle}</span></div>
      {factor.aporte === null ? <p>No disponible; no aporta al orden.</p> :
        <div className="priority-factor-track"><span className={`priority-factor-bar priority-factor--${factor.codigo}`} style={{width:`${factor.barra}%`}}/></div>}
    </div>)}</div>
  </div>;
}
