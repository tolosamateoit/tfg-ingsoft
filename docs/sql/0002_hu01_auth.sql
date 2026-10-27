-- HU-01: SOLO PARA REVISION. NO APLICADO A SUPABASE.
BEGIN;

-- Running upgrade 0001_der_inicial -> 0002_hu01_auth

CREATE TABLE public.auth_estado_acceso (
    clave_correo TEXT NOT NULL, 
    intentos_fallidos INTEGER NOT NULL, 
    bloqueado_hasta TIMESTAMP WITH TIME ZONE, 
    actualizado_en TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_auth_estado_acceso PRIMARY KEY (clave_correo), 
    CONSTRAINT ck_auth_estado_acceso_hash_hexadecimal CHECK (clave_correo ~ '^[0-9a-f]{64}$'), 
    CONSTRAINT ck_auth_estado_acceso_intentos_rango CHECK (intentos_fallidos BETWEEN 0 AND 5)
);

CREATE INDEX ix_auth_estado_acceso_actualizado_en ON public.auth_estado_acceso (actualizado_en);

CREATE TABLE public.auth_sesion (
    token_hash TEXT NOT NULL, 
    id_usuario INTEGER NOT NULL, 
    creada_en TIMESTAMP WITH TIME ZONE NOT NULL, 
    expira_en TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_auth_sesion PRIMARY KEY (token_hash), 
    CONSTRAINT fk_auth_sesion_id_usuario_usuario FOREIGN KEY(id_usuario) REFERENCES public.usuario (id_usuario) ON DELETE RESTRICT ON UPDATE RESTRICT, 
    CONSTRAINT ck_auth_sesion_hash_hexadecimal CHECK (token_hash ~ '^[0-9a-f]{64}$'), 
    CONSTRAINT ck_auth_sesion_vencimiento_valido CHECK (expira_en > creada_en)
);

CREATE INDEX ix_auth_sesion_id_usuario ON public.auth_sesion (id_usuario);

CREATE INDEX ix_auth_sesion_expira_en ON public.auth_sesion (expira_en);

ALTER TABLE public.auth_estado_acceso ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.auth_estado_acceso FROM PUBLIC, anon, authenticated, service_role;

ALTER TABLE public.auth_sesion ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.auth_sesion FROM PUBLIC, anon, authenticated, service_role;

UPDATE public.alembic_version SET version_num='0002_hu01_auth' WHERE public.alembic_version.version_num = '0001_der_inicial';

COMMIT;

