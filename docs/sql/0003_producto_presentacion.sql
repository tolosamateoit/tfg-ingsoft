-- SOLO PARA REVISION. NO APLICADO A SUPABASE.
BEGIN;

-- Running upgrade 0002_hu01_auth -> 0003_producto_presentacion

ALTER TABLE public.producto ADD COLUMN descripcion TEXT;

ALTER TABLE public.producto ADD COLUMN imagen_url TEXT;

UPDATE public.alembic_version SET version_num='0003_producto_presentacion' WHERE public.alembic_version.version_num = '0002_hu01_auth';

COMMIT;

