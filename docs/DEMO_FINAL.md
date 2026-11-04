# Demo académica simplificada

La consolidación puntual dejó Rotisería del Pueblo en el ID 1 y conservó 4.834
pedidos con sus fechas, estados, importes y costos históricos. Se mantienen los
identificadores de productos, insumos, recetas, movimientos y entregas: productos
con nombres similares no se fusionaron para evitar alterar sus antecedentes.

Las cuentas conservadas son Lucía Fernández (propietaria), Martín Acosta
(personal), Valentina López (cliente), Diego Ramírez, Ana Martínez y Elena Vázquez
(repartidores). Las credenciales de acceso rápido permanecen en el archivo privado
de desarrollo del frontend; no se incorporan al bundle de producción.

`python -m app.demo_history.consolidate` verifica la transformación completa con
rollback; `--execute` confirma. Esta herramienta es exclusiva de la preparación
de datos inspeccionados, no una migración ni una regla de negocio. Comprueba el
esquema, bloquea las tablas y reconstruye relaciones en una sola transacción,
sin desactivar triggers ni FK y sin generar respaldos. Conserva el actor original
en el texto de eventos cuyo usuario fue reasignado. Las sesiones anteriores se
invalidan y los accesos locales se actualizan al finalizar.

## Operación

- La simulación inicia con FastAPI en el entorno local ya definido por la
  configuración de autenticación (cookies de desarrollo y orígenes loopback).
  No hay un interruptor adicional. Los pedidos creados allí reciben una marca
  en su evento de registro; los históricos carecen de esa marca.
- El worker usa un reloj monotónico, intervalos de 15 a 25 segundos y un lock
  PostgreSQL de sesión para que un solo proceso avance los pedidos. Descubre
  trabajo cada 30 segundos. Al reiniciar comienza un nuevo intervalo de etapa:
  el tiempo apagado no provoca avances. No cambia la fecha operativa.
- Las transiciones reutilizan preparación, consumo y entrega transaccionales.
  Se admite intervención manual; stock insuficiente, distancia no confirmada o
  falta de repartidor dejan el pedido esperando. No se inventan existencias ni
  kilómetros. El estado interno Asignado se conserva antes de En camino.
- Cada estado tiene su propio plazo de simulación. El despacho automático solo
  incluye pedidos cuyo plazo de listo ya venció; si una acción manual cambió el
  estado, el worker vuelve a iniciar el plazo correspondiente.
- El despacho automático toma primero el mayor puntaje de prioridad y después
  el repartidor disponible con mayor proporción de entregas exitosas. Sin
  antecedentes se considera tasa cero; los empates se ordenan por nombre.
  Un repartidor con entrega activa no puede recibir otra incompatible.
- Entregado confirma el pago en la misma transacción y registra esa confirmación
  en el evento de entrega, sin duplicar pagos ante reintentos.
- Solo el repartidor puede editar su disponibilidad. El propietario consulta
  todos los integrantes del equipo con un indicador verde o rojo.
- El historial de pedidos permite filtrar por día de Buenos Aires y mantiene
  paginación y orden descendente. Los repartidores consultan solo sus pedidos;
  su vista operativa muestra únicamente repartos activos.
- El costo de receta suma cantidad por costo del insumo, usando la misma unidad
  registrada. Cambiar la receta o el costo de un insumo recalcula productos sin
  modificar costos históricos de pedidos. Los envasados utilizan equivalencia
  de inventario (por ejemplo, una botella por producto). Completar la receta o
  equivalencia antes de preparar un producto nuevo.
- Stock ofrece agregar y restar con cantidades positivas en pantalla; internamente
  conserva reposición, ajuste y consumo. Tanto ajustes como preparación rechazan
  resultados negativos. El motivo es opcional y se conserva el usuario responsable.
- Los pedidos nuevos reservan las cantidades de sus recetas hasta su preparación
  o cancelación. La disponibilidad descuenta esas reservas y suma los insumos
  compartidos por productos del mismo pedido. Movimientos y cambios de receta
  no pueden comprometer lo ya reservado. Los productos sin receta o equivalencia
  quedan no disponibles. El estado administrativo permanece independiente.
- El detalle reconstruye el saldo anterior y posterior de cada consumo a partir
  del stock y los movimientos posteriores por orden de registro. No modifica
  movimientos históricos; presupone que los cambios de stock están registrados.

El esquema y la autorización continúan siendo multi-restaurante. Ningún servicio
de negocio selecciona el restaurante 1 por defecto ni fija límites de usuarios.

## Validación

Las pruebas `test_demo_final` cubren costo derivado, protección de historia,
stock, filtros, pago idempotente, alcance local y worker sin navegador. Se
ejecutan también con PostgreSQL local y las migraciones reales. La herramienta
`python -m tests.verify_final_demo_live` comprueba los seis accesos y consulta
historial, predicciones, indicadores, alertas y prioridades de la base de demo.
No crea pedidos de prueba en la base real.

En esta intervención se verificaron los seis accesos a través de Vite/FastAPI y
un único worker activo. Los servidores existentes cargaron los cambios mediante
recarga de desarrollo. Si se ejecutan sin recarga, reiniciarlos después de actualizar
para cargar el lifespan del backend y las seis cuentas locales de Vite.

Pasaron 31 pruebas del frontend, la compilación TypeScript/Vite, la suite general
del backend (208 ejecutadas; las pruebas que requieren PostgreSQL se omiten en
esa ejecución) y las suites pertinentes con PostgreSQL local descartable. La
consulta real verificó 16 productos en la previsión del catálogo consolidado.
La revisión visual manual quedó pendiente por un fallo de la conexión de
automatización al navegador; no se presenta como verificada.
