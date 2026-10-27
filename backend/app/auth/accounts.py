"""Generador OFFLINE de SQL sintético. No importa configuración ni conecta a DB.

Uso: python -m app.auth.accounts --output demo-auth.sql
La contraseña se solicita sin eco y no se incluye en el archivo.
"""

import argparse
import getpass
from pathlib import Path

from app.auth.security import hash_password


def demo_sql(password: str) -> str:
    accounts = [
        ("personal1", "personal", "r1"), ("personal2", "personal", "r2"),
        ("propietario1", "propietario", "r1"), ("propietario2", "propietario", "r2"),
        ("cliente1", "cliente", "NULL"), ("cliente2", "cliente", "NULL"),
        ("repartidor1", "repartidor", "r1"), ("repartidor2", "repartidor", "r2"),
        ("administrador", "administrador_plataforma", "NULL"),
    ]
    statements = []
    for name, role, restaurant in accounts:
        # Una sal diferente por cuenta, incluso cuando usan la misma clave de demo.
        encoded = hash_password(password)
        statements.append(
            "    INSERT INTO public.usuario (id_restaurante, correo, nombre, hash_contrasena, rol, activo) "
            f"VALUES ({restaurant}, '{name}@demo.invalid', 'Sintético {name}', '{encoded}', '{role}', true);"
        )
        if role == "cliente":
            statements.append(
                "    INSERT INTO public.cliente (id_usuario, nombre) "
                f"SELECT id_usuario, nombre FROM public.usuario WHERE correo='{name}@demo.invalid';"
            )
        if role == "repartidor":
            statements.append(
                "    INSERT INTO public.repartidor (id_usuario, estado_disponibilidad) "
                f"SELECT id_usuario, 'Disponible' FROM public.usuario WHERE correo='{name}@demo.invalid';"
            )
    return """-- DATOS SINTÉTICOS HU-01. Revisar antes de ejecutar. No contiene contraseñas en claro.
-- NO se ejecuta automáticamente. Crea 2 restaurantes y 9 usuarios con sus perfiles.
BEGIN;
DO $demo$
DECLARE r1 integer; r2 integer;
BEGIN
    IF EXISTS (SELECT 1 FROM public.usuario WHERE correo IN (
        'personal1@demo.invalid','personal2@demo.invalid','propietario1@demo.invalid',
        'propietario2@demo.invalid','cliente1@demo.invalid','cliente2@demo.invalid',
        'repartidor1@demo.invalid','repartidor2@demo.invalid','administrador@demo.invalid'
    )) THEN
        RAISE EXCEPTION 'Ya existen cuentas sintéticas HU-01; no se sobrescribieron';
    END IF;
    INSERT INTO public.restaurante (nombre,direccion,horario_atencion,abierto,costo_fijo_entrega,costo_por_km)
        VALUES ('Restaurante sintético 1','Dirección sintética 1','Demo',true,0,0) RETURNING id_restaurante INTO r1;
    INSERT INTO public.restaurante (nombre,direccion,horario_atencion,abierto,costo_fijo_entrega,costo_por_km)
        VALUES ('Restaurante sintético 2','Dirección sintética 2','Demo',true,0,0) RETURNING id_restaurante INTO r2;
""" + "\n".join(statements) + "\nEND;\n$demo$;\nCOMMIT;\n"


def main():
    parser = argparse.ArgumentParser(description="Generar SQL de cuentas sintéticas sin conectar a PostgreSQL.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("El archivo ya existe; elegí otra ruta para no sobrescribirlo.")
    password = getpass.getpass("Contraseña de las cuentas sintéticas (15–20 caracteres): ")
    if password != getpass.getpass("Repetí la contraseña: "):
        parser.error("Las contraseñas no coinciden.")
    try:
        sql = demo_sql(password)
    except ValueError as error:
        parser.error(str(error))
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        output.write(sql)
    print("SQL sintético generado localmente. No se ejecutó ninguna escritura en la base de datos.")


if __name__ == "__main__":
    main()
