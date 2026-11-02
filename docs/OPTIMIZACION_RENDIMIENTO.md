# Optimización de rendimiento — 1 de noviembre de 2026

Se implementaron A–F sin cambiar algoritmos, permisos, triggers, bloqueos globales,
índices ni datos históricos de Supabase. Se preservó la edición previa del usuario
en `Orders.tsx` («Actualizar pedidos»).

## Cambios

- **Conexiones:** pool de hasta 3 conexiones por proceso, sin overflow, espera
  máxima de 5 segundos, comprobación antes de reutilizar y renovación a los
  240 segundos. La conexión real usa Session Pooler. PostgreSQL informó un máximo
  de 60 conexiones y entre 14 y 18 abiertas durante las mediciones. Seis lecturas
  simultáneas usaron como máximo tres y dejaron cero conexiones prestadas.
- **Consultas:** se reutilizan pedido, restaurante, historial, productos y entrega
  ya autorizados. Preparación evita cargar dos veces información innecesaria.
- **Interfaz:** aplica respuestas confirmadas y actualiza lo restante en segundo
  plano. Cancela lecturas anteriores para evitar que sobrescriban la confirmación.
  La invalidación distingue restaurantes, detalles de pedidos y cambios de distancia.
  El pedido afectado permanece protegido hasta recibir la nueva lectura del tablero;
  los demás se liberan al confirmar el servidor. Un error de recarga permite reintentar.
- **Advertencias:** calcula solo los pedidos solicitados; limita los importes a
  sus ventanas de referencia y las entregas a los repartidores relevantes. Conserva
  los eventos completos de cada entrega, incluidos viajes largos o repetidos.
- **Asignación individual:** filtra pedido y repartidor antes de bloquear; consulta
  la versión sin cargar toda la preparación. Se conserva la asignación por lote.
- **Indicadores/previsión:** comparten fecha operativa y, cuando corresponde, los
  pedidos ya leídos en la misma solicitud. Sin caché persistente ni cambio estadístico.

## Lecturas reales: Rotisería del Pueblo (ID 2)

Comparación del código de HEAD y el optimizado sobre **una misma transacción
REPEATABLE READ, READ ONLY**, con reloj de prioridades fijo. Conexión abierta;
excluye autenticación, apertura de conexión y navegador. Una muestra por servicio.
Las cinco respuestas de negocio fueron idénticas; se excluyen marcas de generación.

| Servicio | Antes | Después |
|---|---:|---:|
| Pedidos del día | 5,61 s | 3,47 s |
| Historial (20 pedidos) | 3,35 s | 2,31 s |
| Detalle | 3,82 s | 1,48 s |
| Indicadores | 5,32 s | 3,67 s |
| Previsión diaria | 2,49 s | 2,00 s |

También se midieron tres sesiones independientes por servicio, incluyendo obtención
de conexión, selección de propietario y cierre: medianas antes/después de
8,04/4,62 s (día), 6,61/3,47 s (historial), 7,51/2,90 s (detalle),
8,71/4,92 s (indicadores) y 5,47/3,17 s (previsión). El restaurante mantuvo 2.423
pedidos, pero hubo cambios de estado durante las primeras rondas. Por eso estos
últimos valores son orientativos y la equivalencia se verificó separadamente
en la instantánea compartida. El primer préstamo puede incluir inicialización
adicional de la conexión. No son tiempos de interacción completos del navegador.

## Escrituras: PostgreSQL 17 local descartable

Misma fixture, endpoints HTTP, tres ciclos y mediana; código anterior cargado
desde HEAD en memoria. Ambos usan el mismo motor de pruebas sin pool, de modo que
esta comparación aísla las consultas eliminadas. No se escribieron pedidos en Supabase.

| Operación | Antes | Después | Consultas antes → después |
|---|---:|---:|---:|
| Crear como cliente | 54,19 ms | 32,56 ms | 15 → 12 |
| Crear como personal | 44,34 ms | 38,63 ms | 15 → 12 |
| Confirmar preparación | 56,96 ms | 33,45 ms | 16 → 13 |
| Marcar listo | 34,83 ms | 31,37 ms | 11 → 8 |
| Asignar individualmente | 49,05 ms | 34,85 ms | 17 → 13 |
| Iniciar entrega | 38,01 ms | 29,06 ms | 9 → 7 |
| Finalizar entrega | 40,87 ms | 42,42 ms | 13 → 11 |

Los milisegundos locales fluctúan: finalizar no mostró mejora temporal en la última
ronda, pero elimina dos lecturas redundantes y conserva las verificaciones de
integridad. No se extrapolan esos tiempos a la latencia remota.

Con una recarga controlada de 400 ms, la espera adicional del servicio frontend
después de la confirmación pasó de 405,5 ms a 0,4 ms. Es una medición controlada
de la caché, no una medición del renderizado real del navegador.

## Validación y pendientes

- Frontend: 31 pruebas aprobadas y compilación TypeScript/Vite correcta.
- Backend: regresión completa con PostgreSQL local: 383 pruebas, 379 aprobadas y
  4 fallos **reproducidos con el código anterior**. Dos listas de rutas no incluyen
  `/pedidos/operacion` y `/predicciones/diaria`; dos pruebas históricas esperan
  rankings distintos de los que ya produce HEAD. No se modificaron esas expectativas.
- Pruebas focalizadas: permisos y aislamiento, versiones, stock e historial,
  reintentos, límite y recuperación del pool, alertas equivalentes y concurrencia.
  Dos pedidos no obtienen el mismo repartidor; dos repartidores no se asignan
  al mismo pedido. Los contenedores de pruebas se detuvieron y descartaron sus datos.
- Se descartaron índices sin evidencia, caché persistente y cambios al bloqueo
  global. No se recortaron eventos de viajes por fecha de inicio porque podría
  alterar referencias de entregas largas.
- Pendiente: actualizar las cuatro expectativas históricas en una tarea separada
  y medir interacción/renderizado real del navegador si se requiere ese nivel de detalle.

Reproducción local desde `backend/`:

```powershell
.\.venv\Scripts\python.exe -m tests.run_postgresql_local discover -s tests -q
.\.venv\Scripts\python.exe -m tests.run_postgresql_local tests.test_performance_postgresql -q
.\.venv\Scripts\python.exe -m tests.run_postgresql_local tests.performance_baseline_recheck -q
.\.venv\Scripts\python.exe -m tests.run_postgresql_local tests.performance_baseline_recheck.WritePerformanceTests -q
```

Las mediciones remotas de esta sesión están en `.tools/performance/` (ignorado
por Git); los scripts `.tools/benchmark_performance.py` y
`.tools/compare_performance_snapshot.py` ejecutan exclusivamente lecturas y no
guardan credenciales, nombres, direcciones ni respuestas de negocio.
