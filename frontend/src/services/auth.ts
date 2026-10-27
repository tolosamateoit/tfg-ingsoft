export type User = {
  id_usuario: number;
  nombre: string;
  correo: string;
  rol: string;
  id_restaurante: number | null;
};

export class AuthError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request(path: string, body?: object, signal?: AbortSignal) {
  const response = await fetch(`/api/auth/${path}`, {
    method: body ? 'POST' : 'GET',
    credentials: 'same-origin',
    headers: body ? { 'Content-Type': 'application/json', 'X-CSRF-Protection': '1' } : {},
    body: body ? JSON.stringify(body) : undefined,
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(10000)]) : AbortSignal.timeout(10000),
    cache: 'no-store',
  });
  if (!response.ok) {
    const message = response.status === 401
      ? 'No se pudo iniciar sesión. Verificá los datos o intentá nuevamente en 15 minutos.'
      : response.status === 403
        ? 'No se pudo validar el origen de la solicitud. Volvé a abrir la aplicación desde la dirección local indicada.'
      : response.status === 503
        ? 'El servicio de inicio de sesión no está disponible. Volvé a intentar.'
      : response.status === 422
        ? 'Comprobá el correo y la contraseña ingresados.'
        : 'No se pudo completar la solicitud. Volvé a intentar.';
    throw new AuthError(response.status, message);
  }
  return response.status === 204 ? undefined : response.json();
}

export async function getSession(signal?: AbortSignal): Promise<User | null> {
  try { return await request('me', undefined, signal) as User; }
  catch (error) {
    if (error instanceof AuthError && error.status === 401) return null;
    throw error;
  }
}

export async function login(correo: string, contrasena: string): Promise<User> {
  return await request('login', { correo, contrasena }) as User;
}

export async function logout(): Promise<void> {
  try { await request('logout', {}); }
  catch (error) {
    if (!(error instanceof AuthError && error.status === 401)) throw error;
  }
}
