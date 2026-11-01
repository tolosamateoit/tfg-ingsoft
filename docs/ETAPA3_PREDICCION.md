# HU-08 — validación de la etapa 3

Implementación vigente: promedio diario frente a promedio por día de semana,
por producto activo, sin nuevas dependencias, tablas ni migraciones. Sustituye
la regresión lineal y el corte UTC descritos anteriormente en HU08_HU09.md.

- Fecha operativa obtenida del servicio centralizado y contexto autorizado.
  Se considera cerrado ese día local (Buenos Aires); horizonte: siguientes 7 días.
- Solo pedidos Entregado; suma de cantidades, días calendario sin ventas en cero
  desde el primer pedido entregado. No se infiere demanda no atendida.
- Mínimo 35 días y 10 pedidos. Últimas dos semanas separadas: primera para
  comparar métodos, segunda para MAE independiente. Entrenamiento siempre
  anterior al bloque pronosticado; empate favorece promedio diario.
- Después de evaluar se ajusta el método seleccionado con todo el historial.
  El MAE no es porcentaje ni intervalo de confianza; mide unidades/producto/día.
- Metadatos, siete cantidades diarias y evidencia se conservan en el campo Text
  modelo existente. Predicciones antiguas se leen indicando que deben regenerarse.
- Las recetas suman ingredientes compartidos una sola vez por producto. Se exige
  coincidencia de unidades y restaurante. Bebidas usan sus recetas existentes.
  Faltante = máximo(0, necesidad - stock); unidades indivisibles se reponen
  redondeando hacia arriba. No se modifican existencias, recetas ni pedidos.
- Asociación: al menos 30 pedidos, 10 conjuntos, soporte 5 %, antecedente
  20 pedidos, confianza 50 % y lift 1,2. Presencia por pedido, sin multiplicar por
  cantidad. Son asociaciones descriptivas; no causalidad ni recomendación de venta.

## Comprobación real de solo lectura (31/10/2026)

`python -m tests.verify_forecast_live` abre una transacción READ ONLY en Supabase,
verifica propietario activo del restaurante 2 y no guarda predicciones.
90 días, 2330 pedidos entregados, 10 productos, 19 insumos, sin recetas faltantes.
Horizonte 01/11/2026–07/11/2026. MAE agregado: **4,359706** sobre **70 observaciones**.
Cuatro productos eligieron promedio por día de semana, seis promedio diario.
Referencia simple en la misma semana de prueba: MAE **5,154733**.
La auditoría Decimal independiente confirmó MAE y totales de los diez productos.
El historial es sintético: estos resultados no acreditan precisión comercial.
La evaluación independiente abarca una semana y no garantiza resultados futuros.
No se conocen las fechas de alta de productos: ceros anteriores a sus primeras
ventas se interpretan como ausencia de ventas dentro del historial observado.

## Verificación reproducible

- `python -m unittest tests.test_forecast_hu08 tests.test_analytics -q`
- `python -m unittest tests.test_experiment tests.test_dashboard -q` (compatibilidad de consumidores existentes).
- `python ../.tools/run_phase3_regression.py tests.test_analytics_postgresql.ForecastPostgreSQLTests -q`
- `npm test` y `npm run build` desde frontend.
- La prueba React renderiza una respuesta calculada en SQLite por el backend;
  comprueba período, siete cantidades, MAE, necesidades y reposición.
