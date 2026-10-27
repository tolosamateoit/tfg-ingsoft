# HU-03 — Registro y consulta de pedidos

Decisiones confirmadas el 27/10/2026: totales de productos sin cargos de envío;
distancia estimada manual ingresada por personal/propietario al registrar.

Implementado: productos activos y cantidades, cliente precargado identificado por
correo, dirección, referencia/zona opcionales y medio de pago. FastAPI calcula
importe y costo, valida restaurante abierto y repartidor disponible del mismo
restaurante y guarda pedido, detalles e historial inicial en una transacción.
Personal/propietario consultan su restaurante; el cliente consulta menú y pedidos propios.
Estado inicial `Nuevo`, pago `pendiente`; sin cambios de estado en HU-03.

Sin cambios al DER, nuevas migraciones, stock, priorización ni asignación.
Pruebas con SQLite y PostgreSQL local descartable; Supabase no fue modificado.

Verificación: iniciar la API habitual y React, ingresar como personal o propietario,
abrir Pedidos, usar `cliente@prueba.com`, dirección, distancia, medio de pago y
cantidades. Confirmar, anotar el número y recargar para comprobar persistencia.
Como cliente, consultar Mis pedidos. En Supabase revisar `pedido`, `detalle_pedido`
y `historial_pedido` por ese `id_pedido`.
