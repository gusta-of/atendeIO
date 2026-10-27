"""Corpo multipart/x-mixed-replace (MJPEG) alimentado por um CameraHub."""

import asyncio
import time
from typing import Awaitable, Callable

from .hub import CameraHub

MEDIA_TYPE = "multipart/x-mixed-replace; boundary=frame"


def part(jpeg: bytes) -> bytes:
    return (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
            + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")


async def frames(hub: CameraHub, queue: asyncio.Queue, still_authorized: Callable[[], Awaitable[bool]],
                 recheck_every_s: float, boxes: bool = True, areas: bool = True):
    """Emite o último quadro e depois cada novo. Encerra se o hub parar (câmera removida)
    ou se a sessão deixar de valer (logout/expirou)."""
    next_check = time.monotonic() + recheck_every_s
    first = hub.last_jpeg(boxes, areas)
    if first:
        yield part(first)
    while not hub.stop_event.is_set():
        try:
            jpeg = await asyncio.wait_for(queue.get(), timeout=5.0)
        except asyncio.TimeoutError:
            jpeg = None  # câmera reconectando ou hub encerrado
        if time.monotonic() >= next_check:
            next_check = time.monotonic() + recheck_every_s
            if not await still_authorized():
                return
        if jpeg is not None:
            yield part(jpeg)
