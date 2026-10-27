import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ...streaming import sse
from ..deps import MediaAuth, events_auth, get_container
from ..hubs import acquire_hub

router = APIRouter(tags=["events"])


@router.get("/api/cameras/{cam_id}/events")
async def camera_events(cam_id: int, request: Request, detail: int = 0, history: int = 1,
                        media: MediaAuth = Depends(events_auth)):
    """Telemetria da câmera em JSON, em tempo real (SSE).

    detail=1  inclui um evento por quadro, com cada detecção e caixa (mais pesado; só liga se você pedir).
    history=1 entrega antes os últimos eventos em memória (o navegador reenvia Last-Event-ID ao reconectar).
    Só do dono da câmera; ouvir conta como espectador (liga a câmera e respeita os limites)."""
    c = get_container(request)
    user = media.user
    cam = await run_in_threadpool(c.cameras.get_owned, cam_id, user["id"])  # 404 se não for dele
    loop = asyncio.get_running_loop()
    hub = await acquire_hub(c, cam, user)
    since = sse.parse_last_event_id(request.headers.get("last-event-id"))
    sub, backlog = hub.events.subscribe(loop, detail=bool(detail), since=since, history=bool(history))

    async def still_authorized() -> bool:
        return await run_in_threadpool(media.still_valid)

    async def body():
        try:
            async for chunk in sse.events_stream(hub, sub, backlog, still_authorized, c.settings.session_recheck_s):
                yield chunk
        finally:
            hub.events.unsubscribe(sub)
            c.registry.release(hub)

    return StreamingResponse(body(), media_type=sse.MEDIA_TYPE,
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
