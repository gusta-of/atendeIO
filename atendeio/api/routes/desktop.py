"""Controle do agente desktop pelo Electron (só existe com o segredo de execução; o middleware já o exige)."""

from fastapi import APIRouter, Request

from ...errors import NotFoundError
from ..deps import get_container

router = APIRouter(prefix="/api/desktop", tags=["desktop"], include_in_schema=False)


@router.post("/quit")
def quit_engine(request: Request):
    """Encerramento limpo: o uvicorn desce, os hubs entregam o histórico, o escritor grava e o cofre de credenciais é
    apagado. (Matar o processo pularia tudo isso, e no Windows não há SIGTERM de verdade.)"""
    s = get_container(request).settings
    if not (s.desktop and s.launch_secret):
        raise NotFoundError("Não encontrado.")
    server = getattr(request.app.state, "server", None)
    if server is not None:
        server.should_exit = True
    return {"stopping": server is not None}
