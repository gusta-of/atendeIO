"""Server-Sent Events: eventos da câmera como texto, uma conexão HTTP que o navegador reabre sozinho.

Formato por evento:  id: <seq> / event: <type> / data: <json>.  Comentários (": ping") mantêm a conexão viva
atrás de proxies. O navegador reenvia `Last-Event-ID` ao reconectar e recebe só o que perdeu."""

import asyncio
import json
import time
from typing import Awaitable, Callable, List, Optional

from .events import Subscriber, encode_sse
from .hub import CameraHub

MEDIA_TYPE = "text/event-stream"
HEARTBEAT_S = 15.0


def encode(ev: dict) -> bytes:
    """Um evento no formato SSE (o `data` é uma linha de JSON, sem quebras)."""
    return encode_sse(ev)


def _system(event: str, data: dict) -> bytes:
    """Evento do próprio canal (sem `id`: não entra no buffer nem no Last-Event-ID)."""
    ev = {"ts": int(time.time() * 1000), "type": "system", "event": event, "data": data}
    return f"event: system\ndata: {json.dumps(ev, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()


def parse_last_event_id(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None and value.strip() != "" else None
    except ValueError:
        return None


async def events_stream(hub: CameraHub, sub: Subscriber, backlog: List[dict],
                        still_authorized: Callable[[], Awaitable[bool]], recheck_every_s: float,
                        heartbeat_s: float = HEARTBEAT_S):
    """Backlog primeiro, depois cada evento novo. Termina se o hub parar (câmera removida) ou se a
    sessão deixar de valer (logout/expirou)."""
    yield b"retry: 3000\n\n"
    for ev in backlog:
        yield encode(ev)
    next_check = time.monotonic() + recheck_every_s
    while not hub.stop_event.is_set():
        ev = None
        try:
            ev = await asyncio.wait_for(sub.queue.get(), timeout=heartbeat_s)
        except asyncio.TimeoutError:
            yield b": ping\n\n"
        n = sub.take_dropped()
        if n:  # passou do orçamento de eventos/s (ou o ouvinte não acompanhou): avisa quantos ficaram de fora
            yield _system("events.throttled", {"count": n})
        if time.monotonic() >= next_check:
            next_check = time.monotonic() + recheck_every_s
            if not await still_authorized():
                return
        if ev is not None:
            yield encode(ev)
