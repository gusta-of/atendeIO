"""Pessoas no Mapa: suavização do movimento e rastro (puro, sem Qt).

A câmera entrega uma posição por pessoa poucas vezes por segundo (`map_fps`); aqui cada marcador desliza até a posição
nova em vez de pular, e guarda os últimos segundos de trajeto. Tudo em memória: nenhum trajeto vai para o disco.
Quem some por mais de `ttl_s` sem amostra sai (mesmo prazo do `PersonTracker`)."""

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

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


TABLE_RATIO = 0.44        # altura do tampo (~0,75 m) / altura de uma pessoa (~1,7 m)


class PersonScale:
    """Aprende, por câmera, quanto mede (em fração do quadro) uma pessoa de pé em cada linha da imagem: h(y) ≈ a·y + b.
    Serve para achar a BASE de uma mesa: o polígono dela é desenhado no tampo, e o chão fica abaixo dele em ~0,44·h.
    Só entram corpos inteiros no quadro. Tudo em memória; sem amostras suficientes, não estima (None)."""

    def __init__(self, keep: int = 300, min_samples: int = 12, min_spread: float = 0.08):
        self._keep, self._min, self._spread = keep, min_samples, min_spread
        self._s: Dict[int, Deque[Tuple[float, float]]] = {}

    def add(self, camera_id: int, y_feet: float, h: float) -> None:
        if 0.05 <= h <= 1.0 and 0.0 < y_feet < 1.0:
            self._s.setdefault(camera_id, deque(maxlen=self._keep)).append((y_feet, h))

    def height_at(self, camera_id: int, y: float) -> Optional[float]:
        pts = self._s.get(camera_id)
        if not pts or len(pts) < self._min:
            return None
        ys = [p[0] for p in pts]
        if max(ys) - min(ys) < self._spread:                    # pessoas sempre na mesma linha: não dá para ver a tendência
            n = len(pts)
            return sum(p[1] for p in pts) / n
        n, my, mh = len(pts), sum(ys) / len(pts), sum(p[1] for p in pts) / len(pts)
        var = sum((a - my) ** 2 for a in ys)
        a = sum((p[0] - my) * (p[1] - mh) for p in pts) / var if var else 0.0
        a = max(0.0, a)                                         # mais perto da câmera (y maior) = maior, nunca o contrário
        return max(0.05, min(1.0, mh + a * (y - my)))

    def table_lift(self, camera_id: int, y_base: float) -> float:
        """Quanto descer o polígono do tampo (fração do quadro) para chegar à base da mesa."""
        h = self.height_at(camera_id, y_base)
        return TABLE_RATIO * h if h else 0.0

    def clear(self) -> None:
        self._s.clear()
