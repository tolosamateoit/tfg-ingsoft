# HU-03 — Registro y consulta de pedidos

Fuentes revisadas: Tabla 10 de la tesis vigente, `AGENTS.md`, `CONTEXTO_TESIS.md`,
`ALCANCE_DEMO.md`, `DESIGN.md`, DER y migraciones existentes.

## Implementación prevista

1. Consultar restaurantes y productos activos como cliente, aunque el delivery no esté disponible.
2. Confirmar el carrito desde FastAPI usando el cliente de la sesión y los precios y costos de PostgreSQL.
3. Validar restaurante abierto y al menos un repartidor activo y disponible de ese restaurante.
4. Guardar cabecera, detalles e historial inicial en una única transacción, respetando los triggers existentes.
5. Consultar pedidos propios como cliente y pedidos del restaurante como personal/propietario.
6. Incorporar carrito, formulario y consulta en React; probar permisos, importes, integridad y concurrencia.

Sin cambios al DER ni migraciones nuevas. Sin descuento de stock, priorización,
asignación de repartidores, geolocalización ni pasarela de pagos.

## Decisiones consultadas, pendientes de respuesta

- Confirmar que `importe_total` suma precios por cantidades y `costo_total` suma
  costos unitarios por cantidades, sin incorporar cargos de delivery en HU-03.
  La tesis define la ganancia de productos en HU-06, pero no precisa un cargo al cliente por envío.
- Confirmar el ingreso manual de una distancia estimada al registrar el pedido.
  `pedido.distancia_km` es obligatorio en el DER. El alcance excluye Google Maps/GPS
  y prevé distancia precargada o ajustable manualmente en HU-07.

Estas decisiones no se consideran aprobadas por defecto.

## Avance

Preparadas las consultas de menú, disponibilidad y pedidos con aislamiento por rol.
El router todavía no está incorporado a `app.main`: la creación de pedidos y la
interfaz quedan pendientes de resolver las dos decisiones anteriores.
Las pruebas se ejecutan con datos sintéticos en SQLite y PostgreSQL local
descartable; no se modifican datos ni estructura de Supabase.
