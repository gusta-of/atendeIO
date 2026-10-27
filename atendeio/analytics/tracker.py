"""Rastreador leve de pessoas: IoU guloso com ids estáveis.

Existe um por câmera (CameraHub). Não fica no Detector porque o modelo é compartilhado
entre câmeras e misturaria os ids. Serve para contar entradas/saídas e tempo de espera."""

from dataclasses import dataclass
from typing import List, Tuple

from .geometry import iou

Box = Tuple[float, float, float, float]


@dataclass
class _Track:
    id: int
    box: Box
    last_seen: float


class PersonTracker:
    def __init__(self, max_age_s: float = 1.5, iou_min: float = 0.3):
        self._max_age, self._iou_min = max_age_s, iou_min
        self._tracks: List[_Track] = []
        self._next_id = 1

    def update(self, boxes: List[Box], now: float) -> List[Tuple[int, Box]]:
        """Associa as caixas do frame aos tracks. Devolve [(id, box)] na ordem de `boxes`.
        Track sem detecção sobrevive `max_age_s` (oclusão curta não troca o id)."""
        self._tracks = [t for t in self._tracks if now - t.last_seen <= self._max_age]
        pairs = sorted(
            ((iou(t.box, b), ti, bi)
             for ti, t in enumerate(self._tracks) for bi, b in enumerate(boxes)),
            reverse=True)
        used_t, assigned = set(), {}
        for score, ti, bi in pairs:
            if score < self._iou_min:
                break
            if ti in used_t or bi in assigned:
                continue
            used_t.add(ti)
            assigned[bi] = self._tracks[ti]
        out = []
        for bi, box in enumerate(boxes):
            t = assigned.get(bi)
            if t is None:
                t = _Track(self._next_id, box, now)
                self._next_id += 1
                self._tracks.append(t)
            t.box, t.last_seen = box, now
            out.append((t.id, box))
        return out
