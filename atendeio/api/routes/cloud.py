from fastapi import APIRouter, Depends, Request

from ..deps import current_user, get_container
from ..schemas import CloudRequest

router = APIRouter(prefix="/api/cloud", tags=["cloud"])


def _view(request: Request) -> dict:
    c = get_container(request)
    return {**c.cloud.public(), "status": c.exporter.status()}


@router.get("")
def get_cloud(request: Request, user: dict = Depends(current_user)):
    """Configuração do envio à cloud e estado da fila. Nunca devolve a chave do dispositivo."""
    return _view(request)


@router.put("")
def set_cloud(body: CloudRequest, request: Request, user: dict = Depends(current_user)):
    """Liga/desliga o envio, define o endereço e (opcionalmente) troca a chave. Vale na hora."""
    c = get_container(request)
    c.cloud.update(body.enabled, body.url, body.api_key)
    c.exporter.refresh()
    return _view(request)
