# Etapa 2: pedidos, historial y consistencia operativa

## Cambios

Pedidos y Entregas del personal/propietario utilizan el mismo componente
`OrderListing` y la misma consulta autorizada `GET /api/pedidos`. Ofrecen dos
subsecciones, paginadas de a 20 filas:

- **Pedidos del día**: `periodo=dia`, con límites UTC del día de Buenos Aires
  obtenido de la función centralizada `operational_date`.
- **Historial de pedidos**: `periodo=historial`, sin filtros de fecha ni estado.

Para un mismo período y página se muestran los mismos pedidos, resúmenes,
importes, estados y repartidores. Entregas agrega la entrega real asociada;
cuando no existe muestra **Sin asignar**, sin crear registros ficticios. Los
repartidores conservan su consulta exclusiva de entregas asignadas y sus acciones.
Prioridades conserva su filtro de pedidos activos y su orden operativo.

El backend siempre ordena por fecha descendente e ID descendente. Los filtros de
pertenencia proceden de la sesión: no se agrega un selector de restaurante al
endpoint. El día operativo requiere contexto de personal/propietario; los clientes
conservan su historial de pedidos propios en los restaurantes donde compraron.

Los resúmenes se obtienen de `detalle_pedido` y `producto` en una consulta por
lote, y las entregas/repartidores en otra. No hay una consulta por fila. El detalle
usa la misma información. Los listados de prioridades y de entregas del repartidor
también incluyen los productos reales. El seguimiento se ordena por fecha e ID.

Se preservaron las acciones de preparación, asignación y entrega, las transiciones
y los timestamps reales del servidor. La fecha operativa solo decide el filtro de
consulta: no cambia los relojes de operaciones, autenticación ni auditoría. La
presentación de instantes usa explícitamente Buenos Aires para coincidir con el
criterio de día operativo incluso si el navegador tiene otro huso horario.

No se modificó el esquema, no se rehízo la carga sintética, no se escribieron datos
operativos en Supabase ni se implementaron motores analíticos o dashboards.

## Pedidos antiguos y salto de identificadores

La consulta anterior ordenaba correctamente y devolvía solo 20 filas por página.
La interfaz no mostraba el total ni el número de página; al crear un pedido volvía
a la primera página. Con el historial actual, los pedidos anteriores quedan fuera
de esa página. La interfaz ahora explicita el total y la posición y conserva el
acceso al detalle de cualquier fila.

Se verificó en Supabase, en modo de solo lectura, que **#1 y #2 existen, pertenecen
al restaurante 2 y están en la página 7** con paginación de 20. Se abrieron sus
detalles y seguimientos mediante los servicios autorizados. No se renumeraron
pedidos ni se reiniciaron secuencias. La secuencia de IDs es global, incluye otros
restaurantes y no expresa continuidad de pedidos dentro de un restaurante.

Esta es la explicación comprobada de su ausencia de la primera página actual.
No se dispone de una captura del estado de la interfaz en el instante del episodio
original para atribuirle otra causa histórica.

## Verificaciones ejecutadas

```powershell
# Desde backend/
.\.venv\Scripts\python.exe -m unittest tests.test_orders tests.test_logistics tests.test_preparation -q
.\.venv\Scripts\python.exe -m unittest tests.test_order_history.OrderHistoryTests -q
.\.venv\Scripts\python.exe -m tests.run_postgresql_local tests.test_order_history tests.test_orders_postgresql tests.test_logistics_postgresql tests.test_operations_postgresql tests.test_tab_sessions tests.test_demo_preparation_postgresql -q

# Supabase: solo lectura, sin login ni creación de sesiones.
.\.venv\Scripts\python.exe -m tests.verify_order_history_live --restaurant-id 2 --user-id 1

# Desde frontend/
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vite/bin/vite.js build
node --test tests/*.test.mjs
```

- **39** pruebas existentes de pedidos, preparación y reparto: OK.
- **4** pruebas nuevas locales: OK.
- **62** pruebas en el ejecutor PostgreSQL local descartable: OK, sin omisiones.
  Incluyen pruebas nuevas tanto SQLite como PostgreSQL y regresiones de permisos,
  sesiones, operaciones y carga previa.
- **5** pruebas frontend: OK. TypeScript y compilación de producción: OK.
- Consulta real de Supabase: **2.421 pedidos**, sin IDs duplicados ni faltantes,
  orden correcto en todas las páginas consultadas, **2.421 resúmenes** contrastados
  con detalles y **20 entregas** contrastadas con pedidos. Los pedidos del día son
  **45** y su fecha operativa es **31/10/2026**. Los #1 y #2 son accesibles.
- Navegador con `tests.preview_order_history` y SQLite temporal: mismos IDs en
  Pedidos/Entregas en la primera página del día, fecha 31/10, paginación del historial, consulta de un
  pedido antiguo desde la última página y seguimiento sin entrega asignada.

Las pruebas nuevas verifican fronteras UTC/local, cambio automático de fecha
operativa con una fecha máxima posterior, orden con fechas iguales, creación real
sin pérdida de historial, consistencia de resúmenes/detalle/entrega, consultas por
lote, trazabilidad y reintento sin eventos duplicados, límites y aislamiento.
Las escrituras de esas pruebas se realizan únicamente en bases locales.

## Alcance pendiente

No quedan cambios de datos ni migraciones pendientes de esta etapa. Predicciones,
necesidades futuras, indicadores, alertas y dashboards siguen fuera de alcance.
