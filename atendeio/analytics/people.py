"""Pessoas na área da câmera: contagem estável (sem piscar com 1 frame ruim)."""

from collections import deque
from statistics import median


class PeopleCounter:
    """Mediana das contagens dos últimos `window_s` segundos (relógio injetado)."""

    def __init__(self, window_s: float = 2.0):
        self._window = window_s
        self._samples = deque()  # (t, n)

    def update(self, n: int, now: float) -> int:
        self._samples.append((now, n))
        while self._samples and now - self._samples[0][0] > self._window:
            self._samples.popleft()
        return int(round(median(v for _, v in self._samples)))
