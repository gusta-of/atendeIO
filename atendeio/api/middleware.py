"""Cabeçalhos de segurança e checagem de origem em requisições que alteram estado."""

from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response

# 'unsafe-inline' só em estilo (o Ionic injeta <style> em tempo de execução); script continua só 'self'.
# worker-src/manifest-src: service worker e manifest do PWA, ambos da mesma origem.
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
       "worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'")


SESSION_COOKIE = "atendeio_session"


def install(app: FastAPI, cors_origins: tuple = ()) -> None:
    allowed = set(cors_origins)

    @app.middleware("http")
    async def security(request: Request, call_next):
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
