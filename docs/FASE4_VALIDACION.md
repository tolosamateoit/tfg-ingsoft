# Fase 4: funcionamiento y experiencia de uso

Validación realizada el 31/10/2026 sobre el sistema existente. No se modificaron el DER, las migraciones, los motores analíticos ni los datos de la fase 3.

## Cambios

- Cada pestaña conserva un identificador opaco en `sessionStorage` (`oliva.tab`). El encabezado `X-Oliva-Tab` selecciona su cookie `tfg_session_<identificador>`. El token sigue en una cookie HttpOnly, con los mismos atributos de seguridad y vencimiento de ocho horas; PostgreSQL conserva el hash y la revocación existentes. Una pestaña nueva no adopta la cookie compartida anterior. Los clientes de API sin encabezado conservan la compatibilidad anterior.
- Web Locks evita que una pestaña duplicada con `sessionStorage` copiado adopte la sesión de otra pestaña activa. La recarga conserva el identificador. Sin Web Locks se mantiene el aislamiento de pestañas nuevas, pero no se garantiza el aislamiento al duplicarlas mediante la función del navegador.
- `GET /api/restaurantes/{id}/alertas` devuelve `{alertas, total, limit, offset}`; admite `tipo`, `estado` y `severidad`. La interfaz consulta 25 por página; la API valida límites de 1 a 100. El límite por respuesta no limita la cantidad total consultable. Se preservan permisos de propietario y aislamiento por restaurante.
- Como el modelo no contiene una columna de severidad, se deriva únicamente para presentación: **crítica** si hay stock negativo o el valor observado supera el doble del umbral; **advertencia** en los demás casos. Se aplican el mismo criterio a las tarjetas y al filtro SQL. Esto no crea, resuelve ni modifica alertas, sus umbrales o su deduplicación.
- Los instantes se muestran en horario local, con formato argentino de 24 horas. Las fechas de calendario se formatean sin convertirlas en instantes. Los períodos analíticos conservan el corte UTC validado en fase 3 y lo explican una vez, sin agregarlo a cada campo. Las distancias se muestran con dos decimales y los importes con formato monetario consistente.

## Verificaciones

| Verificación | Resultado |
| --- | --- |
| Regresión backend con PostgreSQL local descartable | 298 pruebas aprobadas; sin omisiones |
| Frontend: fechas, importes, distancias e identidad por pestaña | 4 pruebas aprobadas |
| TypeScript y compilación Vite | Aprobadas |
| Supabase: migración autorizada 0003 y restricciones | Verificadas, sin aplicar migraciones |
| Supabase: recorrido de todas las alertas del restaurante 3 | 901 IDs distintos en 37 páginas de hasta 25 registros |
| Distribución real por tipo | 278 importe, 278 preparación, 344 entrega, 1 stock |
| Clasificación visual derivada de los valores guardados | 48 críticas y 853 advertencias |
| Tablas de negocio de todos los restaurantes, antes/después | Huellas SHA-256 idénticas; incluye pedidos, stock, predicciones y alertas |
| Resultados fase 3 conservados | 2.407 pedidos y 6 predicciones; 15 insumos y 14 con necesidad pronosticada, sin regeneración |

Las únicas escrituras en Supabase durante la comprobación fueron las técnicas de login/logout de la cuenta dedicada; no se ejecutaron el dashboard ni los controles analíticos sobre esa base. La evidencia privada de la lectura y las huellas está en `.tools/phase4-live-validation.json`.

En Brave se verificaron los cuatro perfiles simultáneamente en pestañas del mismo navegador, navegación, recarga y cierre de sesión independiente. Se completó un pedido en la base SQLite **descartable** de QA: compra del cliente → preparación con dos movimientos de consumo → listo → asignación → en camino → entregado. La distancia persistida se mostró como `4,03 km` en pedido y entrega. Después de cerrar la sesión de personal, el cliente conservó su sesión al recargar y pudo consultar el pedido entregado. También se comprobaron las tarjetas rojas, la segunda página y los tres filtros combinados de alertas en QA. Los importes no nulos y las reglas de costos, disponibilidad, predicciones, faltantes y aislamiento están cubiertos por la regresión automatizada.

## Repetir la validación

Desde `backend/`, con Docker disponible:

```powershell
.\.venv\Scripts\python.exe -m tests.run_postgresql_local discover -s tests -v
```

Desde `frontend/`:

```powershell
npm test
npm run build
```

En el navegador, abrir la dirección de la demo en varias pestañas e ingresar con perfiles distintos. Recargar una, navegar y cerrar su sesión; las demás deben conservar sus perfiles. Como propietario, abrir **Indicadores y alertas**, combinar filtros y usar **Más alertas** / **Alertas anteriores**. La consulta de alertas guardadas no ejecuta los motores.

Limitaciones conservadas: los resúmenes del dashboard muestran una selección acotada; el listado completo se consulta desde Indicadores y alertas. Los cortes diarios analíticos siguen siendo UTC. La comprobación de pestañas se realizó en Brave; la duplicación depende del soporte de Web Locks indicado arriba.
