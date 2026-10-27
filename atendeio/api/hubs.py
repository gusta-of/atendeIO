"""Liga (ou reaproveita) o pipeline de uma câmera do utilizador — usado pelo vídeo e pela telemetria."""

from fastapi.concurrency import run_in_threadpool

from ..container import Container
from ..services.recognition import parse as parse_recognition
from ..streaming.hub import CameraHub


async def acquire_hub(c: Container, cam: dict, user: dict) -> CameraHub:
    """Conta como espectador: a câmera liga mesmo que ninguém esteja vendo o vídeo, e respeita os limites.
    Quem chama deve `registry.release(hub)` ao terminar."""
    zones = await run_in_threadpool(c.zones.load, cam["id"])
    enabled, classes = parse_recognition(cam)
    return c.registry.acquire(cam["id"], user["id"], lambda: c.cameras.source_for(cam), zones, enabled, classes)
