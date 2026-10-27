"""Primitivas de segurança: hash de senha, tokens de sessão e cofre de segredos."""

import hashlib
import hmac
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password("dummy-password-for-timing")  # equaliza o tempo de usuário inexistente


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """O banco guarda só o SHA-256: vazar o banco não vaza sessões ativas."""
    return hashlib.sha256(token.encode()).hexdigest()


class SecretBox:
    """Criptografia em repouso (Fernet) para credenciais de câmeras."""

    def __init__(self, key: str, key_path: Path):
        self._key, self._key_path, self._fernet = key.encode(), key_path, None

    def _get(self) -> Fernet:
        if self._fernet is None:
            key = self._key
            if not key:
                self._key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                if not self._key_path.exists():
                    fd = os.open(self._key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as f:
                        f.write(Fernet.generate_key())
                key = self._key_path.read_bytes().strip()
            self._fernet = Fernet(key)
        return self._fernet

    def encrypt(self, data: bytes) -> bytes:
        return self._get().encrypt(data)

    def decrypt(self, token: bytes) -> bytes:
        return self._get().decrypt(token)
