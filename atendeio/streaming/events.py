"""Telemetria da câmera em JSON, em tempo real (barramento de eventos por câmera).

O hub transforma o que a câmera "vê" em eventos e os publica aqui; quem escuta (a janela de logs do painel, ou
qualquer ferramenta de análise via SSE) recebe cada evento no mesmo formato:

    {"seq": 42, "ts": 1793093698117, "time": "2026-10-27T09:14:58.117Z", "camera": 3,
     "type": "change", "event": "area.status", "data": {...}}

Tipos
    change    algo mudou: pessoas, status de mesa, câmera online/offline, reconhecimento, áreas...
    snapshot  retrato do estado, 1 por segundo (pessoas, objetos, mesas, fps)
    frame     detalhado, por quadro, com cada detecção e caixa. Só é montado enquanto alguém pede (`detail`)
    system    do próprio canal (ex.: eventos descartados porque o ouvinte não acompanhou)

`change` e `snapshot` ficam num buffer em memória (últimos N) pra quem abre a janela já ver o recente.
`frame` nunca é guardado. Nada vai pra disco."""

import asyncio
import contextlib
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, List, Optional

HISTORY = 200           # eventos guardados em memória por câmera (a janela de logs é só depuração)
SUB_QUEUE = 1000        # fila por ouvinte: se encher, descarta os mais antigos e conta
SNAPSHOT_EVERY_S = 1.0


class Event(dict):
    """O envelope do evento. `raw` guarda o texto SSE já pronto: serializa UMA vez (na thread que emitiu) em vez de
    uma vez por ouvinte dentro do laço de eventos, que é o que travava a aplicação com muitos logs."""
    __slots__ = ("raw",)


def encode_sse(ev: dict) -> bytes:
    raw = getattr(ev, "raw", None)
    if raw is not None:
        return raw
    body = json.dumps(ev, ensure_ascii=False, separators=(",", ":"))
    return f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {body}\n\n".encode()


def iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Subscriber:
    """Um ouvinte (uma conexão SSE). A fila é descartável: ouvinte lento perde eventos antigos, nunca trava o hub."""

    def __init__(self, loop, detail: bool, rate: float = 10.0, burst: Optional[float] = None):
        self.loop, self.detail = loop, detail
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=SUB_QUEUE)
        self._dropped = 0
        self._dlock = threading.Lock()
        self._rate = rate                                 # eventos/s que esta conexão aguenta (0 = sem limite)
        self._cap = burst if burst is not None else max(rate * 3, 10.0)
        self._tokens, self._t = self._cap, None

    def allow(self, now: float) -> bool:
        """Balde de fichas: decide NA ORIGEM se este evento vai pra esta conexão. Negado = nem acorda o laço de eventos."""
        if self._rate <= 0:
            return True
        if self._t is not None:
            self._tokens = min(self._cap, self._tokens + (now - self._t) * self._rate)
        self._t = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        self.add_dropped(1)
        return False

    def add_dropped(self, n: int) -> None:
        with self._dlock:
            self._dropped += n

    def take_dropped(self) -> int:
        with self._dlock:
            n, self._dropped = self._dropped, 0
        return n

    @property
    def dropped(self) -> int:
        return self._dropped

    def _put(self, item) -> None:  # roda na thread do loop
        if self.queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
            self.add_dropped(1)
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait(item)


class EventBus:
    def __init__(self, camera_id: int, history: int = HISTORY, clock: Callable[[], float] = time.time,
                 rate: float = 10.0):
        self.camera_id = camera_id
        self._rate = rate
        self._ring = deque(maxlen=history)
        self._subs: List[Subscriber] = []
        self._seq = 0
        self._lock = threading.Lock()
        self._clock = clock

    # -- publicação (threads do hub e de request) --------------------------------------------
    def emit(self, type_: str, event: str, data: dict) -> Optional[dict]:
        """Publica um evento. `frame` só é montado/enviado se há ouvinte detalhado: o chamador pode
        perguntar `wants_detail()` antes e nem construir o dado."""
        with self._lock:
            if type_ == "frame" and not any(s.detail for s in self._subs):
                return None
            self._seq += 1
            ts = int(self._clock() * 1000)
            ev = Event(seq=self._seq, ts=ts, time=iso(ts), camera=self.camera_id, type=type_, event=event, data=data)
            ev.raw = encode_sse(ev)             # serializa uma vez, aqui, fora do laço de eventos
            if type_ != "frame":
                self._ring.append(ev)
            now = self._clock()
            targets = [s for s in self._subs if (type_ != "frame" or s.detail) and s.allow(now)]
        for s in targets:
            with contextlib.suppress(RuntimeError):  # loop do ouvinte já fechou
                s.loop.call_soon_threadsafe(s._put, ev)
        return ev

    def wants_detail(self) -> bool:
        with self._lock:
            return any(s.detail for s in self._subs)

    # -- ouvintes ----------------------------------------------------------------------------
    def subscribe(self, loop, detail: bool = False, since: Optional[int] = None, history: bool = True):
        """Devolve (ouvinte, backlog). O backlog é o que já está no buffer (só eventos com seq > since),
        entregue na mesma operação em que o ouvinte entra: nada se perde nem duplica entre os dois."""
        sub = Subscriber(loop, detail, self._rate)
        with self._lock:
            backlog = [e for e in self._ring if (since is None or e["seq"] > since)] if history else []
            self._subs.append(sub)
        return sub, backlog

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subs = [s for s in self._subs if s is not sub]

    def listeners(self) -> int:
        with self._lock:
            return len(self._subs)

    def recent_since(self, seq: int) -> list:
        """Eventos com `seq` maior que o informado (o painel de logs nativo consulta de tempos em tempos, sem SSE)."""
        with self._lock:
            return [e for e in self._ring if e["seq"] > seq]

    def recent(self, n: int = 50) -> list:
        with self._lock:
            return list(self._ring)[-n:]


# ── Diferenças entre estados (puro) ───────────────────────────────────────────────────────────

def diff_states(prev: Optional[dict], cur: dict) -> list:
    """[(evento, dados)] do que mudou entre dois estados do hub. Puro, sem relógio nem I/O.

    Usa só números já estabilizados pelo hub (pessoas = mediana, mesas = máquina de estados com histerese),
    então não vira spam por oscilação de um quadro."""
    out = []
    if prev is not None and prev.get("people") != cur.get("people"):
        out.append(("people.changed", {"from": prev.get("people"), "to": cur.get("people")}))
    before = {a["id"]: a for a in (prev or {}).get("areas", [])}
    for a in cur.get("areas", []):
        old = before.get(a["id"])
        if old is None:
            # área que acaba de aparecer (1º estado ou área nova): registra o status inicial, `from` nulo
            if "status" in a:
                out.append(("area.status", {"id": a["id"], "name": a["name"], "kind": a["kind"],
                                            "from": None, "to": a["status"], "people": a.get("people", 0)}))
        elif a.get("status") != old.get("status"):
            out.append(("area.status", {"id": a["id"], "name": a["name"], "kind": a["kind"],
                                        "from": old.get("status"), "to": a.get("status"),
                                        "people": a.get("people", 0)}))
        elif a.get("people") != old.get("people"):
            out.append(("area.people", {"id": a["id"], "name": a["name"], "kind": a["kind"],
                                        "from": old.get("people"), "to": a.get("people")}))
    return out


def diff_counts(prev: Optional[dict], cur: dict) -> list:
    """Mudança na contagem por classe ({"bottle": 1, ...}). Chamada ~1x/s, não por quadro:
    a detecção de objetos pequenos pisca, e 1 Hz já filtra o grosso disso."""
    if prev is None:
        return []
    out = []
    for name in sorted(set(prev) | set(cur)):
        a, b = prev.get(name, 0), cur.get(name, 0)
        if a != b:
            out.append(("objects.changed", {"class": name, "from": a, "to": b}))
    return out


def counts_of(state: dict) -> dict:
    return {c["name"]: c["count"] for c in state.get("counts", [])}


def snapshot_of(state: dict, fps: float, viewers: int, online: bool) -> dict:
    """Retrato compacto (1/s): o que dá pra ler de relance e depois agregar."""
    return {
        "online": online, "fps": round(fps, 1), "viewers": viewers,
        "people": state.get("people"),
        "objects": counts_of(state),
        "areas": [{k: a[k] for k in ("id", "name", "kind", "status", "people", "items", "seconds", "wait") if k in a}
                  for a in state.get("areas", [])],
        "recognition": state.get("recognition"),
    }


def frame_of(dets: list, state: dict, fps: float) -> dict:
    """Detalhe de UM quadro: cada detecção com classe, confiança e caixa normalizada (0..1)."""
    return {
        "fps": round(fps, 1), "people": state.get("people"), "size": state.get("size"),
        "detections": [{"class": d["name"], "conf": round(d["conf"], 2),
                        "box": [round(v, 3) for v in d["box"]]} for d in dets],
        "areas": [{k: a[k] for k in ("id", "name", "status", "people") if k in a} for a in state.get("areas", [])],
    }
