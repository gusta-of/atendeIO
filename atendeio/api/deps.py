"""Dependências injetadas nas rotas."""

from fastapi import Request

from ..container import Container
from ..errors import AuthError

COOKIE = "atendeio_session"


def get_container(request: Request) -> Container:
    return request.app.state.container


def session_token(request: Request):
    return request.cookies.get(COOKIE)


def current_user(request: Request) -> dict:
    user = get_container(request).auth.user_for_token(session_token(request))
    if not user:
        raise AuthError("Faça login.")
    return user
