import type { User } from '../services/auth';
export type Page = { path: string; label: string; icon: string; group: string; description: string };
const operations: Page[] = [
  { path: 'pedidos', label: 'Pedidos', icon: 'orders', group: 'Operación', description: 'Del primer ingrediente a la última entrega.' },
  { path: 'catalogo', label: 'Menú y recetas', icon: 'food', group: 'Operación', description: 'La carta de tu restaurante, siempre al día.' },
  { path: 'stock', label: 'Insumos y stock', icon: 'food', group: 'Operación', description: 'Existencias y movimientos de los insumos de tu cocina.' },
  { path: 'repartidores', label: 'Repartidores', icon: 'people', group: 'Operación', description: 'Tu equipo de reparto y su disponibilidad.' },
];
export const newOrder: Page = { path: 'nuevo-pedido', label: 'Nuevo pedido', icon: 'plus', group: 'Operación', description: 'Registrá los productos y los datos de entrega.' };
export const canonicalPath = (path: string) => ['resumen', 'prioridades'].includes(path) ? 'pedidos' : path;
export function pagesFor(user: User): Page[] {
  if (['propietario', 'personal'].includes(user.rol) && user.id_restaurante !== null) return [...operations,
    { path: 'demanda', label: 'Previsión de demanda', icon: 'spark', group: 'Análisis', description: 'Anticipá las próximas ventas y las necesidades de tu cocina.' },
    { path: 'indicadores', label: 'Indicadores y alertas', icon: 'chart', group: 'Análisis', description: 'Datos que te ayudan a tomar mejores decisiones.' },
  ];
  if (user.rol === 'repartidor') return [
    { path: 'pedidos-reparto', label: 'Mis pedidos', icon: 'orders', group: 'Mi trabajo', description: 'Pedidos asignados y su historial.' },
    { path: 'disponibilidad', label: 'Mi disponibilidad', icon: 'clock', group: 'Mi trabajo', description: 'Mantené al equipo informado de tu disponibilidad.' },
  ];
  if (user.rol === 'cliente') return [
    { path: 'menu', label: 'Explorar menú', icon: 'food', group: 'Mi cuenta', description: 'Encontrá tu próximo plato favorito.' },
    { path: 'mis-pedidos', label: 'Mis pedidos', icon: 'orders', group: 'Mi cuenta', description: 'Consultá el estado de tus pedidos y entregas.' },
  ];
  return [{ path: 'soporte', label: 'Soporte de cuentas', icon: 'support', group: 'Administración', description: 'Consultá las condiciones de acceso de una cuenta.' }];
}
export const roleLabels: Record<string, string> = { propietario: 'Propietario', personal: 'Personal', repartidor: 'Repartidor', cliente: 'Cliente', administrador_plataforma: 'Administración' };
