"""CloudExporter: a ÚNICA thread que envia eventos do restaurante à cloud.

Mesmo desenho do FlowWriter: as threads do hub só entregam o evento a uma fila limitada (`submit` nunca bloqueia nem
levanta), e a thread daqui o grava na outbox (SQLite) e o envia em lotes. A outbox sobrevive a quedas de internet e a
reinícios; um evento só sai dela quando a cloud confirma (2xx). A cloud ignora um `event_id` repetido, então reenviar é
seguro.

Falhas:
    rede / 5xx / 408 / 429 / 3xx   tenta de novo com espera crescente (5 s ... 5 min)
    401 / 403                      chave recusada: espera 5 min e tenta de novo (o estado fica `auth_failed`)
    outro 4xx                      o conteúdo foi recusado: isola o evento (lote de 1) e, se for ele, marca `rejected`
"""

import contextlib
import json
import queue
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from ..analytics import cloud_events as ce
from ..config import Settings
from ..repositories.cloud import OutboxRepository
from ..services.cloud import CloudService

PATH = "/v1/events"
CAMERA_CACHE_S = 60.0
CREDENTIALS_CACHE_S = 30.0
TRIM_EVERY_S = 600.0
AUTH_RETRY_S = 300.0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Nunca segue redirecionamentos: a chave do dispositivo não pode ir parar noutro endereço."""

    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def http_post(url: str, key: str, body: bytes, timeout: float) -> int:
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": "atendeIO"})
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


class CloudExporter:
    def __init__(self, cloud: CloudService, outbox: OutboxRepository, camera_lookup: Callable[[int, int], Optional[dict]],
                 states: Callable[[], list], settings: Settings, clock: Callable[[], float] = time.time,
                 post: Callable[[str, str, bytes, float], int] = http_post, queue_max: int = 2000):
        self._cloud, self._outbox, self._lookup, self._states = cloud, outbox, camera_lookup, states
        self._cfg, self._clock, self._post = settings, clock, post
        self._q: queue.Queue = queue.Queue(maxsize=queue_max)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="cloud-exporter", daemon=True)
        self._creds: Optional[dict] = None
        self._creds_at = -CREDENTIALS_CACHE_S
        self._enabled = False
        self._cameras: dict = {}
        self._next_try = 0.0
        self._backoff = 0.0
        self._limit = settings.cloud_batch_size
        self._last_snapshot = 0.0
        self._last_trim = 0.0
        self.state = "off"                    # off | ok | retrying | auth_failed
        self.last_ok: Optional[float] = None
        self.last_error: Optional[str] = None
        self.submitted = self.dropped = self.sent = 0

    # -- ciclo de vida --------------------------------------------------------------------------
    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Guarda na outbox o que ainda estava na fila (sem esperar pela rede) e encerra."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)
        with contextlib.suppress(Exception):
            if self._creds:
                self._ingest(self._clock())

    def refresh(self) -> None:
        """A configuração mudou (API): relê já a chave e o endereço."""
        self._creds_at = -CREDENTIALS_CACHE_S
        self._next_try = 0.0
        self._backoff = 0.0
        self._load_credentials(self._clock())

    # -- entrada (threads do hub) ---------------------------------------------------------------
    def submit(self, kind: str, cam_id: int, owner_id: int, payload) -> None:
        """Nunca bloqueia e nunca levanta. Desligado = ignora. Fila cheia = descarta o mais antigo."""
        if not self._enabled:
            return
        self.submitted += 1
        item = (kind, cam_id, owner_id, payload)
        while True:
            try:
                self._q.put_nowait(item)
                return
            except queue.Full:
                with contextlib.suppress(queue.Empty):
                    self._q.get_nowait()
                self.dropped += 1

    # -- estado para a API ----------------------------------------------------------------------
    def status(self) -> dict:
        counts = self._outbox.counts()
        return {"state": self.state, "pending": counts["pending"], "rejected": counts["rejected"],
                "last_ok": ce.iso_utc(self.last_ok) if self.last_ok else None, "last_error": self.last_error,
                "sent": self.sent, "dropped": self.dropped}

    # -- uma volta (a thread chama em laço; os testes chamam direto, com relógio injetado) ------------
    def run_once(self) -> bool:
        """True se enviou um lote cheio (há mais para enviar: volta já, sem esperar)."""
        now = self._clock()
        self._load_credentials(now)
        if self._creds is None:
            self._discard_queue()
            return False
        self._ingest(now)
        self._maybe_snapshot(now)
        self._maybe_trim(now)
        return self._send(now)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                more = self.run_once()
            except Exception as e:  # nada aqui pode derrubar o servidor
                more = False
                self.last_error = f"erro interno: {type(e).__name__}"
                print(f"[-] envio à cloud: {type(e).__name__}: {e}")
            if not more:
                self._stop.wait(1.0)

    # -- passos --------------------------------------------------------------------------------
    def _load_credentials(self, now: float) -> None:
        if now - self._creds_at < CREDENTIALS_CACHE_S:
            return
        self._creds_at = now
        self._creds = self._cloud.credentials()
        self._enabled = self._creds is not None
        if not self._enabled:
            self.state = "off"
        elif self.state == "off":
            self.state = "ok"

    def _discard_queue(self) -> None:
        with contextlib.suppress(queue.Empty):
            while True:
                self._q.get_nowait()

    def _camera(self, cam_id: int, owner_id: int, now: float) -> Optional[dict]:
        cached = self._cameras.get(cam_id)
        if cached and cached[1] > now:
            return cached[0]
        cam = self._lookup(cam_id, owner_id)
        self._cameras[cam_id] = (cam, now + CAMERA_CACHE_S)
        return cam

    def _enqueue_envelopes(self, envelopes: list) -> None:
        self._outbox.add_many([(e["event_id"], json.dumps(e, separators=(",", ":"), ensure_ascii=False))
                               for e in envelopes])

    def _ingest(self, now: float) -> None:
        device_id, envelopes = self._creds["device_id"], []
        for _ in range(500):
            try:
                kind, cam_id, owner_id, payload = self._q.get_nowait()
            except queue.Empty:
                break
            cam = self._camera(cam_id, owner_id, now)
            if cam is None:        # câmera removida entretanto
                continue
            if kind == "change":
                env = ce.from_change(device_id, cam, payload)
            elif kind == "flow":
                env = ce.from_flow_batch(device_id, cam, payload, now)
            else:
                env = None
            if env is not None:
                envelopes.append(env)
        self._enqueue_envelopes(envelopes)

    def _maybe_snapshot(self, now: float) -> None:
        if now - self._last_snapshot < self._cfg.cloud_snapshot_every_s:
            return
        self._last_snapshot = now
        envelopes = []
        for cam_id, owner_id, state in self._states():
            cam = self._camera(cam_id, owner_id, now)
            if cam is not None:
                envelopes.append(ce.snapshot(self._creds["device_id"], cam, state, now))
        self._enqueue_envelopes(envelopes)

    def _maybe_trim(self, now: float) -> None:
        if now - self._last_trim < TRIM_EVERY_S:
            return
        self._last_trim = now
        dropped = self._outbox.trim(self._cfg.cloud_outbox_max, self._cfg.cloud_rejected_keep_s)
        self.dropped += dropped

    def _retry_later(self, now: float, why: str) -> None:
        self._backoff = min(self._cfg.cloud_backoff_max_s, 5.0 if self._backoff == 0 else self._backoff * 2)
        self._next_try = now + self._backoff
        self.state, self.last_error = "retrying", why

    def _send(self, now: float) -> bool:
        if now < self._next_try:
            return False
        rows = self._outbox.pending(self._limit)
        if not rows:
            return False
        ids = [r["id"] for r in rows]
        body = ('{"device_id":"%s","sent_at":"%s","events":[%s]}'
                % (self._creds["device_id"], ce.iso_utc(now), ",".join(r["payload"] for r in rows))).encode()
        try:
            status = self._post(self._creds["url"] + PATH, self._creds["key"], body, self._cfg.cloud_timeout_s)
        except (OSError, ValueError):
            self._outbox.mark_attempt(ids)
            self._retry_later(now, "sem ligação à cloud")
            return False

        if 200 <= status < 300:
            self._outbox.delete(ids)
            self._backoff, self._next_try = 0.0, 0.0
            self._limit = min(self._cfg.cloud_batch_size, self._limit * 2)
            self.state, self.last_ok, self.last_error = "ok", now, None
            self.sent += len(ids)
            return len(ids) >= self._cfg.cloud_batch_size
        self._outbox.mark_attempt(ids)
        if status in (401, 403):
            self.state, self.last_error = "auth_failed", "a cloud recusou a chave do dispositivo"
            self._next_try = now + AUTH_RETRY_S
        elif 400 <= status < 500 and status not in (408, 429):
            if len(ids) > 1:
                self._limit = 1                 # isola o evento problemático
                self._next_try = 0.0
            else:
                self._outbox.reject(ids)        # este evento não é aceite: deixa de bloquear a fila
                self.last_error = f"evento recusado pela cloud (HTTP {status})"
                self._next_try = 0.0
        else:
            self._retry_later(now, f"a cloud respondeu HTTP {status}")
        return False
