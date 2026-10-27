"""Cabeçalhos de segurança e checagem de origem em requisições que alteram estado."""

from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "frame-ancestors 'none'")


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def security(request: Request, call_next):
        # Mutação só de origem própria (defesa extra além de SameSite=Strict).
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return Response("Origem não permitida.", status_code=403)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = CSP
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp
