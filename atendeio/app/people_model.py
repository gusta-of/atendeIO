"""Pessoas no Mapa: suavização do movimento e rastro (puro, sem Qt).

A câmera entrega uma posição por pessoa poucas vezes por segundo (`map_fps`); aqui cada marcador desliza até a posição
nova em vez de pular, e guarda os últimos segundos de trajeto. Tudo em memória: nenhum trajeto vai para o disco.
Quem some por mais de `ttl_s` sem amostra sai (mesmo prazo do `PersonTracker`)."""

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Tuple

Key = Tuple[int, int]            # (camera_id, id da pessoa)


@dataclass
class Marker:
    camera_id: int
    pid: int
    x: float                     # mundo (chão), já suavizado
    y: float
    trail: List[Tuple[float, float]] = field(default_factory=list)   # do mais antigo ao mais novo


class PeopleSmoother:
    def __init__(self, ttl_s: float = 1.5, trail_s: float = 8.0, speed: float = 8.0):
        self.ttl_s, self.trail_s, self.speed = ttl_s, trail_s, speed   # speed: 1/s da suavização exponencial
        self._cur: Dict[Key, List[float]] = {}                        # posição exibida
        self._target: Dict[Key, Tuple[float, float]] = {}
        self._seen: Dict[Key, float] = {}
        self._trail: Dict[Key, Deque[Tuple[float, float, float]]] = {}  # (t, x, y)
        self._last_step = None

    def update(self, people, now: float) -> None:
        """`people`: iterável de (camera_id, pid, x, y) em coordenadas do mundo."""
        for cam, pid, x, y in people:
            k = (cam, pid)
            if k not in self._cur:
                self._cur[k] = [x, y]            # nasce no lugar certo, sem deslizar do nada
                self._trail[k] = deque()
            self._target[k], self._seen[k] = (x, y), now
            self._trail[k].append((now, x, y))

    def drop(self, key: Key) -> None:
        """Tira já um marcador (ex.: virou a mesma pessoa de outra câmera): sem esperar o prazo."""
        for d in (self._cur, self._target, self._seen, self._trail):
            d.pop(key, None)

    def step(self, now: float) -> List[Marker]:
        """Avança a suavização até `now` e devolve os marcadores vivos."""
        dt = max(0.0, now - self._last_step) if self._last_step is not None else 0.0
        self._last_step = now
        a = 1.0 - pow(2.718281828, -self.speed * dt)
        for k in [k for k, t in self._seen.items() if now - t > self.ttl_s]:
            for d in (self._cur, self._target, self._seen, self._trail):
                d.pop(k, None)
        out = []
        for k, cur in self._cur.items():
            tx, ty = self._target[k]
            cur[0] += (tx - cur[0]) * a
            cur[1] += (ty - cur[1]) * a
            tr = self._trail[k]
            while tr and now - tr[0][0] > self.trail_s:
                tr.popleft()
            out.append(Marker(k[0], k[1], cur[0], cur[1], [(x, y) for _, x, y in tr]))
        return out

    def clear(self) -> None:
        for d in (self._cur, self._target, self._seen, self._trail):
            d.clear()
        self._last_step = None

