"""Uma pessoa vista por duas câmeras da mesma sala conta UMA vez (puro, sem Qt).

Câmeras com a mesma `sala` e com o chão calibrado têm as pessoas no mesmo plano (o utilizador alinha as zonas no mapa), então duas
detecções de câmeras diferentes a menos de `max_m` metros uma da outra, no mesmo instante, são a mesma pessoa. Nunca se junta
duas pessoas da MESMA câmera (a câmera as vê como distintas). Sem calibração não há metros, então não se junta (fica como está)."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..analytics.geometry import point_in_polygon, point_polygon_distance

Key = Tuple[int, int]                         # (camera_id, id da pessoa na câmera)
MAX_M = 0.5
CROWD_DOTS = 12     # a partir de tantas detecções na sala, o raio de união é limitado
CROWD_MAX_M = 0.6
CONSENSUS_MAX = 4   # até tantas pessoas por câmera, com a MESMA contagem nas câmeras da sala, vale o raio largo
CONSENSUS_M = 3.0   # raio largo: quando as contagens batem, a distância é erro de alinhamento, não outra pessoa
VISIBLE_M = 1.5     # ...desde que cada uma esteja a menos disto do chão que a OUTRA câmera enxerga (as duas deveriam vê-la)


@dataclass
class Dot:
    camera_id: int
    pid: int
    x: float
    y: float
    room: str = ""
    units_per_m: Optional[float] = None       # unidades do mundo por metro (None = câmera sem calibração)
    sigma_m: float = 1.0                      # incerteza da posição (m): a união pondera pela precisão de cada câmera
    floor: Optional[Sequence[Tuple[float, float]]] = None   # o chão calibrado da câmera no mundo (4 cantos): onde ela deveria ver as pessoas


@dataclass
class Person:
    camera_id: int                            # câmera "dona" do marcador (a de menor id entre as que veem a pessoa)
    pid: int
    x: float
    y: float
    members: List[Key] = field(default_factory=list)

    @property
    def key(self) -> Key:
        return (self.camera_id, self.pid)


RELEASE = 1.8       # uma ligação já feita só se desfaz acima de RELEASE × o raio (histerese: andar não faz o pin separar e juntar)
HOLD_S = 1.0        # a ligação sobrevive tanto tempo à falta de uma das detecções (oclusão curta, id trocado)


class RoomMerger:
    """`merge` com memória: as ligações entre trilhas de câmeras diferentes persistem enquanto elas se mantêm razoavelmente
    perto. Duas câmeras não são sincronizadas e a calibração tem erro; sem isso, andar fazia a união ligar e desligar."""

    def __init__(self, max_m: float = MAX_M):
        self.max_m = max_m
        self._links: Dict[frozenset, float] = {}          # {chave_a, chave_b} -> último instante em que valeu

    def merge(self, dots: List[Dot], now: float) -> Tuple[List[Person], int]:
        people, dup = merge(dots, self.max_m, self._links, now)
        return people, dup


def _near_floor(d: "Dot", floor, upm: float) -> bool:
    if not floor:
        return False                                  # sem o chão da outra câmera não dá para afirmar que as duas deveriam ver a pessoa
    pt = (d.x, d.y)
    return point_in_polygon(pt[0], pt[1], list(floor)) or point_polygon_distance(pt[0], pt[1], list(floor)) <= VISIBLE_M * upm


def _both_should_see(a: "Dot", b: "Dot") -> bool:
    """A pessoa de cada câmera está dentro (ou perto) do chão que a outra câmera também enxerga: as duas deveriam tê-la visto."""
    upm = ((a.units_per_m or 1.0) + (b.units_per_m or 1.0)) / 2
    return _near_floor(a, b.floor, upm) and _near_floor(b, a.floor, upm)


def merge(dots: List[Dot], max_m: float = MAX_M, links: Optional[Dict[frozenset, float]] = None,
          now: float = 0.0) -> Tuple[List[Person], int]:
    """Devolve (pessoas sem duplicar, quantas duplicatas foram unidas). Com `links` (de um RoomMerger) usa e atualiza a memória."""
    links = links if links is not None else {}
    for pair in [k for k, t in links.items() if now - t > HOLD_S]:
        del links[pair]
    parent: Dict[Key, Key] = {(d.camera_id, d.pid): (d.camera_id, d.pid) for d in dots}
    cams: Dict[Key, set] = {(d.camera_id, d.pid): {d.camera_id} for d in dots}

    def find(k: Key) -> Key:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    by_room: Dict[str, List[Dot]] = {}
    for d in dots:
        if d.room and d.units_per_m:
            by_room.setdefault(d.room.strip().lower(), []).append(d)
    for group in by_room.values():
        # sala cheia: com muita gente perto, um raio grande une pessoas DIFERENTES; limita o raio
        radius = max_m if len(group) <= CROWD_DOTS else min(max_m, CROWD_MAX_M)
        per_cam: Dict[int, int] = {}
        for d in group:
            per_cam[d.camera_id] = per_cam.get(d.camera_id, 0) + 1
        counts = set(per_cam.values())
        consensus = len(per_cam) >= 2 and len(counts) == 1 and max(counts) <= CONSENSUS_MAX     # todas veem o mesmo número de pessoas
        pairs = []
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if a.camera_id == b.camera_id:
                    continue
                dist = ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5 / ((a.units_per_m + b.units_per_m) / 2)
                linked = frozenset(((a.camera_id, a.pid), (b.camera_id, b.pid))) in links
                wide = consensus and dist <= CONSENSUS_M and _both_should_see(a, b)
                if dist <= radius or (linked and dist <= radius * RELEASE) or wide:
                    # ligações já existentes vão primeiro (preferência estável); depois os pares mais próximos
                    pairs.append((0 if linked else 1, dist, (a.camera_id, a.pid), (b.camera_id, b.pid)))
        for _prio, _dist, ka, kb in sorted(pairs):
            ra, rb = find(ka), find(kb)
            if ra == rb or cams[ra] & cams[rb]:           # já juntos, ou as duas câmeras já estão nesse grupo
                continue
            parent[rb] = ra
            cams[ra] |= cams[rb]
            links[frozenset((ka, kb))] = now
    groups: Dict[Key, List[Dot]] = {}
    for d in dots:
        groups.setdefault(find((d.camera_id, d.pid)), []).append(d)
    people = []
    for members in groups.values():
        members.sort(key=lambda d: (d.camera_id, d.pid))
        lead = members[0]
        w = [1.0 / max(m.sigma_m, 0.02) ** 2 for m in members]        # mais peso a quem enxerga o ponto com menos incerteza
        tw = sum(w)
        people.append(Person(lead.camera_id, lead.pid, sum(wi * m.x for wi, m in zip(w, members)) / tw,
                             sum(wi * m.y for wi, m in zip(w, members)) / tw, [(m.camera_id, m.pid) for m in members]))
    people.sort(key=lambda p: p.key)
    return people, len(dots) - len(people)
