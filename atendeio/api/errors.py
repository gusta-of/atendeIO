"""Tradução de erros de domínio em respostas HTTP."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .. import errors

_STATUS = [
    (errors.ValidationError, 400),
    (errors.AuthError, 401),
    (errors.ForbiddenError, 403),
    (errors.NotFoundError, 404),
    (errors.ConflictError, 409),
    (errors.RateLimitError, 429),
]


def install(app: FastAPI) -> None:
    @app.exception_handler(errors.DomainError)
    async def _domain(_request: Request, exc: errors.DomainError):
        status = next((s for cls, s in _STATUS if isinstance(exc, cls)), 400)
        return JSONResponse({"detail": str(exc)}, status_code=status)
