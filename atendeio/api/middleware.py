"""Cabeçalhos de segurança e checagem de origem em requisições que alteram estado."""

import hmac
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response

# 'unsafe-inline' só em estilo (o Ionic injeta <style> em tempo de execução); script continua só 'self'.
# worker-src/manifest-src: service worker e manifest do PWA, ambos da mesma origem.
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
       "worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'")


SESSION_COOKIE = "atendeio_session"
LAUNCH_HEADER = "x-atendeio-launch"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def _hostname(host_header: str) -> str:
    """`127.0.0.1:8000` -> `127.0.0.1`; `[::1]:8000` -> `[::1]`."""
    if host_header.startswith("["):
        return host_header[:host_header.find("]") + 1]
    return host_header.rsplit(":", 1)[0]


def install(app: FastAPI, cors_origins: tuple = (), launch_secret: str = "") -> None:
    allowed = set(cors_origins)

    @app.middleware("http")
    async def security(request: Request, call_next):
        # Modo desktop: só o Electron que subiu este motor fala com ele. Outros programas e páginas da máquina (inclusive
        # um site tentando alcançar 127.0.0.1) não têm o segredo; o Host fixo barra DNS rebinding.
        if launch_secret:
            host = _hostname(request.headers.get("host", ""))
            if host not in LOCAL_HOSTS or not hmac.compare_digest(request.headers.get(LAUNCH_HEADER, ""), launch_secret):
                return Response("Acesso negado.", status_code=403)
        # Mutação só de origem própria (defesa extra além de SameSite=Strict). Exceção: origens de apps nativos
        # que o operador listou, e SÓ sem cookie de sessão — sem credencial ambiente não há o que forjar (CSRF).
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                if not (origin in allowed and SESSION_COOKIE not in request.cookies):
                    return Response("Origem não permitida.", status_code=403)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = CSP
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp
