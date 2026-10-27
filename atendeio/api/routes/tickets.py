from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from ..deps import current_user, digest_of, get_container

router = APIRouter(tags=["tickets"])


class TicketRequest(BaseModel):
    kind: Literal["stream", "events"]


@router.post("/api/cameras/{cam_id}/ticket")
async def ticket(cam_id: int, body: TicketRequest, request: Request, user: dict = Depends(current_user)):
    """Tíquete curto para abrir o vídeo ou os eventos DESTA câmera (só do dono: 404 para as dos outros).

    Existe porque `<img>` e `EventSource` não mandam `Authorization`: o app nativo põe o tíquete na URL."""
    c = get_container(request)
    await run_in_threadpool(c.cameras.get_owned, cam_id, user["id"])
    return {"ticket": c.tickets.issue(user["id"], cam_id, body.kind, digest_of(request)), "expires_in": c.tickets.ttl_s}
