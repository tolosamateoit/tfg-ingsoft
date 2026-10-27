import { useEffect, useRef, type ReactNode } from 'react';

const paths: Record<string, ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
  orders: <><path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/></>,
  food: <><path d="M4 3v6a3 3 0 0 0 6 0V3M7 3v18M19 3c-4 2-4 8 0 9v9M19 3v9"/></>,
  truck: <><path d="M3 5h11v12H3zM14 9h4l3 4v4h-7"/><circle cx="7" cy="18" r="2"/><circle cx="18" cy="18" r="2"/></>,
  people: <><circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 4v3"/></>,
  chart: <><path d="M4 3v17h17M8 15v-4M13 15V7M18 15V4"/></>,
  spark: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/></>,
  support: <><path d="M4 13v-1a8 8 0 0 1 16 0v1M4 12h3v7H4zM17 12h3v7h-3zM20 19c0 2-3 2-6 2"/></>,
  eye: <><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12"/><circle cx="12" cy="12" r="3"/></>,
  eyeOff: <><path d="m3 3 18 18M10 5a12 12 0 0 1 12 7c-1 2-2 3-4 4M6 6a15 15 0 0 0-4 6s3 7 10 7c2 0 4-.5 5-1.5"/></>,
  logout: <><path d="M9 4H4v16h5M9 12h12m-4-4 4 4-4 4"/></>,
  menu: <path d="M3 6h18M3 12h18M3 18h18"/>,
  close: <path d="m6 6 12 12M6 18 18 6"/>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
  plus: <path d="M12 4v16M4 12h16"/>,
  search: <><circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  leaf: <><path d="M20 3C6 2 2 9 6 16s15 4 14-13Z"/><path d="M4 21 16 9"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
};
export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] ?? paths.grid}</svg>;
}
export function Status({ value }: { value: string }) {
  const tone = ['Entregado', 'Listo', 'Disponible', 'Activa'].includes(value) ? 'success'
    : ['No entregado', 'No disponible', 'Inactiva'].includes(value) ? 'danger' : ['En preparación', 'Ocupado'].includes(value) ? 'warning' : 'neutral';
  return <span className={`status-badge status-badge--${tone}`}><i />{value}</span>;
}
export function FoodPhoto({ name, hero = false }: { name: string; hero?: boolean }) {
  const text = name.toLowerCase();
  const index = /pizza|muzza/.test(text) ? 1 : /hamburg|burger/.test(text) ? 2 : /ensalad|salad/.test(text) ? 3 : /empanad/.test(text) ? 4 : /pasta|fideo|raviol/.test(text) ? 5 : 0;
  return <div className={`food-photo${hero ? ' food-photo--hero' : ''}`} role="img" aria-label={`Imagen ilustrativa de ${name}`}
    style={{ backgroundPosition: `${(index % 3) * 50}% ${Math.floor(index / 3) * 100}%` }} />;
}
export function Dialog({ title, children, onClose, busy = false }: { title: string; children: ReactNode; onClose: () => void; busy?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} className="editor-dialog" aria-label={title} onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="dialog-heading"><div><span className="eyebrow">Tu restaurante</span><h2>{title}</h2></div>
      <button type="button" className="icon-button" aria-label={`Cerrar ${title}`} disabled={busy} onClick={onClose}><Icon name="close" /></button></div>
    {children}
  </dialog>;
}
export function displayText(value: string | null | undefined): string {
  return (value ?? '').replace(/\[PRUEBA SINT[EÉ]TICA\]\s*/gi, '').replace(/\bsint[eé]tic[oa]s?\b/gi, '').replace(/\bHU-\d+\b/g, '').replace(/\bdemo\b/gi, '').replace(/precargad([oa]s?)/g, 'registrad$1').trim();
}
