import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


SECRET_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    raw_key = get_settings().app_encryption_key.strip()
    if not raw_key or raw_key == "change-me-app-encryption":
        raise RuntimeError("APP_ENCRYPTION_KEY nao foi configurada com seguranca")
    derived = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def decrypt_secret(value: str | None) -> str | None:
    if not value or not value.startswith(SECRET_PREFIX):
        return value
    try:
        return _fernet().decrypt(value.removeprefix(SECRET_PREFIX).encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Nao foi possivel descriptografar um segredo da instalacao") from exc
