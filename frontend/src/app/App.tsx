import { useEffect, useState } from 'react';
import { getHealth } from '../services/health';

type ConnectionState =
  | { status: 'loading' }
  | { status: 'success'; message: string }
  | { status: 'error' };

export default function App() {
  const [connection, setConnection] = useState<ConnectionState>({ status: 'loading' });

  async function checkConnection(signal?: AbortSignal) {
    setConnection({ status: 'loading' });
    try {
      const result = await getHealth(signal);
      if (!signal?.aborted) {
        setConnection({ status: 'success', message: result.message });
      }
    } catch {
      if (!signal?.aborted) {
        setConnection({ status: 'error' });
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void checkConnection(controller.signal);
    return () => controller.abort();
  }, []);

  const statusLabel = {
    loading: 'Comprobando conexión…',
    success: 'Conexión verificada',
    error: 'Sin conexión al backend',
  }[connection.status];

  return (
    <div className="page">
      <header className="page-header">
        <span className="brand">Pedidos y delivery</span>
        <span className="demo-label">Demo académica</span>
      </header>

      <main>
        <p className="eyebrow">Ingeniería en Software · Etapa 1</p>
        <h1>El primer paso de la demo</h1>
        <p className="intro">
          Esta pantalla comprueba la comunicación entre la interfaz y el servidor.
        </p>

        <section className="connection-card" aria-labelledby="connection-title">
          <h2 id="connection-title">Estado de conexión</h2>
          <div role="status" aria-live="polite" aria-atomic="true">
            <p className={`status status--${connection.status}`}>{statusLabel}</p>
            <p className="connection-description">
              {connection.status === 'success'
                ? connection.message
                : connection.status === 'error'
                  ? 'No se pudo verificar la conexión. Comprobá que el backend esté iniciado y volvé a intentar.'
                  : 'Consultando al servidor. Esto puede tardar unos segundos.'}
            </p>
          </div>
          <button
            type="button"
            disabled={connection.status === 'loading'}
            onClick={() => void checkConnection()}
          >
            {connection.status === 'loading' ? 'Comprobando…' : 'Volver a comprobar'}
          </button>
        </section>

        <p className="scope-note">
          Base inicial del proyecto. Las funciones de gestión de pedidos se incorporarán en las próximas etapas.
        </p>
      </main>
      <footer>Prototipo de tesis · Desarrollo por etapas</footer>
    </div>
  );
}
