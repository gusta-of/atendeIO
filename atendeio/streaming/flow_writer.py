"""FlowWriter: a ÚNICA thread que grava o histórico de fluxo no banco.

Existe para que o banco nunca atrase quem importa: as threads do hub só entregam um lote a uma fila limitada
(`submit` não bloqueia, nunca levanta exceção) e a gravação acontece aqui, em lotes, numa transação só. Se o disco
travar, a fila enche e os lotes MAIS ANTIGOS são descartados (vira lacuna na análise); a câmera segue no ritmo."""

import contextlib
import queue
import threading
import time
from typing import Callable

from ..config import Settings
from ..repositories.flow import FlowRepository

PURGE_EVERY_S = 3600.0


class FlowWriter:
    def __init__(self, repo: FlowRepository, settings: Settings, clock: Callable[[], float] = time.time,
                 queue_max: int = 500):
        self._repo, self._cfg, self._clock = repo, settings, clock
        self._q: queue.Queue = queue.Queue(maxsize=queue_max)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="flow-writer", daemon=True)
        self._last_purge = 0.0
        self.submitted = self.written = self.dropped = self.errors = 0

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Grava o que sobrou e encerra."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def submit(self, batch: dict) -> bool:
        """Entrega um lote. Nunca bloqueia e nunca levanta: com a fila cheia, descarta o lote mais antigo."""
        self.submitted += 1
        while True:
            try:
                self._q.put_nowait(batch)
                return True
            except queue.Full:
                with contextlib.suppress(queue.Empty):
                    self._q.get_nowait()
                self.dropped += 1

    # -- thread escritora ---------------------------------------------------------------------
    def _drain(self, first=None) -> list:
        batches = [first] if first is not None else []
        while len(batches) < 100:
            try:
                batches.append(self._q.get_nowait())
            except queue.Empty:
                break
        return batches

    def _write(self, batches: list) -> None:
        if not batches:
            return
        try:
            self._repo.apply(batches)
            self.written += len(batches)
        except Exception as e:  # banco ocupado/falhando: registra e segue; o hub nem fica sabendo
            self.errors += 1
            print(f"[-] histórico de fluxo: não gravei {len(batches)} lote(s): {type(e).__name__}: {e}")

    def _purge_if_due(self) -> None:
        now = self._clock()
        if now - self._last_purge < PURGE_EVERY_S:
            return
        self._last_purge = now
        try:
            self._repo.purge(int(now // 60) - self._cfg.flow_minute_days * 1440,
                             int(now // 3600) - self._cfg.flow_hour_days * 24)
        except Exception as e:
            self.errors += 1
            print(f"[-] histórico de fluxo: limpeza falhou: {type(e).__name__}: {e}")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                first = self._q.get(timeout=1.0)
            except queue.Empty:
                self._purge_if_due()
                continue
            self._write(self._drain(first))
            self._purge_if_due()
        self._write(self._drain())   # parada: grava o que ainda estava na fila
