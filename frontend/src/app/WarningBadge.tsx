/** Aviso de solo lectura, accesible con teclado y disponible al tocar el icono. */
export default function WarningBadge({ message, label, title }: { message?: string | null; label?: string; title?: string }) {
  if (!message) return null;
  return <details className={`operational-warning${label ? ' operational-warning--labeled' : ''}`}><summary aria-label={label ?? 'Consultar advertencia'} title={title ?? message}>
    <span aria-hidden="true">⚠</span>{label && <small>{label}</small>}</summary><p>{message}</p></details>;
}
