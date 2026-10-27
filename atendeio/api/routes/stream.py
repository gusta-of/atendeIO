import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ...streaming import mjpeg
from ..deps import current_user, get_container, session_token
from ..hubs import acquire_hub

router = APIRouter(tags=["stream"])


@router.get("/stream")
async def stream(camera: int, request: Request, boxes: int = 1, areas: int = 1, user: dict = Depends(current_user)):
    """MJPEG ao vivo (com YOLO) de UMA câmera do próprio utilizador."""
    c = get_container(request)
    cam = await run_in_threadpool(c.cameras.get_owned, camera, user["id"])  # 404 se não for dele
    loop = asyncio.get_running_loop()
    token = session_token(request)

    hub = await acquire_hub(c, cam, user)
    queue = hub.subscribe(loop, boxes=bool(boxes), areas=bool(areas))

    def cleanup():
        hub.unsubscribe(queue)
        c.registry.release(hub)

    if not await loop.run_in_executor(None, hub.ready.wait, c.settings.first_frame_timeout_s):
        cleanup()
        raise HTTPException(502, "Não consegui abrir a câmera (sem frames).")

    async def still_authorized() -> bool:
        return await run_in_threadpool(c.auth.user_for_token, token) is not None

    async def body():
        try:
            async for chunk in mjpeg.frames(hub, queue, still_authorized, c.settings.session_recheck_s, bool(boxes), bool(areas)):
                yield chunk
        finally:
            cleanup()

    return StreamingResponse(body(), media_type=mjpeg.MEDIA_TYPE, headers={"Cache-Control": "no-store"})


@router.get("/api/states")
def states(request: Request, user: dict = Depends(current_user)):
    """Inventário das câmeras ativas do utilizador (só as dele), numa chamada."""
    registry = get_container(request).registry
    return {"states": {str(k): v for k, v in registry.states_for(user["id"]).items()}}
