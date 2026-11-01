/** Aviso de solo lectura, accesible con teclado y disponible al tocar el icono. */
export default function WarningBadge({ message }: { message?: string | null }) {
  if (!message) return null;
  return <details className="operational-warning"><summary aria-label="Consultar advertencia" title={message}>
    <span aria-hidden="true">⚠</span></summary><p>{message}</p></details>;
}
