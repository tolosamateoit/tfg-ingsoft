"""Argon2id y tokens opacos. Nunca registrar contraseñas ni tokens."""

import hashlib
import re
from functools import lru_cache

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Parámetros explícitos, sal aleatoria individual de 16 bytes (argon2-cffi).
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID)
# Lista local pequeña, deliberadamente documentada; no es una base completa de filtraciones.
COMMON_PASSWORDS = frozenset({
    'hola123', '123456', '123456789', 'password', 'contraseña', 'contrasena',
    "123456789012345", "1234567890123456", "12345678901234567", "123456789012345678",
    "1234567890123456789", "12345678901234567890", "passwordpassword", "password123456789",
    "qwertyuiopasdfgh", "contrasenacontrasena", "contraseñacontraseña",
} | {char * length for char in '0123456789abcdefghijklmnopqrstuvwxyz' for length in range(15, 21)})


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Correo inválido.")
    return email


def hash_password(password: str) -> str:
    if not 15 <= len(password) <= 20:
        raise ValueError("La contraseña debe tener entre 15 y 20 caracteres.")
    if not password.strip() or password.casefold() in COMMON_PASSWORDS:
        raise ValueError("Elegí una contraseña menos común.")
    return PASSWORD_HASHER.hash(password)


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    return PASSWORD_HASHER.hash("verificación ficticia sin cuenta")


def verify_password(encoded: str | None, password: str) -> bool:
    # La API no acepta hashes de otros algoritmos, aunque la biblioteca los soporte.
    if encoded and encoded.startswith("$argon2id$"):
        try:
            return PASSWORD_HASHER.verify(encoded, password)
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError):
            pass
    try:
        PASSWORD_HASHER.verify(dummy_hash(), password)
    except VerificationError:
        pass
    return False


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
