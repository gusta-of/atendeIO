"""Dependências injetadas nas rotas."""

from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import Request

from ..container import Container
from ..errors import AuthError
from ..security import token_digest

COOKIE = "atendeio_session"


def get_container(request: Request) -> Container:
    return request.app.state.container


def session_token(request: Request) -> Optional[str]:
    """Credencial da requisição: o cookie (navegador) ou `Authorization: Bearer` (apps nativos)."""
    cookie = request.cookies.get(COOKIE)
    if cookie:
        return cookie
    scheme, _, value = (request.headers.get("authorization") or "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def current_user(request: Request) -> dict:
    user = get_container(request).auth.user_for_token(session_token(request))
    if not user:
        raise AuthError("Faça login.")
    return user


@dataclass
class MediaAuth:
    """Quem pediu um vídeo/eventos e como reconferir (a cada poucos segundos) que ainda pode."""
    user: dict
    still_valid: Callable[[], bool]


def media_auth(request: Request, kind: str, cam_id: int) -> MediaAuth:
    """Autoriza /stream e /events: por `?ticket=` (apps nativos) ou pela sessão normal (cookie / Bearer)."""
    c = get_container(request)
    ticket = request.query_params.get("ticket")
    if ticket:
        data = c.tickets.verify(ticket, cam_id, kind)
        user = c.auth.user_for_digest(data["s"]) if data else None
        if not data or not user or user["id"] != data["u"]:
            raise AuthError("Tíquete inválido ou expirado.")
        return MediaAuth(user, lambda: c.auth.user_for_digest(data["s"]) is not None)   # logout derruba o vídeo aberto
    token = session_token(request)
    user = c.auth.user_for_token(token)
    if not user:
        raise AuthError("Faça login.")
    return MediaAuth(user, lambda: c.auth.user_for_token(token) is not None)


def stream_auth(request: Request, camera: int) -> MediaAuth:
    return media_auth(request, "stream", camera)


def events_auth(request: Request, cam_id: int) -> MediaAuth:
    return media_auth(request, "events", cam_id)


def digest_of(request: Request) -> str:
    return token_digest(session_token(request) or "")
