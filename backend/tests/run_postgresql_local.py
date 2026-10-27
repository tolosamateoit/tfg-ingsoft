"""Entorno descartable Docker/PostgreSQL para la suite completa, sin Supabase.

Desde backend/: python -m tests.run_postgresql_local
No lee .env. No usa volúmenes persistentes. Detiene solo su propio contenedor.
"""

import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

BACKEND = Path(__file__).resolve().parents[1]


def main():
    container = "tfg-hu01-test-" + uuid.uuid4().hex[:12]
    password = secrets.token_urlsafe(32)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("PG") and key != "TFG_TEST_POSTGRES_DSN"}
    environment.update(POSTGRES_PASSWORD=password, POSTGRES_USER="tfg_local_admin",
                       POSTGRES_DB="tfg_test_hu01")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    started = False
    try:
        subprocess.run([
            "docker", "run", "--detach", "--rm", "--name", container,
            "--label", "tfg.test=hu01", "--publish", f"127.0.0.1:{port}:5432",
            "--tmpfs", "/var/lib/postgresql/data:rw,size=256m", "--memory", "512m",
            "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_USER", "--env", "POSTGRES_DB",
            "postgres:17",
        ], check=True, env=environment, stdout=subprocess.DEVNULL)
        started = True
        connection_args = dict(host="127.0.0.1", hostaddr="127.0.0.1", port=port,
                               dbname="tfg_test_hu01", password=password, connect_timeout=2)
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(**connection_args, user="tfg_local_admin", autocommit=True) as admin:
                    # El backend es propietario, pero NO superusuario ni BYPASSRLS.
                    admin.execute(sql.SQL(
                        "CREATE ROLE postgres LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Literal(password)))
                    admin.execute("CREATE ROLE anon NOLOGIN")
                    admin.execute("CREATE ROLE authenticated NOLOGIN")
                    admin.execute("CREATE ROLE service_role NOLOGIN BYPASSRLS")
                    admin.execute("GRANT anon, authenticated, service_role TO postgres WITH INHERIT FALSE")
                    admin.execute("ALTER DATABASE tfg_test_hu01 OWNER TO postgres")
                    admin.execute("ALTER SCHEMA public OWNER TO postgres")
                    # Grants de Supabase y un grant PUBLIC adicional para probar las cuatro revocaciones.
                    admin.execute("ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
                                  "GRANT ALL ON TABLES TO PUBLIC, anon, authenticated, service_role")
                    version = admin.execute("SHOW server_version").fetchone()[0]
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("PostgreSQL local no inició dentro de 60 segundos.") from None
                time.sleep(0.5)
        environment["TFG_TEST_POSTGRES_DSN"] = make_conninfo(
            host="127.0.0.1", port=port, dbname="tfg_test_hu01", user="postgres", password=password,
        )
        print(f"PostgreSQL {version}; base tfg_test_hu01 en loopback; rol propietario postgres sin superusuario.", flush=True)
        arguments = sys.argv[1:] or ["discover", "-s", "tests", "-v"]
        result = subprocess.run([sys.executable, "-m", "unittest", *arguments],
                                cwd=BACKEND, env=environment)
        return result.returncode
    finally:
        if started:
            subprocess.run(["docker", "stop", "--time", "10", container], check=True,
                           env=environment, stdout=subprocess.DEVNULL)
            print("Contenedor de pruebas detenido; datos tmpfs descartados.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
