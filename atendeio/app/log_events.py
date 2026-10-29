"""Buffer de eventos da janela de logs (sem Qt): filtro por tipo, busca, anel de eventos, estatísticas e NDJSON.

Porta de `web/src/app/features/logs/{log-event.ts, logs-window.component.ts}`. Feito para NUNCA pesar: o JSON de cada evento é
serializado UMA vez na chegada, o anel guarda no máximo 2000 e a busca usa um texto minúsculo já preparado."""

import json
import time
from collections import deque
from datetime import datetime
from typing import Callable, List, Optional

TYPES = [("change", "Mudanças", True), ("snapshot", "Resumo 1/s", True), ("frame", "Quadros (2/s)", False),
         ("system", "Sistema", True)]
MAX_CAPTURED = 2000          # eventos guardados na janela (para exportar)
RATE_WINDOW_S = 5.0
_INTERNAL = ("_s", "_l")


def clock(ts_ms: int) -> str:
    d = datetime.fromtimestamp(ts_ms / 1000)
    return f"{d:%H:%M:%S}.{d.microsecond // 1000:03d}"


def to_ndjson(events: List[dict]) -> str:
    """Um objeto JSON por linha, pronto para jq, pandas, planilha etc. (sem os campos internos `_s`/`_l`)."""
    lines = [json.dumps({k: v for k, v in e.items() if k not in _INTERNAL}, ensure_ascii=False, separators=(",", ":"))
             for e in events]
    return "\n".join(lines) + ("\n" if lines else "")


class LogBuffer:
    def __init__(self, now: Callable[[], float] = time.time):
        self._now = now
        self.events: List[dict] = []
        self.view: List[dict] = []
        self.last_seq = 0
        self.throttled = 0
        self.peak_people = 0
        self.started = now()
        self._recent: deque = deque()
        self.types = {tid for tid, _label, on in TYPES if on}
        self.query = ""

    # -- filtro -----------------------------------------------------------------------------------------
    def matches(self, e: dict) -> bool:
        if e["type"] not in self.types:
            return False
        if not self.query:
            return True
        if "_l" not in e:
            e["_l"] = f"{e['event']} {e['type']} {e['_s']}".lower()
        return self.query in e["_l"]

    def refilter(self) -> None:
        self.view = [e for e in self.events if self.matches(e)]

    def set_type(self, type_id: str, on: bool) -> None:
        (self.types.add if on else self.types.discard)(type_id)
        self.refilter()

    def set_query(self, text: str) -> None:
        self.query = text.strip().lower()
        self.refilter()

    def clear(self) -> None:
        self.events, self.view, self.throttled, self.peak_people = [], [], 0, 0

    # -- entrada ---------------------------------------------------------------------------------------------
    def ingest(self, raw: dict) -> bool:
        """Registra um evento do barramento. Devolve True se ele entrou na lista visível."""
        seq = raw.get("seq")
        if seq:
            if seq <= self.last_seq:
                return False                         # já tinha (reabertura da janela / troca de detalhe)
            self.last_seq = seq
        e = dict(raw)                                # cópia: o evento do barramento é compartilhado
        e["_s"] = json.dumps(e.get("data", {}), ensure_ascii=False, separators=(",", ":"))   # serializa UMA vez
        if e["event"] == "events.throttled":
            self.throttled += int(e["data"].get("count") or 0)
        self.events.append(e)
        if len(self.events) > MAX_CAPTURED + 200:
            self.events = self.events[-MAX_CAPTURED:]
        self._recent.append(self._now())
        people = e["data"].get("people") if e["type"] == "snapshot" else e["data"].get("to") if e["event"] == "people.changed" else None
        if isinstance(people, (int, float)) and not isinstance(people, bool) and people > self.peak_people:
            self.peak_people = int(people)
        if self.matches(e):
            self.view.append(e)
            if len(self.view) > MAX_CAPTURED + 200:
                self.view = self.view[-MAX_CAPTURED:]
            return True
        return False

    # -- estatísticas ----------------------------------------------------------------------------------------
    def stats_text(self, paused: bool = False) -> str:
        now = self._now()
        while self._recent and now - self._recent[0] > RATE_WINDOW_S:
            self._recent.popleft()
        rate = f"{len(self._recent) / RATE_WINDOW_S:.1f}"
        return (f"{len(self.events)} capturados · {rate}/s · pico de pessoas {self.peak_people} · {round(now - self.started)}s"
                + (f" · {self.throttled} cortados pelo servidor" if self.throttled else "")
                + (" · em pausa" if paused else ""))
