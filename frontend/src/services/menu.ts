import { cacheScope, invalidateMutation } from './queryCache';
import { sessionHeaders } from './session';
export type Product = {
  id_producto: number;
  id_restaurante: number;
  nombre: string;
  precio: string;
  costo_unitario: string;
  activo: boolean;
  descripcion: string | null;
  imagen_url: string | null;
};
export type ProductInput = Omit<Product, 'id_producto' | 'id_restaurante'>;
export type Ingredient = { id_insumo: number; nombre: string; unidad: string };
export type RecipeItem = { id_insumo: number; cantidad: string; unidad: string };
export type Recipe = { id_producto: number; detalles: (RecipeItem & { nombre: string })[] };

export class MenuError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(restaurant: number, path: string, method = 'GET', body?: object, signal?: AbortSignal): Promise<T> {
  const requestScope = cacheScope();
  const response = await fetch(`/api/restaurantes/${restaurant}/${path}`, {
    method, credentials: 'same-origin', cache: 'no-store',
    headers: await sessionHeaders(Boolean(body)),
    body: body ? JSON.stringify(body) : undefined,
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(10000)]) : AbortSignal.timeout(10000),
  });
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null);
    const detail = data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string' ? data.detail : null;
    throw new MenuError(response.status, response.status === 401 ? 'Tu sesión venció. Volvé a ingresar.'
      : response.status === 403 ? 'No tenés permiso para gestionar este restaurante.'
        : response.status === 422 ? detail ?? 'Comprobá los datos ingresados.'
          : response.status === 404 ? 'El producto ya no está disponible en este restaurante.'
            : 'No se pudo completar la operación. Volvé a intentar.');
  }
  const result = await response.json() as T;
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) await invalidateMutation(`restaurantes/${restaurant}/${path}`, requestScope);
  return result;
}

export const listProducts = (restaurant: number, signal?: AbortSignal) => request<Product[]>(restaurant, 'productos', 'GET', undefined, signal);
export const listIngredients = (restaurant: number, signal?: AbortSignal) => request<Ingredient[]>(restaurant, 'insumos', 'GET', undefined, signal);
export const createProduct = (restaurant: number, data: ProductInput) => request<Product>(restaurant, 'productos', 'POST', data);
export const updateProduct = (restaurant: number, id: number, data: ProductInput) => request<Product>(restaurant, `productos/${id}`, 'PUT', data);
export const getRecipe = (restaurant: number, id: number, signal?: AbortSignal) => request<Recipe>(restaurant, `productos/${id}/receta`, 'GET', undefined, signal);
export const saveRecipe = (restaurant: number, id: number, detalles: RecipeItem[]) => request<Recipe>(restaurant, `productos/${id}/receta`, 'PUT', { detalles });

export { formatMoney } from './format';
