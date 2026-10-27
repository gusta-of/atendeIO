"""Tíquetes de mídia: autorizam ABRIR um vídeo (/stream) ou um fluxo de eventos (/events) sem cabeçalho.

Apps nativos autenticam por `Authorization: Bearer`, mas `<img>` e `EventSource` não conseguem mandar cabeçalhos.
O app pede um tíquete (autenticado) e o põe na URL. O tíquete é assinado (HMAC-SHA256), vale poucos segundos e está
preso a utilizador + câmera + tipo + sessão: não serve para outra câmera, outro tipo, e morre com o logout."""

import base64
import hashlib
import hmac
import json
import time
from typing import Callable, Optional

KINDS = ("stream", "events")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class TicketService:
    def __init__(self, key: bytes, ttl_s: int = 60, clock: Callable[[], float] = time.time):
        self._key, self._ttl, self._clock = key, ttl_s, clock

    @property
    def ttl_s(self) -> int:
        return self._ttl

    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self._key, body.encode(), hashlib.sha256).digest())

    def issue(self, user_id: int, cam_id: int, kind: str, session_digest: str) -> str:
        """`session_digest` é o SHA-256 do token de sessão (o mesmo que o banco guarda): não permite entrar, só
        reconferir se aquela sessão ainda existe."""
        if kind not in KINDS:
            raise ValueError(kind)
        payload = {"u": user_id, "c": cam_id, "k": kind, "e": int(self._clock()) + self._ttl, "s": session_digest}
        body = _b64(json.dumps(payload, separators=(",", ":")).encode())
        return f"{body}.{self._sign(body)}"

    def verify(self, ticket: str, cam_id: int, kind: str) -> Optional[dict]:
        """Os dados do tíquete, ou None se estiver adulterado, vencido, de outra câmera ou de outro tipo."""
        try:
            body, sig = ticket.split(".")
            if not hmac.compare_digest(sig, self._sign(body)):
                return None
            data = json.loads(_unb64(body))
            if data["c"] != cam_id or data["k"] != kind or data["e"] < self._clock():
                return None
            return data
        except (ValueError, KeyError, TypeError):
            return None
