"""Anti força-bruta em memória: N falhas por chave dentro de uma janela."""

import threading
import time


class LoginThrottle:
    def __init__(self, limit: int, window_s: int):
        self._limit, self._window = limit, window_s
        self._fails: dict = {}
        self._lock = threading.Lock()

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            for k in [k for k, (_, t0) in self._fails.items() if now - t0 > self._window]:
                del self._fails[k]
            return self._fails.get(key, (0, now))[0] >= self._limit

    def record_failure(self, key: str) -> None:
        with self._lock:
            n, t0 = self._fails.get(key, (0, time.monotonic()))
            self._fails[key] = (n + 1, t0)

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
