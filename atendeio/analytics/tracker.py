"""Rastreador leve de pessoas: IoU guloso com ids estáveis.

Existe um por câmera (CameraHub). Não fica no Detector porque o modelo é compartilhado
entre câmeras e misturaria os ids. Serve para contar entradas/saídas e tempo de espera."""

from dataclasses import dataclass
from typing import List, Tuple

from .geometry import iou

Box = Tuple[float, float, float, float]


def _center_gap(a: Box, b: Box) -> float:
    """Distância entre os centros das caixas, em múltiplos do tamanho (maior lado) da maior das duas."""
    size = max(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1], 1e-6)
    return (((a[0] + a[2]) / 2 - (b[0] + b[2]) / 2) ** 2 + ((a[1] + a[3]) / 2 - (b[1] + b[3]) / 2) ** 2) ** 0.5 / size


@dataclass
class _Track:
    id: int
    box: Box
    last_seen: float


class PersonTracker:
    def __init__(self, max_age_s: float = 1.5, iou_min: float = 0.3, near: float = 0.6):
        self._max_age, self._iou_min, self._near = max_age_s, iou_min, near   # near: distância entre centros / tamanho da pessoa
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
        # 2ª passada: quem anda rápido entre duas leituras tem caixas que quase não se sobrepõem (IoU baixo) mas ainda
        # está PERTO; associa pelo centro (dentro de ~metade do tamanho da pessoa) em vez de criar uma pessoa nova
        rest = sorted(
            ((_center_gap(t.box, b), ti, bi)
             for ti, t in enumerate(self._tracks) if ti not in used_t
             for bi, b in enumerate(boxes) if bi not in assigned),
            key=lambda r: r[0])
        for gap, ti, bi in rest:
            if gap > self._near:
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
