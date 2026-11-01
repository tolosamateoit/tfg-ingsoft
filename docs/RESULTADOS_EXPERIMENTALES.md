# Resultados experimentales — Oliva, fase 3

**Ejecución:** 2026-10-31T14:04:22.601128-03:00 (Buenos Aires); 2026-10-31T17:04:22.601128+00:00 UTC.
**Origen:** Supabase PostgreSQL, restaurante **Rotisería del Pueblo, ID 3**. Operaciones históricas sintéticas; cálculos reales de los servicios implementados.

## 1. Metodología y conservación de los datos

Se verificó la revisión `0003_producto_presentacion` y el historial existente. No se regeneró la carga, ni se cambiaron el DER, las migraciones, el esquema, la interfaz o los algoritmos de negocio.

Se reutilizaron `generate_forecast`, `ingredient_needs`, `metrics`, `observations`, `calculate`, `ranked_couriers` y `assign_ready_orders`. La instrumentación está en `backend/app/analytics/experiment.py`; las asignaciones se probaron exclusivamente en PostgreSQL local descartable.

Antes de ejecutar se guardó un respaldo privado completo del restaurante en `.tools/history-demo/`. Las llamadas de los motores se agruparon en una transacción exterior; sus commits internos liberaron savepoints. Solo se confirmó la transacción tras comprobar auditorías, integridad de entradas y aislamiento. Las únicas escrituras de negocio en Supabase fueron las seis predicciones y las alertas del restaurante 3.

Huella SHA-256 de las entradas antes y después: `f495ba13372cb67a5190ce2e69329e9254341ca6f3677f2e0268a1c74dc50364`. Los registros históricos, stock, catálogo, cuentas, disponibilidades y demás entradas conservaron la misma huella. También coincidió la huella de registros externos: `613dea3252f67b499e8146f4377925d38f4fbed9bdaa42c4f8e38ea202f50bfb`.

### Conjunto de datos

Período de operación: **02/08/2026–30/10/2026**, 90 días locales de Buenos Aires. Las marcas temporales están almacenadas en UTC. Los motores agrupan ventas y períodos de indicadores por UTC, sin cambiar esa regla.

| Elemento | Cantidad |
| --- | --- |
| Pedidos | 2407 |
| Entregados / no entregados / pendientes al corte | 2.315 / 89 / 3 |
| Productos / insumos / detalles de receta | 8 / 15 / 32 |
| Detalles de pedido | 2940 |
| Entregas / eventos de pedido | 2404 / 14439 |
| Movimientos de stock | 12416 |
| Clientes / repartidores | 24 / 4 |
| Predicciones / alertas antes de la ejecución | 0 / 0 |

Los estados pendientes son una fotografía del corte histórico. No se presentaron como pedidos actuales ni se completaron para la evaluación.

## 2. Predicción de demanda y auditoría temporal

Se utilizaron **2315 pedidos entregados**. Se excluyeron las 89 entregas fallidas y los tres pendientes. Para cada producto con ventas se construyó una serie de 90 días, incorporando explícitamente ceros en días sin ventas.

| Etapa | Período UTC | Días |
| --- | --- | --- |
| Entrenamiento para evaluar MAE | 2026-08-02–2026-10-12 | 72 |
| Evaluación fuera de muestra | 2026-10-13–2026-10-30 | 18 |
| Reentrenamiento posterior para pronosticar | 2026-08-02–2026-10-30 | 90 |
| Horizonte pronosticado | 2026-10-31–2026-11-06 | 7 |

El único predictor de la regresión lineal es el índice cronológico del día. El MAE es `Σ |ventas observadas − pronóstico de validación| / 18`, en unidades por día. El ajuste de evaluación usa solo los primeros 72 días; el reentrenamiento con los 90 días ocurre después de calcular el MAE. Los pronósticos negativos se limitan a cero, como hace el servicio existente.

Se contrastaron MAE y horizonte mediante una implementación independiente de mínimos cuadrados con decimales. Los seis resultados coincidieron dentro de `0,000001` unidades. Una prueba automatizada instrumentó el regresor real: comprobó el orden fit(entrenamiento) → predict(validación) → fit(total) → predict(futuro), incluyendo ceros. Alterar el bloque de evaluación en la auditoría no cambia las predicciones del ajuste de entrenamiento.

### Resultados por producto

| Producto | ID predicción | Demanda 7 días (unidades) | MAE (unidades/día) | Días con venta cero | Ventas últimos 7 días |
| --- | --- | --- | --- | --- | --- |
| Milanesa con puré | 1 | 57.531432 | 3.332179 | 0 | 70 |
| Pollo al horno con papas | 2 | 60.413656 | 2.527330 | 0 | 75 |
| Empanada de carne | 3 | 488.707750 | 19.308490 | 0 | 522 |
| Tarta de verduras | 4 | 28.403745 | 2.295011 | 2 | 29 |
| Ensalada de estación | 5 | 41.936502 | 2.445057 | 7 | 35 |
| Pasta con salsa | 6 | 20.021492 | 1.864802 | 8 | 20 |

Los valores semanales son los resultados persistidos del motor. Las ventas de la semana anterior se muestran como contexto descriptivo, no como observaciones del horizonte futuro ni como una comparación de modelos. El MAE absoluto de productos con distinta escala de venta no basta para ordenar su calidad relativa.

### Desagregación diaria auditada

El servicio persiste el total del horizonte. Esta tabla reconstruye el ajuste final para sus siete días. Se muestran seis decimales; el total del motor se redondea después de sumar.

| Fecha UTC | Milanesa con puré | Pollo al horno con papas | Empanada de carne | Tarta de verduras | Ensalada de estación | Pasta con salsa |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-31 | 8.405243 | 8.647191 | 68.591760 | 4.064419 | 5.880150 | 2.926592 |
| 2026-11-01 | 8.343088 | 8.641635 | 68.999638 | 4.062172 | 5.917076 | 2.904466 |
| 2026-11-02 | 8.280932 | 8.636079 | 69.407515 | 4.059925 | 5.954003 | 2.882339 |
| 2026-11-03 | 8.218776 | 8.630522 | 69.815393 | 4.057678 | 5.990929 | 2.860213 |
| 2026-11-04 | 8.156620 | 8.624966 | 70.223270 | 4.055431 | 6.027855 | 2.838087 |
| 2026-11-05 | 8.094464 | 8.619410 | 70.631148 | 4.053184 | 6.064782 | 2.815961 |
| 2026-11-06 | 8.032309 | 8.613854 | 71.039025 | 4.050936 | 6.101708 | 2.793835 |

### Coherencia frente a los patrones históricos

| Producto | Unidades primeros 30 días | Unidades últimos 30 días | Pendiente final (unidades/día) |
| --- | --- | --- | --- |
| Milanesa con puré | 406 | 284 | -0.062156 |
| Pollo al horno con papas | 276 | 268 | -0.005556 |
| Empanada de carne | 1194 | 1884 | 0.407878 |
| Tarta de verduras | 126 | 122 | -0.002247 |
| Ensalada de estación | 90 | 165 | 0.036926 |
| Pasta con salsa | 140 | 105 | -0.022126 |

Empanadas y ensaladas presentan pendientes positivas, mientras que milanesas y pastas presentan pendientes negativas, coherentes con las tendencias del historial. La regresión no incorpora día de semana: no reproduce explícitamente el pico de fines de semana que contiene la muestra. La dirección de una tendencia no demuestra por sí sola precisión futura.

### Historial insuficiente y productos nuevos

| Producto omitido | Resultado |
| --- | --- |
| Tortilla de papas | Sin ventas entregadas; no se inventa una serie de demanda. |
| Berenjenas al horno | Sin ventas entregadas; no se inventa una serie de demanda. |

El restaurante supera los mínimos de siete días y diez pedidos, por lo que su respuesta es `Predicción generada`. Los mínimos no se aplican por producto. Los dos productos sin ventas entregadas aparecen en `productos_sin_ventas`, sin MAE ni demanda inventados. Un producto con pocas ventas podría recibir una predicción si el restaurante cumple los mínimos; no existe una antigüedad o muestra mínima por producto en el algoritmo actual. Las pruebas existentes verifican además los casos globales de seis días/diez pedidos y siete días/nueve pedidos, que devuelven `Historial insuficiente`.

## 3. Necesidades de insumos y existencias reales

Para cada insumo se sumó `demanda pronosticada del producto × cantidad de su receta`. Se reutilizaron las recetas y unidades persistidas y el redondeo superior a seis decimales. La auditoría verificó cada suma y que el stock leído de Supabase coincide con la suma de sus movimientos. No se modificaron existencias.

| Insumo | Unidad | Necesidad 7 días | Stock Supabase | Faltante |
| --- | --- | --- | --- | --- |
| Carne vacuna | kg | 39.535842 | 100.000000 | 0.000000 |
| Pollo | kg | 24.165463 | 1.000000 | 23.165463 |
| Papas | kg | 37.253581 | 160.000000 | 0.000000 |
| Harina de trigo | kg | 22.956760 | 120.000000 | 0.000000 |
| Cebolla | kg | 14.661233 | 80.000000 | 0.000000 |
| Aceite de girasol | l | 6.212797 | 0.500000 | 5.712797 |
| Espinaca | kg | 5.112675 | 50.000000 | 0.000000 |
| Huevos | unidad | 42.786603 | 400.000000 | 0.000000 |
| Queso mozzarella | kg | 2.020833 | 60.000000 | 0.000000 |
| Tomate | kg | 8.035605 | 90.000000 | 0.000000 |
| Lechuga | kg | 4.193651 | -0.200000 | 4.393651 |
| Zanahoria | kg | 3.354921 | 50.000000 | 0.000000 |
| Fideos secos | kg | 4.004299 | 90.000000 | 0.000000 |
| Berenjena | kg | — | 20.000000 | — |
| Pan rallado | kg | 3.451886 | 50.000000 | 0.000000 |

Se detectaron faltantes previstos de **pollo, aceite de girasol y lechuga**. Berenjena no participa en una receta de producto pronosticado: se indica ausencia de estimación, no una necesidad calculada de cero.

Ejemplo verificable: pollo = `60.413656 × 0.4 = 24.1654624 kg`; con redondeo superior, `24.165463 kg`. Al restar `1.000000 kg` de stock, el faltante es `23.165463 kg`. La lechuga tiene una diferencia de inventario de `−0.200000 kg`; por eso su faltante supera la necesidad en `0.200000 kg`.

## 4. Indicadores y alertas efectivas

Período evaluado: **01/10/2026–30/10/2026 UTC**. Referencia: **01/09/2026–30/09/2026 UTC**, de igual duración. Importe usa la fecha de creación; preparación usa la finalización del ciclo en `Listo`; entrega usa la finalización `Entregado`, desde `En camino`. Los ciclos abandonados al repetir preparación y las entregas `No entregado` no inventan tiempos de entrega completada.

| Indicador | Unidad | N referencia | N evaluado | Promedio referencia | Promedio evaluado | Umbral × 1,10 | Alertas | No superan umbral |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Importe | ARS | 798 | 783 | 16382.080201 | 17419.284802 | 18020.288221 | 278 | 505 |
| Preparación | min | 798 | 783 | 20.328321 | 20.928480 | 22.361153 | 278 | 505 |
| Entrega | min | 763 | 761 | 14.498034 | 14.984231 | 15.947837 | 344 | 417 |

Los umbrales se compararon sin redondearlos; la tabla solo redondea su presentación. La condición es estricta: observado **mayor** que referencia × 1,10. Los valores iguales al umbral no disparan alerta.

| Tipo | Alertas activas persistidas |
| --- | --- |
| importe | 278 |
| preparacion | 278 |
| entrega | 344 |
| stock | 1 |
| Total | 901 |

La alerta de stock corresponde a **lechuga, ID 14, −0.200000 kg**, con umbral cero. Pollo y aceite presentan faltantes futuros, pero su stock actual no es negativo: sus faltantes pertenecen al cálculo de HU-08, no a la regla de stock negativo de HU-09.

### Casos deliberados rastreados

| Pedido Supabase | Caso | Valor observado | Umbral | Alerta ID | Resultado |
| --- | --- | --- | --- | --- | --- |
| 1626 | preparacion_lenta | 91.00 | 22.361153 | 282 | Detectado |
| 1704 | entrega_lenta | 80.00 | 15.947837 | 595 | Detectado |
| 1740 | importe_alto | 151700.00 | 18020.288221 | 36 | Detectado |
| 1780 | preparacion_lenta | 87.00 | 22.361153 | 338 | Detectado |
| 1888 | entrega_lenta | 81.00 | 15.947837 | 667 | Detectado |
| 1939 | importe_alto | 151700.00 | 18020.288221 | 114 | Detectado |
| 1940 | preparacion_lenta | 79.00 | 22.361153 | 392 | Detectado |
| 2064 | entrega_lenta | 75.00 | 15.947837 | 735 | Detectado |
| 2095 | preparacion_lenta | 83.00 | 22.361153 | 452 | Detectado |
| 2141 | importe_alto | 151700.00 | 18020.288221 | 183 | Detectado |
| 2249 | preparacion_lenta | 85.00 | 22.361153 | 491 | Detectado |
| 2251 | entrega_lenta | 79.00 | 15.947837 | 832 | Detectado |
| 2357 | importe_alto | 151700.00 | 18020.288221 | 262 | Detectado |

Se detectaron **13 de 13 casos marcados**: cinco de preparación, cuatro de entrega y cuatro de importe. No hubo un caso marcado omitido que requiriera corregir el motor.

Además se detectaron 274 importes, 273 preparaciones y 340 entregas sin esas marcas. Son **887 observaciones adicionales** que cumplen efectivamente el umbral aprobado. Las marcas del generador no constituyen etiquetas exhaustivas de anomalía: muchos tiempos habituales de 23–27 minutos superan un umbral de preparación de aproximadamente 22,36 minutos. Por eso no se identifica automáticamente a esas alertas adicionales como defectos o falsos positivos demostrados. La sensibilidad de la regla debe considerarse al interpretar el resultado.

No activaron esas alertas 505 observaciones de importe, 505 de preparación y 417 de entrega. Los dos productos sin ventas tampoco obtuvieron predicciones. La aplicación no estima tiempos de entrega completada para los 89 pedidos no entregados del conjunto completo. Las ventanas UTC por finalización pueden incluir operaciones creadas en otra ventana o excluir cierres nocturnos del último día; por ello las muestras de preparación/entrega no tienen por qué igualar las de importe.

### Reejecución y duplicados

| Control | Cantidad |
| --- | --- |
| Alertas tras primera ejecución | 901 |
| Alertas tras segunda ejecución | 901 |
| Claves de observación duplicadas | 0 |
| IDs y valores iguales | True |

La tabla completa contiene 901 alertas; la consulta operativa devuelve las últimas **100**. La evaluación leyó todas las alertas del restaurante, no solo esa página. La fecha de la alerta registra su generación; la descripción conserva la fecha observada y su referencia. Una nueva evaluación con otro período puede actualizar una alerta operativa; el JSON preserva la evidencia de esta ejecución.

## 5. Priorización y asignación

### Lectura del conjunto real sin modificar pedidos

Se copiaron en memoria los tres pedidos activos y se aplicó `P = T + D + G` al instante UTC `2026-10-31 17:04:22.601128+00:00`. No se persistieron puntajes, estados ni asignaciones.

| Pedido Supabase | Estado | T | D | G | P |
| --- | --- | --- | --- | --- | --- |
| 2407 | Nuevo | 954 | 8.750 | 7.039 | 969.789 |
| 2408 | En preparación | 953 | 8.750 | 7.039 | 968.789 |
| 2409 | Listo | 952 | 8.750 | 7.9515 | 968.7015 |

La consulta real de candidatos devolvió **0 repartidores disponibles**, con **1 pedido listo**. El restaurante histórico conserva su cierre y sus repartidores no disponibles. Las entregas completadas permanecieron intactas.

### Casos controlados en PostgreSQL local descartable

**Todos los ID de esta subsección son de fixtures locales; no identifican pedidos o repartidores históricos de Supabase.** Se reutilizaron los servicios reales y el esquema migrado en un contenedor que se eliminó al terminar.

| Caso | Entradas / resultado verificado |
| --- | --- |
| Fórmula y minutos completos | 10001 min 59 s; distancia 3,25; importe 10000,12; costo 5500,01 → T=10001, D=6,75, G=4,50011; P=10012.25011 |
| Empate por antigüedad y luego ID | Tres P=17,540; pedidos más antiguos 4 y 5 con fecha idéntica, pedido 1 cinco segundos posterior → orden [4, 5, 1] |
| Nombre alfabético con carga/tasa iguales | Ana Ruiz (3), Bruno Silva (1) → [3, 1] |
| Tasa de éxito precede al nombre | Bruno 1/1; Ana 0/1; carga igual → [1, 3] |
| Menor carga precede a tasa de éxito | Bruno carga 1 y éxito 1/1; Ana carga 0 y éxito 0/1 → [3, 1] |
| Filtros | Repartidor 2 de otro restaurante excluido; al inactivar Ana queda [1]; al no disponer de Bruno queda [3] |
| Asignación por prioridad | Pedidos [4, 5] a repartidores [3, 1]; queda 1 listo pendiente |
| Costo y redondeo | 100,00 + 0,10 × 2,55 = 100,255 → 100,26 con ROUND_HALF_UP; ambos costos persistidos coincidieron |
| Reintento | 0 entregas nuevas; sin duplicar asignaciones |

La prueba de carga usa disponibilidades declaradas y carga activa controladas, para verificar que ambos factores se evalúan. No representa una modificación del estado de los repartidores históricos.

## 6. Pruebas, problemas y limitaciones

La regresión completa finalizó con **288 pruebas aprobadas** en **202.433 segundos**, usando PostgreSQL local descartable. Se añadieron cinco pruebas experimentales: auditoría exacta, independencia del bloque de evaluación, orden temporal/ceros en el regresor real, ejecución completa con conservación de entradas y casos de logística. La ejecución real en Supabase añadió la comprobación de persistencia y de igualdad entre ambas corridas de alertas.

No se encontró un defecto que exigiera modificar los motores o las fórmulas aprobadas. Se añadió instrumentación reproducible y pruebas; se documentaron las siguientes limitaciones observadas:

1. La regresión solo usa tendencia temporal: carece de estacionalidad semanal, intervalos de incertidumbre y una comparación contra otros métodos. Solo se evaluó una partición cronológica de 18 días; no se hizo validación móvil.
2. Los datos son sintéticos y de un restaurante. El MAE de esta muestra no demuestra eficacia en restaurantes reales ni en el horizonte futuro, para el que aún no hay ventas observadas.
3. Los mínimos son globales por restaurante. Los productos nuevos sin ventas no pueden pronosticarse; el esquema no registra fechas de alta para distinguir automáticamente ausencia de datos de demanda cero previa.
4. Las cantidades pronosticadas son continuas. Pueden aparecer fracciones de huevos u otros insumos por unidad; no existe redondeo por presentación o lote de compra.
5. La regla del 10 % produce muchas alertas sobre variación habitual. El listado operativo muestra solo las últimas 100 y no constituye la totalidad de detecciones.
6. Las series y ventanas analíticas usan UTC, mientras que el historial se describe por jornadas de Buenos Aires. El stock y la disponibilidad son fotografías actuales, no balances reconstruidos al cierre de cada período analítico.
7. Las predicciones se agregan por ejecución; la garantía de no duplicación comprobada aquí corresponde a las alertas por observación. Los resultados operativos pueden actualizarse al evaluar otros períodos; por eso se guardó evidencia independiente.

## 7. Reproducción y trazabilidad

Evidencia completa: [fase3-20261031T170431Z-d6120d85.json](experimentos/fase3-20261031T170431Z-d6120d85.json). Incluye series diarias, predicciones de validación, valores y umbrales por observación, IDs persistidos, huellas y versiones. Logística aislada: [fase3-logistica-aislada-20261031.json](experimentos/fase3-logistica-aislada-20261031.json). Los respaldos privados permanecen fuera de Git y no se incorporan a la tesis.

SHA-256 del JSON principal: `ac7826b49f9f565083194691830b550e9b9fe12398a4e2d0630182933ef56fc3`.

Desde `backend/`, auditar exactamente los números publicados **sin conexión a Supabase ni escrituras**:

```powershell
.\.venv\Scripts\python.exe -m app.analytics.experiment audit ../docs/experimentos/fase3-20261031T170431Z-d6120d85.json
```

Para repetir los servicios reales en Supabase, con el entorno privado ya configurado y conservando el historial:

```powershell
.\.venv\Scripts\python.exe -m app.analytics.experiment run --execute
```

Ese comando calcula el horizonte desde la fecha UTC real de la base: ejecutarlo otro día agrega días sin ventas a la serie y cambia el horizonte/resultados. No debe cambiarse el reloj ni reescribirse el historial para igualar esta corrida. La auditoría offline del JSON reproduce la evidencia fija; una nueva ejecución se guarda en otro archivo y agrega un nuevo lote de predicciones.

Pruebas aisladas reproducibles:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_experiment -q
.\.venv\Scripts\python.exe -m tests.run_postgresql_local tests.test_experiment_postgresql tests.test_experiment_logistics_postgresql -q
.\.venv\Scripts\python.exe -m tests.run_postgresql_local discover -s tests -q
```

| Componente | Versión utilizada |
| --- | --- |
| python | 3.14.4 |
| scikit-learn | 1.9.1 |
| SQLAlchemy | 2.1.6 |
| psycopg | 3.3.6 |

| Código ejecutado | SHA-256 |
| --- | --- |
| analytics/forecast.py | 53c18d95822e3f6424e7fd98b7742d478a64599667f0314fa28b3d4e7fde024d |
| analytics/metrics.py | dee6e1692740ca1c4600d32a65d492f1247198ac5da08a30b89d4178828beef5 |
| analytics/experiment.py | 72397a5f4d4332b50a73d933d7f628b2d402473525a783726eaaee78599b2e4c |
| logistics/priority.py | e99410f0f25b4629ae819f349d3d75ba3580326dcd2031c0f3b1fa9c97d83f58 |
| logistics/service.py | 3dbabb0751fe56013f6042502a6ce97ace98038b47af42b2b216e1d7bd7b0501 |

## 8. Conclusiones

Los motores produjeron seis pronósticos con MAE cronológico reproducible y necesidades de insumos consistentes con recetas y existencias reales de Supabase. Se identificaron tres faltantes previstos y una diferencia de inventario negativa. El control detectó los trece casos deliberados y otras observaciones que cumplen su umbral; la repetición conservó 901 alertas sin duplicados.

Las pruebas aisladas verificaron fórmula, ordenamiento, desempates, selección, costo y reintentos de asignación, conservando los pedidos históricos. La evidencia permite sostener el funcionamiento y la trazabilidad de esta implementación sobre el escenario sintético. La evaluación no justifica afirmar precisión operativa general ni que una regresión sin estacionalidad sea el modelo más adecuado para demanda gastronómica.
