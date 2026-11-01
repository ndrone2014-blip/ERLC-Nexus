"""Secret encryption (Fernet) and token helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken


def _fernet(secret_key: str) -> Fernet:
    digest = hashlib.sha256(("erlc-nexus-secrets:" + secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(secret_key: str, value: str) -> str:
    return _fernet(secret_key).encrypt(value.encode()).decode()


def decrypt_secret(secret_key: str, token: str) -> str | None:
    if not token:
        return None
    try:
        return _fernet(secret_key).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign(secret_key: str, value: str) -> str:
    mac = hmac.new(secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{value}.{mac}"


def unsign(secret_key: str, signed: str) -> str | None:
    if not signed or "." not in signed:
        return None
    value, _, mac = signed.rpartition(".")
    expected = hmac.new(secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]
    return value if hmac.compare_digest(mac, expected) else None
