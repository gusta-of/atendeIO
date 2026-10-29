"""Estado das áreas marcadas pelo utilizador (mesas, balcão, entrada, saída, fila...)."""

import threading
from collections import deque
from dataclasses import dataclass
from statistics import median
from typing import Dict, Iterable, List, Optional, Tuple

from .geometry import (box_overlap_fraction, feet_in_zone, membership_score, point_in_polygon,
                       point_polygon_distance)

KINDS = ("mesa", "balcao", "entrada", "saida", "fila", "area")

LIVRE, OCUPADA, A_LIMPAR = "livre", "ocupada", "a_limpar"

# Áreas de CHÃO: a pessoa só conta se pisa nelas (pés). Quem está perto da câmera cobre a porta na
# imagem, mas não está na porta.
FLOOR_KINDS = frozenset({"entrada", "saida", "fila"})


@dataclass(frozen=True)
class Zone:
    id: int
    name: str
    kind: str
    points: Tuple[Tuple[float, float], ...]  # normalizados 0..1
    margin: float = 0.0                      # mesa: largura da sombra de assentos (fração da altura da imagem)


@dataclass(frozen=True)
class AnalyticsConfig:
    occupy_after_s: float = 3.0   # pessoa precisa ficar isso pra a mesa virar "ocupada"
    free_after_s: float = 15.0    # mesa sem ninguém por isso pra deixar de ser "ocupada"
    item_hold_s: float = 3.0      # objeto visto há menos disso ainda conta (detector pisca)
    clean_after_s: float = 20.0   # sem objetos por isso, "a limpar" vira "livre"
    people_window: int = 9        # amostras na mediana de pessoas (estabiliza a contagem)
    overlap_min: float = 0.35     # pontuação mínima (ver geometry.membership_score) pra contar na área
    table_feet_tol: float = 0.06  # mesa: folga (fração do quadro) além do chão estimado da mesa; passou disso = a pessoa está na frente dela


def _center(box) -> Tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


class _Table:
    """Máquina de estados de uma mesa, com histerese pra não piscar por oclusão."""

    def __init__(self, now: float, cfg: AnalyticsConfig):
        self.cfg = cfg
        self.status, self.since = LIVRE, now
        self._people = deque(maxlen=cfg.people_window)
        self._arrived: Optional[float] = None      # desde quando há gente (candidato a ocupada)
        self._empty_since: Optional[float] = None  # desde quando está vazia (estando ocupada)
        self._item_seen: Optional[float] = None    # última vez que viu objeto de mesa
        self._no_items_since: Optional[float] = None

    def mark_clean(self, now: float) -> None:
        self.status, self.since = LIVRE, now
        self._no_items_since = None

    def update(self, people: int, items: int, now: float) -> dict:
        cfg = self.cfg
        self._people.append(people)
        people = int(median(self._people))  # decide pelo mesmo número que a tela mostra (sem "ocupada com 0 pessoas")
        if items:
            self._item_seen = now
        has_items = self._item_seen is not None and now - self._item_seen <= cfg.item_hold_s

        if self.status in (LIVRE, A_LIMPAR):
            if people:
                self._arrived = self._arrived if self._arrived is not None else now
                if now - self._arrived >= cfg.occupy_after_s:
                    self.status, self.since = OCUPADA, now
                    self._empty_since = None
            else:
                self._arrived = None
        if self.status == OCUPADA:
            if people:
                self._empty_since = None
            else:
                self._empty_since = self._empty_since if self._empty_since is not None else now
                if now - self._empty_since >= cfg.free_after_s:
                    # saíram: se ficou coisa na mesa, precisa limpar
                    self.status, self.since = (A_LIMPAR if has_items else LIVRE), now
                    self._arrived, self._no_items_since = None, None
        elif self.status == A_LIMPAR:
            if has_items:
                self._no_items_since = None
            else:
                self._no_items_since = self._no_items_since if self._no_items_since is not None else now
                if now - self._no_items_since >= cfg.clean_after_s:
                    self.status, self.since = LIVRE, now  # sumiu da mesa: foi limpa
        return {"status": self.status, "people": people,
                "items": items, "seconds": round(now - self.since)}


class ZoneAnalyzer:
    """Uma instância por câmera. `update` roda na thread de inferência; `set_zones` e
    `mark_clean` vêm de threads de request — por isso o lock."""

    def __init__(self, cfg: AnalyticsConfig = AnalyticsConfig(), zones: Iterable[Zone] = ()):
        self._cfg = cfg
        self._lock = threading.Lock()
        self._zones: Tuple[Zone, ...] = ()
        self._tables: Dict[int, _Table] = {}
        self._waiting: Dict[int, Dict[int, float]] = {}  # fila: id -> quando chegou
        self.set_zones(zones)

    @property
    def has_zones(self) -> bool:
        return bool(self._zones)

    @property
    def zones(self) -> Tuple[Zone, ...]:
        return self._zones

    def set_zones(self, zones: Iterable[Zone]) -> None:
        with self._lock:
            self._zones = tuple(zones)
            keep = {z.id for z in self._zones}
            for store in (self._tables, self._waiting):
                for zid in [k for k in store if k not in keep]:
                    del store[zid]

    @staticmethod
    def _affinity(box, z: Zone, ar: float, min_score: float, feet_tol: float = 0.06) -> float:
        """0 = a pessoa não é desta mesa; >0 = é (quanto maior, mais ligada). Duas formas de ser da mesa:
        sobrepor/cobrir a mesa, ou estar SENTADA na sombra de assentos: o CORPO (a caixa da pessoa, da altura
        do peito pra baixo) a até `margin` da borda da mesa. Quem senta ao lado fica fora do polígono, mas
        encostado na sombra, e é da mesa.

        Antes disso, a posição NO CHÃO: o polígono da mesa é desenhado no TAMPO, então o chão dela fica abaixo dele
        (~0,5 da altura de uma pessoa naquela profundidade). Quem pisa além disso (mais `feet_tol`) está NA FRENTE da mesa,
        mais perto da câmera: cobre a mesa na imagem mas não está nela. Caixa colada na borda de baixo = pés fora do quadro,
        conta como bem abaixo. A folga cresce com o tamanho da pessoa, então quem está encostado na mesa (mesmo longe
        da câmera, com a mesa alta na imagem) continua contando."""
        feet = box[3] + (0.15 if box[3] >= 0.985 else 0.0)
        floor = max(y for _, y in z.points) + 0.5 * max(feet - box[1], 0.0)      # onde a mesa pisa no chão, na imagem
        if feet > floor + feet_tol:
            return 0.0
        over = membership_score(box, z.points)
        best = over if over >= min_score else 0.0
        if z.margin > 0:
            x1, y1, x2, y2 = box
            poly = [(x * ar, y) for x, y in z.points]  # em unidades de altura: distância igual nos dois eixos
            h = y2 - y1
            d = min(point_polygon_distance((x1 + (x2 - x1) * fx) * ar, y1 + h * fy, poly)
                    for fy in (0.4, 0.6, 0.8) for fx in (0.0, 0.5, 1.0))
            if d <= z.margin:
                best = max(best, 1.0 - d / z.margin + 1e-6)  # +epsilon: na borda exata ainda conta
        return best

    def reset(self) -> None:
        """Esquece o estado das mesas e da fila (as áreas desenhadas continuam)."""
        with self._lock:
            self._tables.clear()
            self._waiting.clear()

    def mark_clean(self, zone_id: int, now: float) -> None:
        with self._lock:
            table = self._tables.get(zone_id)
            if table:
                table.mark_clean(now)

    def update(self, people: List[Tuple[int, tuple]], items: List[tuple], now: float, ar: float = 4 / 3) -> dict:
        """people: [(track_id, (x1,y1,x2,y2))]; items: [(x1,y1,x2,y2)] de objetos de mesa; ar: largura/altura
        do quadro (distâncias da sombra de assentos são medidas em pixels, não em fração de cada eixo).
        Quem conta em cada tipo de área:
          mesa            dentro OU cobrindo a mesa (`membership_score >= overlap_min`) OU sentada na SOMBRA de
                          assentos (corpo a até `margin` da borda da mesa); cada pessoa vai só pra mesa de maior
                          afinidade;
          entrada/saida/fila  só quem PISA na área (pés), pra não contar quem está na frente da câmera;
          balcao/area     `overlap_min` do corpo da pessoa dentro da área."""
        with self._lock:
            min_score = self._cfg.overlap_min
            tables = [z for z in self._zones if z.kind == "mesa"]
            # mesa: afinidade = maior entre (sobreposição) e (proximidade à borda, dentro da sombra de assentos)
            score = {z.id: {tid: self._affinity(box, z, ar, min_score, self._cfg.table_feet_tol) for tid, box in people}
                     for z in tables}
            members = {}
            for z in self._zones:
                if z.kind == "mesa":
                    members[z.id] = [tid for tid, sc in score[z.id].items() if sc > 0]
                elif z.kind in FLOOR_KINDS:  # porta/fila: só quem pisa na área
                    members[z.id] = [tid for tid, box in people if feet_in_zone(box, z.points)]
                else:                         # balcão/área: a maior parte da pessoa está dentro
                    members[z.id] = [tid for tid, box in people
                                     if box_overlap_fraction(box, z.points) >= min_score]
            for tid, _ in people:
                owners = [z for z in tables if tid in members[z.id]]
                if len(owners) > 1:
                    best = max(owners, key=lambda z: score[z.id][tid])
                    for z in owners:
                        if z is not best:
                            members[z.id].remove(tid)
            out = []
            for z in self._zones:
                ids = members[z.id]
                info = {"id": z.id, "name": z.name, "kind": z.kind}
                if z.kind == "mesa":
                    n_items = sum(1 for b in items if point_in_polygon(*_center(b), z.points))
                    table = self._tables.setdefault(z.id, _Table(now, self._cfg))
                    info.update(table.update(len(ids), n_items, now))
                elif z.kind == "fila":
                    waiting = self._waiting.setdefault(z.id, {})
                    for tid in list(waiting):
                        if tid not in ids:
                            del waiting[tid]
                    for tid in ids:
                        waiting.setdefault(tid, now)
                    info.update(people=len(ids),
                                wait=round(max((now - t for t in waiting.values()), default=0)))
                else:  # balcao, entrada, saida, area: quantas pessoas estão aí agora
                    info.update(people=len(ids))
                out.append(info)
            return {"areas": out}
