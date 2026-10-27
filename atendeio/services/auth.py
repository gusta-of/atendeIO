"""Cadastro, login e sessões."""

import re
from typing import Optional

from ..config import Settings
from ..errors import AuthError, ForbiddenError, RateLimitError, ValidationError
from ..repositories.sessions import SessionRepository
from ..repositories.users import UserRepository
from ..security import DUMMY_HASH, hash_password, new_token, token_digest, verify_password
from .throttle import LoginThrottle

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


class AuthService:
    def __init__(self, users: UserRepository, sessions: SessionRepository,
                 throttle: LoginThrottle, settings: Settings):
        self._users, self._sessions, self._throttle, self._cfg = users, sessions, throttle, settings

    def register(self, username: str, password: str) -> tuple:
        """Cria a conta e já abre sessão. Devolve (username, token)."""
        if not self._cfg.allow_signup:
            raise ForbiddenError("Cadastro desativado.")
        username = normalize_username(username)
        if not USERNAME_RE.match(username):
            raise ValidationError("Usuário: 3 a 32 caracteres (letras, números, . _ -).")
        if not 8 <= len(password or "") <= 128:
            raise ValidationError("A senha deve ter entre 8 e 128 caracteres.")
        user_id = self._users.create(username, hash_password(password))
        return username, self._open_session(user_id)

    def create_user(self, username: str, password: str) -> int:
        """Criação administrativa (scripts/add_user.py), mesmo com cadastro público desligado."""
        username = normalize_username(username)
        if not USERNAME_RE.match(username):
            raise ValidationError("Usuário: 3 a 32 caracteres (letras, números, . _ -).")
        if not 8 <= len(password or "") <= 128:
            raise ValidationError("A senha deve ter entre 8 e 128 caracteres.")
        return self._users.create(username, hash_password(password))

    def login(self, username: str, password: str, client_ip: str) -> tuple:
        username = normalize_username(username)
        key = f"{client_ip}|{username}"
        if self._throttle.blocked(key):
            raise RateLimitError("Muitas tentativas. Aguarde alguns minutos.")
        row = self._users.get_by_username(username)
        ok = verify_password(password or "", row["pw_hash"] if row else DUMMY_HASH)  # tempo constante
        if not (row and ok):
            self._throttle.record_failure(key)
            raise AuthError("Usuário ou senha incorretos.")
        self._throttle.reset(key)
        return username, self._open_session(row["id"])

    def user_for_token(self, token: Optional[str]) -> Optional[dict]:
        """{"id","username"} da sessão válida, ou None."""
        return self._sessions.get_user(token_digest(token)) if token else None

    def user_for_digest(self, digest: str) -> Optional[dict]:
        """Mesma checagem de `user_for_token`, a partir do digest guardado num tíquete."""
        return self._sessions.get_user(digest)

    def logout(self, token: Optional[str]) -> None:
        if token:
            self._sessions.delete(token_digest(token))

    def _open_session(self, user_id: int) -> str:
        token = new_token()
        self._sessions.create(token_digest(token), user_id, self._cfg.session_ttl_s)
        return token
