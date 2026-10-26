type HealthResponse = {
  status: 'ok';
  message: string;
};

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const timeout = AbortSignal.timeout(5000);
  const response = await fetch('/api/health', {
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new Error('El backend no respondió correctamente.');
  }

  const data: unknown = await response.json();
  if (
    typeof data !== 'object' ||
    data === null ||
    !('status' in data) ||
    data.status !== 'ok' ||
    !('message' in data) ||
    typeof data.message !== 'string'
  ) {
    throw new Error('La respuesta del backend no tiene el formato esperado.');
  }

  return { status: data.status, message: data.message };
}
