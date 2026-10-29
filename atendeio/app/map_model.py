"""Modelo do Mapa do ambiente (sem Qt): da câmera/áreas/estado para zonas, blocos 2.5D, cores, alertas e resumo por câmera.

Cada câmera vira uma "zona" (retângulo no mundo, `aspect × 1` vezes a escala) e as áreas aparecem onde estão na imagem dela
(a vista de cima é APROXIMADA: a imagem é uma perspectiva, não uma planta; o utilizador compensa arrastando/escalando a zona).
Tudo aqui é puro e testável sem tela; `ui/map_view.py` só desenha o que este módulo devolve."""

import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from functools import lru_cache

from ..analytics.camera_geometry import CameraGeometry
from ..analytics.geometry import point_in_polygon
from . import iso, labels
from .room_merge import Dot, Person, merge

DEFAULT_ASPECT = 16 / 9
SECTION_GAP = 0.3            # espaço entre zonas no layout automático (em unidades de altura de câmera)
PER_ROW = 2                  # zonas por linha no layout automático
MIN_SCALE, MAX_SCALE = 0.4, 3.0

# altura (z) de cada tipo de área, em unidades de altura de câmera (multiplicada pela escala da zona)
HEIGHT = {"mesa": 0.10, "balcao": 0.22, "entrada": 0.28, "saida": 0.28, "fila": 0.03, "area": 0.02}
SEE_THROUGH = frozenset({"entrada", "saida"})        # portas: desenhadas com transparência
OFFLINE_COLOR = "#475569"


@dataclass
class AlertRules:
    """Limiares dos alertas (segundos / pessoas). Editáveis pelo utilizador (QSettings `map/alert_*`)."""
    clean_warn_s: int = 120          # mesa "a limpar" há mais que isso: aviso
    clean_crit_s: int = 300          # ...e crítico
    queue_wait_warn_s: int = 180     # fila com espera maior que isso: aviso
    queue_wait_crit_s: int = 360
    queue_people_warn: int = 5       # fila com tantas pessoas: aviso
    queue_people_crit: int = 8

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "AlertRules":
        base = cls()
        for k, v in (d or {}).items():
            if hasattr(base, k):
                try:
                    setattr(base, k, max(0, int(v)))
                except (TypeError, ValueError):
                    pass
        return base

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Alert:
    level: str                 # "warn" | "crit"
    kind: str                  # clean | queue | offline | credentials | limit | view
    camera_id: int
    zone_id: Optional[int]
    text: str


@dataclass
class Layout:
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rot: float = 0.0           # graus, em torno do centro da zona (horário visto de cima)

    def world(self, lx: float, ly: float, aspect: float) -> Tuple[float, float]:
        """Ponto local da zona (x em 0..aspect, y em 0..1) no mundo: gira em torno do centro, escala e desloca."""
        if self.rot:
            r = math.radians(self.rot)
            c, sn = math.cos(r), math.sin(r)
            dx, dy = lx - aspect / 2, ly - 0.5
            lx, ly = aspect / 2 + dx * c - dy * sn, 0.5 + dx * sn + dy * c
        return (self.x + lx * self.scale, self.y + ly * self.scale)


@dataclass
class Block:
    camera_id: int
    zone_id: int
    name: str
    kind: str
    footprint: List[Tuple[float, float]]      # mundo (chão)
    height: float
    color: str
    see_through: bool
    status: Optional[str]                     # livre | ocupada | a_limpar (mesas) ou None
    people: Optional[int]
    short: str                                # rótulo curto (zoom baixo)
    lines: List[str]                          # rótulo completo (zoom alto / dica)
    alert: Optional[Alert] = None


@dataclass
class CameraSummary:
    camera_id: int
    name: str
    status: str                               # ok | connecting | offline | credentials | limit
    fps: float = 0.0
    people: Optional[int] = None
    tables: Dict[str, int] = field(default_factory=lambda: {"livre": 0, "ocupada": 0, "a_limpar": 0})
    alerts: int = 0
    reading: bool = True                      # False = reconhecimento desligado / sem Pessoa ("sem leitura")


@dataclass
class Section:
    camera_id: int
    name: str
    rect: Tuple[float, float, float, float]   # x0, y0, x1, y1 no mundo, SEM girar (referência do layout)
    status: str
    blocks: List[Block]
    summary: CameraSummary
    people: List[Tuple[int, float, float]] = field(default_factory=list)   # (id, x, y) no mundo: os pés de cada pessoa
    quad: List[Tuple[float, float]] = field(default_factory=list)          # os 4 cantos no mundo, já girados (é o que se desenha)
    rot: float = 0.0
    room: str = ""                                                         # sala da câmera (vazio = sem sala)
    units_per_m: Optional[float] = None                                    # unidades do mundo por metro (só com o chão calibrado)
    floor: List[Tuple[float, float]] = field(default_factory=list)         # os 4 cantos (mundo) do chão calibrado = a forma da sala; vazio sem calibração
    floor_m: Optional[Tuple[float, float]] = None                          # (largura, profundidade) reais desse chão, em metros
    people_sigma: List[Tuple[int, float, float, float]] = field(default_factory=list)   # (id, x, y, incerteza em metros) para a união entre câmeras
    camera: Optional[Tuple[float, float, float]] = None                    # (x, y, z) no mundo: onde a câmera está (recuperado do chão calibrado)
    fov: List[Tuple[float, float]] = field(default_factory=list)           # triângulo no chão (mundo) do que ela enxerga


@dataclass
class Scene:
    sections: List[Section]
    alerts: List[Alert]
    totals: dict
    crowd: List[Person] = field(default_factory=list)   # pessoas SEM duplicar (a mesma pessoa em 2 câmeras da mesma sala conta uma vez)

    def block(self, camera_id: int, zone_id: int) -> Optional[Block]:
        for s in self.sections:
            if s.camera_id == camera_id:
                return next((b for b in s.blocks if b.zone_id == zone_id), None)
        return None

    def section(self, camera_id: int) -> Optional[Section]:
        return next((s for s in self.sections if s.camera_id == camera_id), None)


# -- layout ---------------------------------------------------------------------------------------------------------
def auto_layout(camera_ids: Sequence[int], aspects: Dict[int, float]) -> Dict[int, Layout]:
    """Zonas lado a lado (PER_ROW por linha), na ordem das câmeras, sem sobrepor."""
    out: Dict[int, Layout] = {}
    x = y = row_h = 0.0
    for i, cid in enumerate(camera_ids):
        w = aspects.get(cid, DEFAULT_ASPECT)
        if i and i % PER_ROW == 0:
            x, y, row_h = 0.0, y + row_h + SECTION_GAP, 0.0
        out[cid] = Layout(x, y, 1.0)
        x += w + SECTION_GAP
        row_h = max(row_h, 1.0)
    return out


def clamp_scale(v: float) -> float:
    return max(MIN_SCALE, min(MAX_SCALE, v))


# -- alertas ---------------------------------------------------------------------------------------------------------
def area_alert(camera_id: int, area: dict, rules: AlertRules) -> Optional[Alert]:
    """Mesa a limpar há muito tempo; fila grande ou demorada."""
    kind, name, zid = area.get("kind"), area.get("name", ""), area.get("id")
    if kind == "mesa" and area.get("status") == "a_limpar":
        secs = int(area.get("seconds") or 0)
        if secs >= rules.clean_crit_s:
            return Alert("crit", "clean", camera_id, zid, f"{name} a limpar há {labels.fmt_dur(secs)}")
        if secs >= rules.clean_warn_s:
            return Alert("warn", "clean", camera_id, zid, f"{name} a limpar há {labels.fmt_dur(secs)}")
    if kind == "fila":
        people, wait = int(area.get("people") or 0), int(area.get("wait") or 0)
        if wait >= rules.queue_wait_crit_s or people >= rules.queue_people_crit:
            return Alert("crit", "queue", camera_id, zid, f"{name}: {labels.plural(people, 'pessoa', 'pessoas')}, espera {labels.fmt_dur(wait)}")
        if wait >= rules.queue_wait_warn_s or people >= rules.queue_people_warn:
            return Alert("warn", "queue", camera_id, zid, f"{name}: {labels.plural(people, 'pessoa', 'pessoas')}, espera {labels.fmt_dur(wait)}")
    return None


def camera_status(camera: dict, state: Optional[dict], limit_reached: bool = False) -> str:
    if camera.get("needs_credentials"):
        return "credentials"
    if limit_reached and state is None:
        return "limit"
    if state is None or not state.get("size"):
        return "connecting"                      # ainda sem o 1º quadro processado
    return "ok" if state.get("online", True) else "offline"


def _floor_corners(lay: "Layout", aspect: float, calib) -> List[Tuple[float, float]]:
    """O chão marcado na calibração (largura × profundidade reais) como retângulo no mundo: é a forma da sala no mapa."""
    if calib is None:
        return []
    k = calib.units_per_m(aspect)
    hw, hd = calib.width * k / 2, calib.depth * k / 2
    cx, cy = aspect / 2, 0.5
    return [lay.world(cx - hw, cy - hd, aspect), lay.world(cx + hw, cy - hd, aspect),
            lay.world(cx + hw, cy + hd, aspect), lay.world(cx - hw, cy + hd, aspect)]


def to_world(lay: "Layout", aspect: float, calib, x: float, y: float) -> Tuple[float, float]:
    """Ponto da imagem (0..1) no mundo. Com calibração do chão a perspectiva é corrigida; sem ela, mapeamento linear aproximado."""
    if calib is not None:
        loc = calib.to_local(x, y, aspect)
        if loc is not None:
            return lay.world(loc[0], loc[1], aspect)
    return lay.world(x * aspect, y, aspect)


@lru_cache(maxsize=32)
def geometry_for(calib, aspect: float) -> Optional[CameraGeometry]:
    """Posição e inclinação da câmera recuperadas do chão calibrado (ou None se a calibração não for coerente)."""
    g = CameraGeometry.from_calibration(calib._h(), calib.width, calib.depth, round(aspect, 4))
    return g if g.valid else None


def plan_to_world(lay: "Layout", aspect: float, calib, X: float, Y: float) -> Tuple[float, float]:
    """Ponto do plano do chão em METROS (origem no canto do fundo à esquerda do chão calibrado) -> mundo do mapa."""
    k = calib.units_per_m(aspect)
    return lay.world(aspect / 2 + (X - calib.width / 2) * k, 0.5 + (Y - calib.depth / 2) * k, aspect)


def _person_world(t: dict, lay: "Layout", aspect: float, calib, geom: Optional[CameraGeometry]) -> Tuple[float, float]:
    """Onde a pessoa está no mapa. Com o chão calibrado, pela MESMA geometria que decide se a mesa está ocupada (pés se em pé, cabeça se
    sentada ou encoberta); sem ela, o ponto dos pés pela homografia ou o mapeamento linear."""
    if geom is not None and t.get("h"):
        pos = geom.person_floor((t["x"] - 0.01, t["y"] - t["h"], t["x"] + 0.01, t["y"]))
        if pos is not None:
            return plan_to_world(lay, aspect, calib, *pos)
    return to_world(lay, aspect, calib, t["x"], t["y"])


def _camera_world(geom: Optional[CameraGeometry], lay: "Layout", aspect: float, calib) -> Optional[Tuple[float, float, float]]:
    if geom is None:
        return None
    x, y = plan_to_world(lay, aspect, calib, float(geom.C[0]), float(geom.C[1]))
    return (x, y, geom.height_m * calib.units_per_m(aspect) * lay.scale)


FOV_REACH_M = 12.0       # o triângulo de visão não vai além disto da câmera (o horizonte da imagem estica o chão ao infinito)


def _fov_wedge(geom: CameraGeometry, lay: "Layout", aspect: float, calib) -> List[Tuple[float, float]]:
    """Triângulo no chão (mundo) do que a câmera enxerga: do ponto sob a câmera até o chão do fundo da imagem, à esquerda e à direita."""
    ground = (float(geom.C[0]), float(geom.C[1]))

    def far_point(x: float):
        for y in (i / 20 for i in range(0, 20)):               # de cima (fundo) para baixo: o primeiro nível que bate no chão
            q = geom.at_height(x, y, 0.0)
            if q is not None:
                d = math.hypot(q[0] - ground[0], q[1] - ground[1])
                k = FOV_REACH_M / d if d > FOV_REACH_M else 1.0
                return (ground[0] + (q[0] - ground[0]) * k, ground[1] + (q[1] - ground[1]) * k)
        return None
    left, right = far_point(0.0), far_point(1.0)
    if left is None or right is None:
        return []
    return [plan_to_world(lay, aspect, calib, *p) for p in (ground, left, right)]


# -- cena -------------------------------------------------------------------------------------------------------------
def _block(camera_id: int, zone: dict, area: Optional[dict], state: Optional[dict], lay: Layout, aspect: float,
           status: str, blind: bool, rules: AlertRules, calib=None) -> Block:
    geom = geometry_for(calib, aspect) if calib is not None else None
    foot = geom.table_footprint(zone["points"]) if (geom is not None and zone["kind"] == "mesa") else None
    if foot is not None:                          # mesa: o polígono é o TAMPO; a pegada no chão (retroprojetada à altura do tampo) é o que vai ao mapa
        pts = [plan_to_world(lay, aspect, calib, X, Y) for X, Y in foot]
    else:
        pts = [to_world(lay, aspect, calib, x, y) for x, y in zone["points"]]
    kind = zone["kind"]
    no_read = blind and kind == "mesa"
    stat = area.get("status") if (area and kind == "mesa" and not no_read) else None
    if status in ("offline", "credentials", "limit", "connecting"):
        color = OFFLINE_COLOR
    elif no_read:
        color = labels.GRAY
    else:
        color = labels.area_color(kind, area, blind)
    people = area.get("people") if area else None
    name = zone["name"]
    kind_label = labels.KIND_LABEL.get(kind, kind)
    if status != "ok" or area is None:
        lines = [name, kind_label]
    elif no_read:
        lines = [name, "Sem leitura — " + labels.reading_hint(state) if labels.reading_hint(state) else "Sem leitura"]
    else:
        cap = labels.area_caption(kind, area)
        if kind == "mesa":
            # o caption de livre/a limpar já começa pelo estado ("Livre · 40 s"); o de ocupada não ("3 pessoas · 25 min")
            lines = [name, f"Ocupada · {cap}" if stat == "ocupada" else (cap or kind_label)]
        else:
            lines = [name, f"{kind_label} · {cap}" if cap else kind_label]
    short = f"{name} · {people}" if (status == "ok" and not no_read and people) else name
    alert = area_alert(camera_id, {**(area or {}), "kind": kind, "name": name, "id": zone["id"]}, rules) if (area and status == "ok") else None
    return Block(camera_id, zone["id"], name, kind, pts, HEIGHT.get(kind, 0.02) * lay.scale, color, kind in SEE_THROUGH,
                 stat, people, short, [l for l in lines if l], alert)


def build_scene(cameras: Sequence[dict], zones: Dict[int, list], states: Dict[int, Optional[dict]],
                layouts: Dict[int, Layout], aspects: Optional[Dict[int, float]] = None,
                rules: Optional[AlertRules] = None, limited: Sequence[int] = (), calibs: Optional[Dict[int, object]] = None,
                merger=None, now: float = 0.0) -> Scene:
    """Monta a cena inteira. `layouts` pode estar incompleto: o que faltar vem do `auto_layout`."""
    rules = rules or AlertRules()
    aspects = dict(aspects or {})
    for cid, st in states.items():                                   # a proporção real da câmera, quando já se sabe
        if st and st.get("size") and st["size"][1]:
            aspects[cid] = st["size"][0] / st["size"][1]
    ids = [c["id"] for c in cameras]
    auto = auto_layout(ids, aspects)
    sections: List[Section] = []
    alerts: List[Alert] = []
    for cam in cameras:
        cid = cam["id"]
        st = states.get(cid)
        lay = layouts.get(cid) or auto[cid]
        aspect = aspects.get(cid, DEFAULT_ASPECT)
        status = camera_status(cam, st, cid in limited)
        areas = {a["id"]: a for a in (st or {}).get("areas", [])}
        blind = labels.no_reading(st)
        calib = (calibs or {}).get(cid)
        blocks = [_block(cid, z, areas.get(z["id"]), st, lay, aspect, status, blind, rules, calib) for z in zones.get(cid, [])]
        geom = geometry_for(calib, aspect) if calib is not None else None
        summary = CameraSummary(cid, cam["name"], status, fps=float((st or {}).get("fps") or 0.0),
                                people=(st or {}).get("people") if status == "ok" else None, reading=not blind)
        for b in blocks:
            if b.kind == "mesa" and b.status in summary.tables:
                summary.tables[b.status] += 1
        cam_alerts = [b.alert for b in blocks if b.alert]
        if status == "offline":
            cam_alerts.append(Alert("warn", "offline", cid, None, f"{cam['name']} fora do ar"))
        elif status == "credentials":
            cam_alerts.append(Alert("warn", "credentials", cid, None, f"{cam['name']} aguardando usuário e senha"))
        elif status == "limit":
            cam_alerts.append(Alert("warn", "limit", cid, None, f"{cam['name']}: limite de câmeras simultâneas"))
        if cam.get("view_changed"):
            cam_alerts.append(Alert("warn", "view", cid, None, f"{cam['name']}: a imagem mudou (câmera ou mesa movida?) — remapear áreas e chão"))
        summary.alerts = len(cam_alerts)
        alerts += cam_alerts
        feet = [(t["id"], *_person_world(t, lay, aspect, calib, geom)) for t in (st or {}).get("tracks", [])] if status == "ok" else []
        sig = ([calib.foot_sigma_m(t["x"], t["y"], aspect) if calib is not None else 1.0 for t in (st or {}).get("tracks", [])]
               if status == "ok" else [])
        sections.append(Section(cid, cam["name"], (lay.x, lay.y, lay.x + aspect * lay.scale, lay.y + lay.scale), status, blocks, summary, feet,
                                [lay.world(a, b, aspect) for a, b in ((0, 0), (aspect, 0), (aspect, 1), (0, 1))], lay.rot,
                                cam.get("room") or "", calib.units_per_m(aspect) * lay.scale if calib is not None else None,
                                _floor_corners(lay, aspect, calib), (calib.width, calib.depth) if calib is not None else None,
                                [(pid, x, y, sg) for (pid, x, y), sg in zip(feet, sig)],
                                _camera_world(geom, lay, aspect, calib), _fov_wedge(geom, lay, aspect, calib) if geom is not None else []))
    alerts.sort(key=lambda a: (0 if a.level == "crit" else 1, a.text))
    dots = [Dot(s.camera_id, pid, x, y, s.room, s.units_per_m, sg, s.floor or None) for s in sections for pid, x, y, sg in s.people_sigma]
    crowd, duplicates = merger.merge(dots, now) if merger is not None else merge(dots)
    totals = {"people": max(0, sum(s.summary.people or 0 for s in sections) - duplicates), "duplicates": duplicates,
              "tables": {k: sum(s.summary.tables[k] for s in sections) for k in ("livre", "ocupada", "a_limpar")},
              "alerts": len(alerts), "crit": sum(1 for a in alerts if a.level == "crit"),
              "cameras": len(sections), "cameras_ok": sum(1 for s in sections if s.status == "ok")}
    return Scene(sections, alerts, totals, crowd)


# -- geometria de tela / interação ---------------------------------------------------------------------------------
def scene_points(scene: Scene, pj: "iso.Projector") -> List[Tuple[float, float]]:
    """Todos os pontos da cena em tela (para ajustar o zoom): cantos das zonas e topos dos blocos."""
    pts = []
    for s in scene.sections:
        pts += pj.polygon(s.floor or s.quad, 0)
        if s.camera:
            pts.append(pj.project(*s.camera))
        for b in s.blocks:
            pts += pj.polygon(b.footprint, b.height)
    return pts


def _area(pts: Sequence[Tuple[float, float]]) -> float:
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2


def ordered_blocks(scene: Scene, pj: "iso.Projector") -> List[Block]:
    """Blocos na ORDEM DE DESENHO (de trás para frente). Empate de profundidade: o menor vai por cima (mesa dentro de uma
    área grande). A tela desenha nesta ordem e o clique percorre ao contrário, então os dois sempre concordam."""
    items = []
    for s in scene.sections:
        for b in s.blocks:
            cx = sum(p[0] for p in b.footprint) / len(b.footprint)
            cy = sum(p[1] for p in b.footprint) / len(b.footprint)
            items.append((round(pj.depth(cx, cy), 6), -_area(b.footprint), len(items), b))
    return [b for *_k, b in sorted(items, key=lambda t: t[:3])]


def pick(scene: Scene, pj: "iso.Projector", sx: float, sy: float) -> Optional[tuple]:
    """O que está sob um pixel: ("block", camera_id, zone_id), ("section", camera_id) ou None. O mais PERTO ganha."""
    for b in reversed(ordered_blocks(scene, pj)):
        prism = pj.prism(b.footprint, 0, b.height)
        polys = [list(prism.top)] + [list(f.points) for f in prism.sides]
        if any(point_in_polygon(sx, sy, poly) for poly in polys):
            return ("block", b.camera_id, b.zone_id)
    ground = pj.unproject_ground(sx, sy)
    if ground:
        for s in reversed(scene.sections):
            if point_in_polygon(ground[0], ground[1], s.quad):
                return ("section", s.camera_id)
    return None
