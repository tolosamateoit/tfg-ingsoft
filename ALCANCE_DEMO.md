# Alcance de la demo — TFG Ingeniería en Software

**Estado:** borrador de implementación, sujeto a observaciones de la profesora.  
**Fuente:** documento vigente «Dev: TESIS_VIGENTE», sección Product Backlog e historias de usuario HU-01 a HU-11, consultado el 26/10/2026.  
**Objetivo:** demostrar un recorrido funcional de extremo a extremo y los tres motores del prototipo, sin intentar completar toda la plataforma en dos semanas.

## Reglas de alcance

- Las **HU y sus criterios de aceptación en la tesis son la fuente de verdad**. Este documento establece un recorte para la **demo**, no modifica las HU ni sus criterios.
- Se intenta cubrir las 11 HU, con distintos grados de profundidad. **Prioridad de implementación:** HU-01 a HU-09; HU-10 como integración visual; HU-11 solo si queda tiempo.
- Datos de prueba **sintéticos**, identificados como tales. Los cálculos y cambios de estado deben ser reales y persistidos; no mostrar métricas inventadas.
- Evitar funciones secundarias, configuraciones sofisticadas e integraciones externas no necesarias.
- Mantener arquitectura y tecnologías previstas: React + TypeScript, FastAPI + Python, PostgreSQL, pandas y scikit-learn; despliegue previsto en Render/Supabase. No añadir tecnologías sin justificarlo.
- La demo debe poder ejecutarse con datos precargados y contar con un recorrido repetible de presentación.
- La profesora todavía no respondió sobre el entregable anterior. **No tratar este alcance como definitivo**: registrar cambios de la devolución y actualizar este archivo antes de alterar arquitectura, datos o funcionalidades.

## Alcance por historia de usuario

| HU | Historia original | Implementación prevista en la demo | Simplificación / límite |
|---|---|---|---|
| HU-01 | Login | Inicio/cierre de sesión con usuarios de prueba y roles; proteger API por rol y pertenencia al restaurante. | Cuentas precargadas; sin registro público ni recuperación de contraseña en esta primera demo. |
| HU-02 | Gestión de menú, productos y recetas | Listar y editar productos/precios; registrar recetas con insumos, cantidades y unidades; vincular datos al restaurante. | Catálogo pequeño y precargado; sin carga compleja de imágenes ni opciones avanzadas. |
| HU-03 | Registro de pedidos | Cliente consulta menú, arma carrito, confirma pedido y consulta estado; persistir detalle, cantidades, importe, dirección, medio de pago, fecha y estado inicial. | Pago registrado como elección, sin pasarela de cobro. Confirmación con delivery solo si restaurante abierto y al menos un repartidor disponible. |
| HU-04 | Preparación y movimientos de stock | Personal cambia estados; historial con fecha, hora y usuario; al entrar por primera vez en «En preparación», descontar insumos según recetas y registrar consumo una sola vez. | Flujo de estados acotado; contemplar nuevo descuento únicamente ante una nueva preparación explícita por pedido arruinado. |
| HU-05 | Repartidores y disponibilidad de delivery | Listar repartidores, cambiar estado y guardar fecha/hora; disponibilidad de delivery calculada con restaurante abierto y repartidor disponible. | Repartidores precargados; sin geolocalización en vivo. |
| HU-06 | Priorización de pedidos | Calcular y mostrar puntaje, factores y orden de pedidos activos conforme a la fórmula de la tesis. | Cálculo bajo demanda o al consultar, sin infraestructura de eventos. |
| HU-07 | Asignación y trazabilidad de entregas | Proponer/asignar repartidor disponible del mismo restaurante; actualizar estados de entrega y permitir seguimiento del cliente. | Distancia precargada o ajustable manualmente; sin Google Maps ni GPS. |
| HU-08 | Predicción de demanda y necesidades de stock | Ejecutar una predicción sencilla sobre historial sintético, mostrar estimación y métrica; convertirla en insumos requeridos usando recetas y compararlos con stock. | Modelo pequeño, entrenable y verificable; sin reentrenamiento automático complejo. |
| HU-09 | Indicadores y detección de anomalías | Indicadores por período y restaurante; alertas de preparación, entrega, importe y stock con valor, umbral y fecha. | Reglas de umbral, sin modelo adicional de detección. |
| HU-10 | Tablero operativo | Vista integrada con pedidos activos, alertas de stock, repartidores e incidencias, filtrada por restaurante. | Actualización al recargar o consultar; sin tiempo real por WebSockets. |
| HU-11 | Administración básica de la plataforma | Si queda tiempo, vista mínima de diagnóstico de cuentas para un administrador autorizado. | **No implementar acceso irrestricto** ni un módulo completo de soporte. Puede quedar fuera de esta demo sin alterar la HU de la tesis. |

## Reglas de negocio que no se deben cambiar

**HU-03 — Delivery:** el menú se consulta aunque no haya repartidores. Solo se confirma un pedido con delivery cuando el restaurante está abierto y tiene al menos un repartidor disponible.

**HU-04 — Stock:** el consumo por pedido e insumo se registra una sola vez al comenzar la preparación; una repetición explícita por preparación arruinada genera un nuevo descuento. Guardar actor y marca temporal del cambio de estado.

**HU-06 — Prioridad:** `P = T + D + G`, donde:
- `T`: minutos completos desde la creación del pedido, sin máximo.
- `D = max(0, 10 - distancia_km)`.
- `G = max(0, (importe_productos - costo_estimado_productos) / 1000)`, en pesos argentinos y admitiendo decimales.
- Orden descendente por `P`; empate por fecha de pedido más antigua y luego ID menor.

**HU-07 — Asignación:** procesar primero pedidos listos de mayor prioridad; seleccionar repartidores disponibles **del mismo restaurante** por menor carga asignada, luego mayor tasa de éxito y luego nombre alfabético. Permitir ajuste manual de distancia y conservar historial de entrega.

**HU-08 — Predicción:** exigir **al menos 7 días de registros y 10 pedidos completados** del restaurante; en caso contrario mostrar **«Historial insuficiente»**, sin predicción. Mostrar métrica de evaluación cuando corresponda.

**HU-09 — Alertas:** para preparación, entrega o importe, detectar valores que superen el promedio de referencia en **10 %**; alertar también si el stock resulta negativo. Mostrar indicador, valor observado, umbral y fecha. El cálculo del promedio debe estar definido y ser reproducible.

**Seguridad:** todo acceso operativo debe validar sesión, rol y pertenencia del recurso al restaurante. No confiar solo en filtros del frontend. Un cliente solo consulta sus propios pedidos.

## Recorrido mínimo de demostración

1. Iniciar sesión como cliente de prueba y consultar el menú de un restaurante.
2. Armar un carrito y confirmar un pedido válido.
3. Entrar como personal del restaurante; ver el pedido, su prioridad y comenzar la preparación.
4. Comprobar el descuento de stock y el historial de cambios.
5. Marcar pedido listo, asignar un repartidor disponible y actualizar la entrega.
6. Consultar el seguimiento desde el cliente.
7. Como propietario, ejecutar predicción de demanda, ver necesidades de insumos y alertas.
8. Consultar indicadores y una anomalía provocada mediante datos sintéticos de prueba.

## Datos sintéticos y pruebas mínimas

- Al menos dos restaurantes y usuarios con roles diferentes para verificar aislamiento.
- Menú, recetas, insumos y stock; pedidos con distintas fechas, distancias, importes y estados; repartidores disponibles y ocupados.
- Historial suficiente para una predicción válida y otro caso con historial insuficiente.
- Casos controlados de demora, importe anómalo, stock negativo, empate de prioridad y empate de repartidores.
- Probar: acceso cruzado denegado; pedido sin delivery disponible; consumo único; fórmula y desempates; asignación solo al mismo restaurante; predicción con/sin datos; alertas con umbral correcto.

## Criterio de finalización de la demo

La demo se considera lista para presentar cuando el recorrido anterior funciona de extremo a extremo con datos persistidos, los tres motores producen resultados reproducibles, las pruebas críticas pasan, existe una forma sencilla de iniciar la aplicación y se dispone de un enlace accesible a los recursos de demostración. **No afirmar que la plataforma completa está terminada.**

## Control de cambios por devolución docente

Cuando llegue el feedback de la profesora:
1. Registrar la observación concreta y la HU, regla o entidad afectada.
2. Compararla con la tesis vigente; no asumir que la observación obliga a rehacer todo.
3. Modificar solo el alcance y los componentes impactados.
4. Pedir a Codex que presente el impacto antes de cambiar código o base de datos.

**Nota para Codex:** antes de implementar, leer `AGENTS.md`, `DESIGN.md` y este documento; proponer un plan pequeño y no escribir código hasta recibir aprobación. No interpretar una simplificación de la demo como cambio a los requisitos de la tesis.
