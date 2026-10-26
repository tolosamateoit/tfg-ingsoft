-- Instantánea de las reglas de integridad de la revisión 0001.
-- No ejecutar directamente: Alembic controla la transacción y la versión.

-- alembic:statement
CREATE FUNCTION public.tfg_bloquear_relaciones() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    -- La demo serializa solo escrituras de relaciones, no cambios de precios,
    -- estados, stock o lecturas. No requiere tablas ni atributos adicionales.
    -- Las consultas posteriores al lock deben usar snapshots renovados.
    IF current_setting('transaction_isolation') NOT IN ('read committed', 'read uncommitted') THEN
        RAISE EXCEPTION USING ERRCODE = '0A000',
            MESSAGE = 'Los cambios de relaciones requieren aislamiento READ COMMITTED';
    END IF;
    PERFORM pg_advisory_xact_lock(1647042, 1);
    RETURN NULL;
END;
$$;

-- alembic:statement
CREATE FUNCTION public.tfg_validar_relacion() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    restaurante_a integer;
    restaurante_b integer;
    usuario_cliente integer;
BEGIN
    CASE TG_TABLE_NAME
    WHEN 'receta_detalle' THEN
        SELECT id_restaurante INTO restaurante_a FROM public.producto WHERE id_producto = NEW.id_producto;
        SELECT id_restaurante INTO restaurante_b FROM public.insumo WHERE id_insumo = NEW.id_insumo;
    WHEN 'detalle_pedido' THEN
        SELECT id_restaurante INTO restaurante_a FROM public.pedido WHERE id_pedido = NEW.id_pedido;
        SELECT id_restaurante INTO restaurante_b FROM public.producto WHERE id_producto = NEW.id_producto;
    WHEN 'movimiento_stock' THEN
        IF NEW.id_pedido IS NULL THEN RETURN NEW; END IF;
        SELECT id_restaurante INTO restaurante_a FROM public.pedido WHERE id_pedido = NEW.id_pedido;
        SELECT id_restaurante INTO restaurante_b FROM public.insumo WHERE id_insumo = NEW.id_insumo;
    WHEN 'entrega' THEN
        SELECT id_restaurante INTO restaurante_a FROM public.pedido WHERE id_pedido = NEW.id_pedido;
        SELECT u.id_restaurante INTO restaurante_b
          FROM public.repartidor r JOIN public.usuario u ON u.id_usuario = r.id_usuario
         WHERE r.id_repartidor = NEW.id_repartidor;
    WHEN 'repartidor' THEN
        SELECT id_restaurante INTO restaurante_a FROM public.usuario WHERE id_usuario = NEW.id_usuario;
        restaurante_b := restaurante_a;
    WHEN 'historial_pedido' THEN
        SELECT p.id_restaurante, c.id_usuario INTO restaurante_a, usuario_cliente
          FROM public.pedido p JOIN public.cliente c ON c.id_cliente = p.id_cliente
         WHERE p.id_pedido = NEW.id_pedido;
        SELECT id_restaurante INTO restaurante_b FROM public.usuario WHERE id_usuario = NEW.id_usuario;
        IF usuario_cliente = NEW.id_usuario THEN RETURN NEW; END IF;
    ELSE
        RAISE EXCEPTION 'Tabla de relación no contemplada';
    END CASE;

    IF restaurante_a IS NULL OR restaurante_b IS NULL OR restaurante_a <> restaurante_b THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            CONSTRAINT = 'ck_pertenencia_restaurante',
            MESSAGE = 'Las referencias deben corresponder al mismo restaurante o al cliente del pedido';
    END IF;
    RETURN NEW;
END;
$$;

-- alembic:statement
CREATE FUNCTION public.tfg_validar_cambio_origen() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    CASE TG_TABLE_NAME
    WHEN 'producto' THEN
        IF NEW.id_restaurante IS NOT DISTINCT FROM OLD.id_restaurante THEN RETURN NEW; END IF;
        IF EXISTS (
            SELECT 1 FROM public.receta_detalle rd JOIN public.insumo i USING (id_insumo)
             WHERE rd.id_producto = NEW.id_producto AND i.id_restaurante <> NEW.id_restaurante
        ) OR EXISTS (
            SELECT 1 FROM public.detalle_pedido d JOIN public.pedido p USING (id_pedido)
             WHERE d.id_producto = NEW.id_producto AND p.id_restaurante <> NEW.id_restaurante
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'El cambio deja productos vinculados a otro restaurante';
        END IF;
    WHEN 'insumo' THEN
        IF NEW.id_restaurante IS NOT DISTINCT FROM OLD.id_restaurante THEN RETURN NEW; END IF;
        IF EXISTS (
            SELECT 1 FROM public.receta_detalle rd JOIN public.producto p USING (id_producto)
             WHERE rd.id_insumo = NEW.id_insumo AND p.id_restaurante <> NEW.id_restaurante
        ) OR EXISTS (
            SELECT 1 FROM public.movimiento_stock m JOIN public.pedido p USING (id_pedido)
             WHERE m.id_insumo = NEW.id_insumo AND p.id_restaurante <> NEW.id_restaurante
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'El cambio deja insumos vinculados a otro restaurante';
        END IF;
    WHEN 'pedido' THEN
        IF NEW.id_restaurante IS NOT DISTINCT FROM OLD.id_restaurante
           AND NEW.id_cliente IS NOT DISTINCT FROM OLD.id_cliente THEN RETURN NEW; END IF;
        IF EXISTS (
            SELECT 1 FROM public.detalle_pedido d JOIN public.producto p USING (id_producto)
             WHERE d.id_pedido = NEW.id_pedido AND p.id_restaurante <> NEW.id_restaurante
        ) OR EXISTS (
            SELECT 1 FROM public.movimiento_stock m JOIN public.insumo i USING (id_insumo)
             WHERE m.id_pedido = NEW.id_pedido AND i.id_restaurante <> NEW.id_restaurante
        ) OR EXISTS (
            SELECT 1 FROM public.entrega e JOIN public.repartidor r USING (id_repartidor)
              JOIN public.usuario u ON u.id_usuario = r.id_usuario
             WHERE e.id_pedido = NEW.id_pedido AND u.id_restaurante IS DISTINCT FROM NEW.id_restaurante
        ) OR EXISTS (
            SELECT 1 FROM public.historial_pedido h JOIN public.usuario u USING (id_usuario)
             WHERE h.id_pedido = NEW.id_pedido
               AND u.id_restaurante IS DISTINCT FROM NEW.id_restaurante
               AND NOT EXISTS (SELECT 1 FROM public.cliente c
                                WHERE c.id_cliente = NEW.id_cliente AND c.id_usuario = h.id_usuario)
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'El cambio deja referencias incompatibles con el pedido';
        END IF;
    WHEN 'usuario' THEN
        IF NEW.id_restaurante IS NOT DISTINCT FROM OLD.id_restaurante THEN RETURN NEW; END IF;
        IF (NEW.id_restaurante IS NULL AND EXISTS (
            SELECT 1 FROM public.repartidor WHERE id_usuario = NEW.id_usuario
        )) OR EXISTS (
            SELECT 1 FROM public.entrega e JOIN public.repartidor r USING (id_repartidor)
              JOIN public.pedido p USING (id_pedido)
             WHERE r.id_usuario = NEW.id_usuario AND p.id_restaurante IS DISTINCT FROM NEW.id_restaurante
        ) OR EXISTS (
            SELECT 1 FROM public.historial_pedido h JOIN public.pedido p USING (id_pedido)
              JOIN public.cliente c ON c.id_cliente = p.id_cliente
             WHERE h.id_usuario = NEW.id_usuario
               AND p.id_restaurante IS DISTINCT FROM NEW.id_restaurante
               AND c.id_usuario <> NEW.id_usuario
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'El cambio de usuario deja referencias incompatibles';
        END IF;
    WHEN 'repartidor' THEN
        IF NEW.id_usuario IS NOT DISTINCT FROM OLD.id_usuario THEN RETURN NEW; END IF;
        IF EXISTS (
            SELECT 1 FROM public.entrega e JOIN public.pedido p USING (id_pedido)
              JOIN public.usuario u ON u.id_usuario = NEW.id_usuario
             WHERE e.id_repartidor = NEW.id_repartidor AND p.id_restaurante IS DISTINCT FROM u.id_restaurante
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'El cambio de repartidor deja entregas de otro restaurante';
        END IF;
    WHEN 'cliente' THEN
        IF NEW.id_usuario IS NOT DISTINCT FROM OLD.id_usuario THEN RETURN NEW; END IF;
        IF EXISTS (
            SELECT 1 FROM public.historial_pedido h JOIN public.pedido p USING (id_pedido)
              JOIN public.usuario u ON u.id_usuario = h.id_usuario
             WHERE p.id_cliente = NEW.id_cliente AND h.id_usuario <> NEW.id_usuario
               AND u.id_restaurante IS DISTINCT FROM p.id_restaurante
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'El cambio de cliente deja actores del historial incompatibles';
        END IF;
    END CASE;
    RETURN NEW;
END;
$$;

-- alembic:statement
CREATE FUNCTION public.tfg_validar_detalles_pedido() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    pedido_id integer;
BEGIN
    IF TG_TABLE_NAME = 'pedido' THEN
        pedido_id := NEW.id_pedido;
    ELSE
        pedido_id := OLD.id_pedido;
    END IF;
    IF EXISTS (SELECT 1 FROM public.pedido WHERE id_pedido = pedido_id)
       AND NOT EXISTS (SELECT 1 FROM public.detalle_pedido WHERE id_pedido = pedido_id) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'ck_pedido_con_detalles',
            MESSAGE = 'Un pedido debe tener al menos un detalle al finalizar la transacción';
    END IF;
    RETURN NULL;
END;
$$;

-- alembic:statement
CREATE FUNCTION public.tfg_rechazar_truncate_detalles() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Usar DELETE transaccional para conservar la integridad de pedidos';
END;
$$;

-- Locks ANTES de que la sentencia adquiera locks de filas: evita escrituras
-- concurrentes que por separado parezcan válidas y juntas rompan la pertenencia.
-- alembic:statement
CREATE TRIGGER tfg_lock_producto BEFORE INSERT OR DELETE OR UPDATE OF id_restaurante ON public.producto FOR EACH STATEMENT EXECUTE FUNCTION public.tfg_bloquear_relaciones();
-- alembic:statement
CREATE TRIGGER tfg_lock_insumo BEFORE INSERT OR DELETE OR UPDATE OF id_restaurante ON public.insumo FOR EACH STATEMENT EXECUTE FUNCTION public.tfg_bloquear_relaciones();
-- alembic:statement
CREATE TRIGGER tfg_lock_usuario BEFORE INSERT OR DELETE OR UPDATE OF id_restaurante ON public.usuario FOR EACH STATEMENT EXECUTE FUNCTION public.tfg_bloquear_relaciones();
-- alembic:statement
CREATE TRIGGER tfg_lock_cliente BEFORE INSERT OR DELETE OR UPDATE OF id_usuario ON public.cliente FOR EACH STATEMENT EXECUTE FUNCTION public.tfg_bloquear_relaciones();
-- alembic:statement
CREATE TRIGGER tfg_lock_pedido BEFORE INSERT OR DELETE OR UPDATE OF id_restaurante, id_cliente ON public.pedido FOR EACH STATEMENT EXECUTE FUNCTION public.tfg_bloquear_relaciones();
-- alembic:statement
CREATE TRIGGER tfg_lock_repartidor BEFORE INSERT OR DELETE OR UPDATE OF id_usuario ON public.repartidor FOR EACH STATEMENT EXECUTE FUNCTION public.tfg_bloquear_relaciones();
-- alembic:statement
CREATE TRIGGER tfg_lock_receta BEFORE INSERT OR DELETE OR UPDATE OF id_producto, id_insumo ON public.receta_detalle FOR EACH STATEMENT EXECUTE FUNCTION public.tfg_bloquear_relaciones();
-- alembic:statement
CREATE TRIGGER tfg_lock_detalle BEFORE INSERT OR DELETE OR UPDATE OF id_pedido, id_producto ON public.detalle_pedido FOR EACH STATEMENT EXECUTE FUNCTION public.tfg_bloquear_relaciones();
-- alembic:statement
CREATE TRIGGER tfg_lock_entrega BEFORE INSERT OR DELETE OR UPDATE OF id_pedido, id_repartidor ON public.entrega FOR EACH STATEMENT EXECUTE FUNCTION public.tfg_bloquear_relaciones();
-- alembic:statement
CREATE TRIGGER tfg_lock_movimiento BEFORE INSERT OR DELETE OR UPDATE OF id_pedido, id_insumo ON public.movimiento_stock FOR EACH STATEMENT EXECUTE FUNCTION public.tfg_bloquear_relaciones();
-- alembic:statement
CREATE TRIGGER tfg_lock_historial BEFORE INSERT OR DELETE OR UPDATE OF id_pedido, id_usuario ON public.historial_pedido FOR EACH STATEMENT EXECUTE FUNCTION public.tfg_bloquear_relaciones();

-- alembic:statement
CREATE TRIGGER tfg_validar_receta BEFORE INSERT OR UPDATE OF id_producto, id_insumo ON public.receta_detalle FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_relacion();
-- alembic:statement
CREATE TRIGGER tfg_validar_detalle BEFORE INSERT OR UPDATE OF id_pedido, id_producto ON public.detalle_pedido FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_relacion();
-- alembic:statement
CREATE TRIGGER tfg_validar_entrega BEFORE INSERT OR UPDATE OF id_pedido, id_repartidor ON public.entrega FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_relacion();
-- alembic:statement
CREATE TRIGGER tfg_validar_movimiento BEFORE INSERT OR UPDATE OF id_pedido, id_insumo ON public.movimiento_stock FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_relacion();
-- alembic:statement
CREATE TRIGGER tfg_validar_repartidor BEFORE INSERT OR UPDATE OF id_usuario ON public.repartidor FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_relacion();
-- alembic:statement
CREATE TRIGGER tfg_validar_historial BEFORE INSERT OR UPDATE OF id_pedido, id_usuario ON public.historial_pedido FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_relacion();

-- alembic:statement
CREATE TRIGGER tfg_origen_producto BEFORE UPDATE OF id_restaurante ON public.producto FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_cambio_origen();
-- alembic:statement
CREATE TRIGGER tfg_origen_insumo BEFORE UPDATE OF id_restaurante ON public.insumo FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_cambio_origen();
-- alembic:statement
CREATE TRIGGER tfg_origen_pedido BEFORE UPDATE OF id_restaurante, id_cliente ON public.pedido FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_cambio_origen();
-- alembic:statement
CREATE TRIGGER tfg_origen_usuario BEFORE UPDATE OF id_restaurante ON public.usuario FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_cambio_origen();
-- alembic:statement
CREATE TRIGGER tfg_origen_cliente BEFORE UPDATE OF id_usuario ON public.cliente FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_cambio_origen();
-- alembic:statement
CREATE TRIGGER tfg_origen_repartidor BEFORE UPDATE OF id_usuario ON public.repartidor FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_cambio_origen();

-- alembic:statement
CREATE CONSTRAINT TRIGGER tfg_pedido_con_detalles AFTER INSERT OR UPDATE OF id_pedido ON public.pedido
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_detalles_pedido();
-- alembic:statement
CREATE CONSTRAINT TRIGGER tfg_detalle_preserva_pedido AFTER DELETE OR UPDATE OF id_pedido ON public.detalle_pedido
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.tfg_validar_detalles_pedido();
-- alembic:statement
CREATE TRIGGER tfg_no_truncate_detalles BEFORE TRUNCATE ON public.detalle_pedido
FOR EACH STATEMENT EXECUTE FUNCTION public.tfg_rechazar_truncate_detalles();

-- alembic:statement
REVOKE ALL ON FUNCTION public.tfg_bloquear_relaciones() FROM PUBLIC;
-- alembic:statement
REVOKE ALL ON FUNCTION public.tfg_validar_relacion() FROM PUBLIC;
-- alembic:statement
REVOKE ALL ON FUNCTION public.tfg_validar_cambio_origen() FROM PUBLIC;
-- alembic:statement
REVOKE ALL ON FUNCTION public.tfg_validar_detalles_pedido() FROM PUBLIC;
-- alembic:statement
REVOKE ALL ON FUNCTION public.tfg_rechazar_truncate_detalles() FROM PUBLIC;
