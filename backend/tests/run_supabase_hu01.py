"""Integración HU-01 autorizada, con datos aislados y rollback total.

Ejecución explícita: python -m tests.run_supabase_hu01 --run
No migra, no borra tablas ni usa el runner destructivo de PostgreSQL local.
Los IDs negativos aleatorios evitan avanzar secuencias compartidas.
"""

import argparse
import secrets
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import router
from app.auth.config import get_auth_settings
from app.auth.database import get_db
from app.auth.dependencies import COOKIE_NAME
from app.auth.models import EstadoAcceso, Sesion
from app.auth.security import digest, hash_password
from app.auth.service import as_utc
from app.db.base import Base
from app.db.engine import build_engine
from app.db.models import Cliente, DetallePedido, Entrega, Pedido, Producto, Repartidor, Restaurante, Usuario
from app.main import private_responses, validation_error
from tests.auth_support import mount_test_routes


class SupabaseHu01Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = build_engine()
        cls.connection = cls.engine.connect()
        cls.outer = cls.connection.begin()
        cls.addClassCleanup(cls.rollback_all)
        cls.connection.exec_driver_sql("SET LOCAL lock_timeout='2s'")
        cls.connection.exec_driver_sql("SET LOCAL statement_timeout='8s'")
        if cls.connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one() != "0002_hu01_auth":
            raise RuntimeError("Se requiere 0002 aplicada; este runner no ejecuta migraciones.")
        if cls.connection.execute(text("SELECT current_user")).scalar_one() != "postgres":
            raise RuntimeError("El rol no coincide con el revisado para HU-01.")
        cls.prefix = uuid.uuid4().hex
        cls.password = "QA " + secrets.token_hex(8)
        cls.now = datetime.now(UTC).replace(microsecond=0)
        cls.base_id = -(1_000_000_000 + secrets.randbelow(500_000_000))
        cls.ids = {name: cls.base_id + offset for offset, name in enumerate((
            "r1", "r2", "staff1", "staff2", "client1_user", "client2_user", "courier1_user", "courier2_user",
            "owner", "admin", "courier3_user", "client1", "client2", "courier1", "courier2", "courier3",
            "product1", "product2", "order1", "order2", "order3", "detail1", "detail2", "detail3",
            "delivery1", "delivery2",
        ), start=1)}
        cls.emails = {name: f"hu01-{cls.prefix}-{name}@test.invalid" for name in (
            "staff1", "staff2", "client1_user", "client2_user", "courier1_user", "courier2_user", "owner", "admin", "courier3_user",
        )}
        cls.initial_counts = cls.row_counts()
        cls.insert_fixture()
        cls.app = FastAPI()
        cls.app.include_router(router, prefix="/api")
        cls.app.add_exception_handler(RequestValidationError, validation_error)
        cls.app.middleware("http")(private_responses)
        mount_test_routes(cls.app)

        def isolated_db():
            with cls.db() as db:
                yield db

        cls.app.dependency_overrides[get_db] = isolated_db
        settings = get_auth_settings()
        cls.origin = sorted(settings.allowed_origins)[0]
        cls.headers = {"Origin": cls.origin, "X-CSRF-Protection": "1"}

    @classmethod
    def db(cls):
        return Session(bind=cls.connection, expire_on_commit=False, join_transaction_mode="create_savepoint")

    @classmethod
    def row_counts(cls):
        names = list(Base.metadata.tables) + ["auth_estado_acceso", "auth_sesion"]
        # Lista interna de tablas conocidas; no se reciben identificadores externos.
        sql = " UNION ALL ".join(f"SELECT '{name}' AS name,count(*) AS total FROM public.\"{name}\"" for name in names)
        return dict(cls.connection.exec_driver_sql(sql).all())

    @classmethod
    def insert_fixture(cls):
        ids = cls.ids
        with cls.db() as db:
            for number in (1, 2):
                db.add(Restaurante(id_restaurante=ids[f"r{number}"], nombre=f"SINTÉTICO QA HU01 {cls.prefix} {number}",
                                   direccion="Dirección sintética QA", horario_atencion="QA", abierto=True,
                                   costo_fijo_entrega=0, costo_por_km=0))
            db.flush()
            for name, role, restaurant in (
                ("staff1", "personal", "r1"), ("staff2", "personal", "r2"),
                ("client1_user", "cliente", None), ("client2_user", "cliente", None),
                ("courier1_user", "repartidor", "r1"), ("courier2_user", "repartidor", "r2"),
                ("owner", "propietario", "r1"), ("admin", "administrador_plataforma", None),
                ("courier3_user", "repartidor", "r1"),
            ):
                db.add(Usuario(id_usuario=ids[name], id_restaurante=ids[restaurant] if restaurant else None,
                               correo=cls.emails[name], nombre="SINTÉTICO QA HU01 " + name,
                               hash_contrasena=hash_password(cls.password), rol=role, activo=True))
            db.flush()
            for number in (1, 2):
                db.add(Cliente(id_cliente=ids[f"client{number}"], id_usuario=ids[f"client{number}_user"], nombre="SINTÉTICO QA"))
                db.add(Producto(id_producto=ids[f"product{number}"], id_restaurante=ids[f"r{number}"],
                                nombre="SINTÉTICO QA", precio=100, costo_unitario=10, activo=True))
            for number in (1, 2, 3):
                db.add(Repartidor(id_repartidor=ids[f"courier{number}"], id_usuario=ids[f"courier{number}_user"],
                                 estado_disponibilidad="Disponible"))
            db.flush()
            for number, restaurant, client in ((1, 1, 1), (2, 2, 2), (3, 2, 1)):
                db.add(Pedido(id_pedido=ids[f"order{number}"], id_restaurante=ids[f"r{restaurant}"],
                              id_cliente=ids[f"client{client}"], fecha_hora=cls.now, estado="Nuevo",
                              direccion_entrega="SINTÉTICO QA", medio_pago="efectivo", estado_pago="pendiente",
                              importe_total=100, distancia_km=1, costo_total=10))
            db.flush()
            for number, product in ((1, 1), (2, 2), (3, 2)):
                db.add(DetallePedido(id_detalle=ids[f"detail{number}"], id_pedido=ids[f"order{number}"],
                                     id_producto=ids[f"product{product}"], cantidad=1, precio_unitario=100))
            for number in (1, 2):
                db.add(Entrega(id_entrega=ids[f"delivery{number}"], id_pedido=ids[f"order{number}"],
                               id_repartidor=ids[f"courier{number}"], estado="asignada", costo_repartidor=0))
            db.commit()  # Solo libera el savepoint: la transacción externa nunca se confirma.
        cls.connection.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
        cls.connection.exec_driver_sql("SET CONSTRAINTS ALL DEFERRED")

    @classmethod
    def rollback_all(cls):
        try:
            if cls.outer.is_active:
                cls.outer.rollback()
            if hasattr(cls, "initial_counts"):
                if cls.row_counts() != cls.initial_counts:
                    raise AssertionError("Cambió el conteo de filas durante la prueba; no se ejecutó ninguna limpieza destructiva.")
                remaining = cls.connection.execute(select(Usuario.id_usuario).where(Usuario.correo.like(f"hu01-{cls.prefix}-%@test.invalid"))).first()
                if remaining is not None:
                    raise AssertionError("El rollback no retiró todos los usuarios de prueba.")
                print("Rollback confirmado: datos de prueba retirados y conteos existentes conservados.", flush=True)
            cls.connection.rollback()
        finally:
            cls.connection.close()
            cls.engine.dispose()

    def setUp(self):
        self.scope = self.connection.begin_nested()
        self.client = TestClient(self.app, base_url=self.origin)
        self.clock = patch("app.auth.service.utc_now", return_value=self.now)
        self.identity_clock = patch("app.auth.dependencies.utc_now", return_value=self.now)
        self.clock_mock = self.clock.start()
        self.identity_clock_mock = self.identity_clock.start()

    def tearDown(self):
        self.client.close()
        self.identity_clock.stop()
        self.clock.stop()
        self.scope.rollback()

    def login(self, name="staff1", password=None):
        return self.client.post("/api/auth/login", headers=self.headers,
                                json={"correo":self.emails[name],"contrasena":self.password if password is None else password})

    def test_login_and_session_hash(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id_restaurante"], self.ids["r1"])
        self.assertTrue("HttpOnly" in response.headers["set-cookie"])
        token = self.client.cookies.get(COOKIE_NAME)
        with self.db() as db:
            self.assertIsNotNone(db.get(Sesion,digest(token)))
        self.assertEqual(self.client.get("/api/auth/me").status_code,200)

    def test_logout_and_replay_denied(self):
        self.assertEqual(self.login().status_code,200)
        token = self.client.cookies.get(COOKIE_NAME)
        self.assertEqual(self.client.post("/api/auth/logout",headers=self.headers).status_code,204)
        self.client.cookies.clear()
        self.client.cookies.set(COOKIE_NAME,token)
        self.assertEqual(self.client.get("/api/auth/me").status_code,401)

    def test_five_failures_and_fifteen_minute_lock(self):
        for number in range(1,6):
            self.assertEqual(self.login(password="incorrecta").status_code,401)
            with self.db() as db:
                state=db.get(EstadoAcceso,digest(self.emails["staff1"]))
                self.assertEqual(state.intentos_fallidos,number)
        self.assertEqual(self.login().status_code,401)
        with self.db() as db:
            self.assertEqual(as_utc(db.get(EstadoAcceso,digest(self.emails["staff1"])).bloqueado_hasta),self.now+timedelta(minutes=15))
        self.clock_mock.return_value=self.now+timedelta(minutes=14,seconds=59)
        self.assertEqual(self.login().status_code,401)
        self.clock_mock.return_value=self.now+timedelta(minutes=15)
        self.assertEqual(self.login().status_code,200)

    def test_success_resets_failures(self):
        for _ in range(4):
            self.assertEqual(self.login(password="incorrecta").status_code,401)
        self.assertEqual(self.login().status_code,200)
        with self.db() as db:
            self.assertEqual(db.get(EstadoAcceso,digest(self.emails["staff1"])).intentos_fallidos,0)

    def test_server_revocation_and_inactive_user(self):
        self.login()
        token=self.client.cookies.get(COOKIE_NAME)
        with self.db() as db:
            db.delete(db.get(Sesion,digest(token)))
            db.commit()
        self.assertEqual(self.client.get("/api/auth/me").status_code,401)
        self.login()
        with self.db() as db:
            db.get(Usuario,self.ids["staff1"]).activo=False
            db.commit()
        self.assertEqual(self.client.get("/api/auth/me").status_code,401)

    def test_roles_and_restaurant_isolation(self):
        for name,own,other in (("staff1","r1","r2"),("staff2","r2","r1"),("owner","r1","r2")):
            self.assertEqual(self.login(name).status_code,200)
            self.assertEqual(self.client.get(f"/api/test/restaurant/{self.ids[own]}").status_code,200)
            self.assertEqual(self.client.get(f"/api/test/restaurant/{self.ids[other]}").status_code,403)
            self.assertEqual(self.client.post(f"/api/test/restaurant/{self.ids[other]}",headers=self.headers).status_code,403)
        for name in ("client1_user","courier1_user","admin"):
            self.login(name)
            self.assertEqual(self.client.get(f"/api/test/restaurant/{self.ids['r1']}").status_code,403)

    def test_client_only_own_orders_across_restaurants(self):
        self.login("client1_user")
        for name in ("order1","order3"):
            self.assertEqual(self.client.get(f"/api/test/order/{self.ids[name]}").status_code,200)
        self.assertEqual(self.client.get(f"/api/test/order/{self.ids['order2']}").status_code,404)
        self.assertEqual(self.client.get(f"/api/test/client/{self.ids['client2']}").status_code,404)
        self.login("staff1")
        self.assertEqual(self.client.get(f"/api/test/order/{self.ids['order2']}").status_code,404)

    def test_courier_only_own_assigned_delivery(self):
        self.login("courier1_user")
        self.assertEqual(self.client.get(f"/api/test/delivery/{self.ids['delivery1']}").status_code,200)
        self.assertEqual(self.client.get(f"/api/test/delivery/{self.ids['delivery2']}").status_code,404)
        self.login("courier3_user")
        self.assertEqual(self.client.get(f"/api/test/delivery/{self.ids['delivery1']}").status_code,404)

    def test_csrf_and_expired_session(self):
        self.assertEqual(self.client.post("/api/auth/login",json={"correo":self.emails["staff1"],"contrasena":self.password}).status_code,403)
        self.login()
        self.assertEqual(self.client.post("/api/auth/logout").status_code,403)
        self.identity_clock_mock.return_value=self.now+timedelta(hours=8)
        self.assertEqual(self.client.get("/api/auth/me").status_code,401)

    def test_unknown_email_has_same_response(self):
        wrong=self.login(password="incorrecta")
        unknown=self.client.post("/api/auth/login",headers=self.headers,
                                 json={"correo":f"unknown-{self.prefix}@test.invalid","contrasena":self.password})
        self.assertEqual(unknown.status_code,wrong.status_code)
        self.assertEqual(unknown.json(),wrong.json())

    def test_auth_constraints_and_foreign_key(self):
        for record in (
            EstadoAcceso(clave_correo="x"*64,intentos_fallidos=0,actualizado_en=self.now),
            EstadoAcceso(clave_correo="a"*64,intentos_fallidos=6,actualizado_en=self.now),
            Sesion(token_hash="b"*64,id_usuario=self.ids["staff1"],creada_en=self.now,expira_en=self.now),
        ):
            with self.db() as db:
                with self.assertRaises(IntegrityError):
                    db.add(record)
                    db.flush()
        with self.db() as db:
            user=db.get(Usuario,self.base_id-100)
            self.assertIsNone(user)
            with self.assertRaises(IntegrityError):
                db.add(Sesion(token_hash="c"*64,id_usuario=self.base_id-100,creada_en=self.now,expira_en=self.now+timedelta(hours=1)))
                db.flush()


def main():
    parser=argparse.ArgumentParser(description="Pruebas autorizadas HU-01 con rollback total, sin migraciones ni borrados de tablas.")
    parser.add_argument("--run",action="store_true",help="Ejecutar explícitamente contra la conexión configurada")
    args=parser.parse_args()
    if not args.run:
        parser.error("Usar --run únicamente con autorización para probar Supabase.")
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SupabaseHu01Tests))
    return 0 if result.wasSuccessful() else 1


if __name__=="__main__":
    raise SystemExit(main())
