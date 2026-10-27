-- HU-01: permisos exclusivos de las tablas de esta aplicación.
-- Ejecutado por el despliegue autorizado, dentro de su transacción con Alembic.
-- No modifica datos, columnas, relaciones, permisos por defecto ni otros esquemas.
-- Sin CASCADE: cualquier dependencia de grants detiene y revierte la operación.
REVOKE ALL PRIVILEGES ON TABLE
    public.restaurante,
    public.usuario,
    public.cliente,
    public.producto,
    public.insumo,
    public.receta_detalle,
    public.pedido,
    public.detalle_pedido,
    public.repartidor,
    public.historial_repartidor,
    public.entrega,
    public.historial_pedido,
    public.movimiento_stock,
    public.prediccion_demanda,
    public.alerta,
    public.alembic_version
FROM PUBLIC, anon, authenticated, service_role;
