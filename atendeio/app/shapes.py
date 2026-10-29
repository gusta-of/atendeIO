"""Geometria das formas (retângulo, quadrado, círculo/elipse, triângulo, polígono livre). Lógica pura, sem Qt.

Porta de `web/src/app/shared/shapes.ts` SEM mudar a matemática.

- Pontos salvos são NORMALIZADOS (0..1). Girar neles distorceria a forma (a imagem não é quadrada), então a conta é feita em
  "espaço de pixels": X = x*W, Y = y*H.
- Formas primitivas são descritas por uma caixa orientada (OBB): `Obb(cx, cy, w, h, angle)` com o ângulo em radianos.
- Polígono livre ("poly") não tem OBB: gira em torno do centro da sua caixa."""

import math
from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

Point = Tuple[float, float]
ELLIPSE_POINTS = 32
EPS = 1e-6
PRIMITIVES = ("rect", "square", "ellipse", "triangle")


@dataclass(frozen=True)
class Obb:
    cx: float
    cy: float
    w: float
    h: float
    angle: float = 0.0


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float


def deg2rad(d: float) -> float:
    return d * math.pi / 180


def rad2deg(r: float) -> float:
    return r * 180 / math.pi


def wrap_deg(d: float) -> float:
    """Normaliza um ângulo (graus) para [-180, 180)."""
    return ((d + 180) % 360) - 180


def rot(x: float, y: float, a: float) -> Point:
    c, s = math.cos(a), math.sin(a)
    return (x * c - y * s, x * s + y * c)


def outline(shape: str, obb: Obb) -> List[Point]:
    """Contorno (em pixels) de uma forma primitiva descrita pela OBB."""
    w, h = obb.w, obb.h
    if shape == "ellipse":
        local = [((w / 2) * math.cos(2 * math.pi * i / ELLIPSE_POINTS), (h / 2) * math.sin(2 * math.pi * i / ELLIPSE_POINTS))
                 for i in range(ELLIPSE_POINTS)]
    elif shape == "triangle":
        local = [(0, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]          # ponta pra cima
    else:
        local = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    out = []
    for lx, ly in local:
        rx, ry = rot(lx, ly, obb.angle)
        out.append((obb.cx + rx, obb.cy + ry))
    return out


def to_norm(pts: List[Point], W: float, H: float) -> List[Point]:
    return [(x / W, y / H) for x, y in pts]


def to_px(pts: List[Point], W: float, H: float) -> List[Point]:
    return [(x * W, y * H) for x, y in pts]


def points_from_obb(shape: str, obb: Obb, W: float, H: float) -> List[Point]:
    return to_norm(outline(shape, obb), W, H)


def obb_from_points(points: List[Point], angle_deg: float, W: float, H: float) -> Obb:
    """Recupera a OBB de uma forma salva (pontos normalizados + ângulo em graus)."""
    a = deg2rad(angle_deg or 0)
    local = [rot(x, y, -a) for x, y in to_px(points, W, H)]
    xs, ys = [p[0] for p in local], [p[1] for p in local]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    cx, cy = rot((min_x + max_x) / 2, (min_y + max_y) / 2, a)
    return Obb(cx, cy, max_x - min_x, max_y - min_y, a)


def obb_from_drag(x0: float, y0: float, x1: float, y1: float) -> Obb:
    """OBB (sem rotação) de um arrasto "canto a canto"."""
    return Obb((x0 + x1) / 2, (y0 + y1) / 2, abs(x1 - x0), abs(y1 - y0), 0.0)


CORNER_SIGNS = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
EDGE_SIGNS = [(0, -1), (1, 0), (0, 1), (-1, 0)]    # topo, direita, base, esquerda (eixo local)


def corners(obb: Obb) -> List[Point]:
    """Posição (px) dos 4 cantos da OBB, na ordem de CORNER_SIGNS."""
    out = []
    for sx, sy in CORNER_SIGNS:
        rx, ry = rot(sx * obb.w / 2, sy * obb.h / 2, obb.angle)
        out.append((obb.cx + rx, obb.cy + ry))
    return out


def resize_from_corner(obb: Obb, index: int, pointer: Point, keep_ratio: bool = False) -> Obb:
    """Redimensiona arrastando o canto `index`; o canto oposto fica parado (vale com a forma girada).
    `keep_ratio`: mantém a proporção largura/altura (quadrado, ou Shift no arrasto)."""
    sx, sy = CORNER_SIGNS[index]
    fixed = (-sx * obb.w / 2, -sy * obb.h / 2)
    px, py = rot(pointer[0] - obb.cx, pointer[1] - obb.cy, -obb.angle)
    w, h = abs(px - fixed[0]), abs(py - fixed[1])
    mx, my = (fixed[0] + px) / 2, (fixed[1] + py) / 2
    if keep_ratio and obb.w > EPS and obb.h > EPS:
        k = max(w / obb.w, h / obb.h)
        w, h = obb.w * k, obb.h * k
        mx = fixed[0] + (1 if px >= fixed[0] else -1) * (w / 2)
        my = fixed[1] + (1 if py >= fixed[1] else -1) * (h / 2)
    wx, wy = rot(mx, my, obb.angle)
    return Obb(obb.cx + wx, obb.cy + wy, w, h, obb.angle)


def edge_midpoints(obb: Obb) -> List[Point]:
    """Posição (px) do meio de cada lado da OBB, na ordem de EDGE_SIGNS."""
    out = []
    for sx, sy in EDGE_SIGNS:
        rx, ry = rot(sx * obb.w / 2, sy * obb.h / 2, obb.angle)
        out.append((obb.cx + rx, obb.cy + ry))
    return out


def resize_from_edge(obb: Obb, index: int, pointer: Point) -> Obb:
    """Arrasta o meio de um lado: muda SÓ a largura (esquerda/direita) ou SÓ a altura (topo/base)."""
    sx, sy = EDGE_SIGNS[index]
    px, py = rot(pointer[0] - obb.cx, pointer[1] - obb.cy, -obb.angle)
    if sx == 0:
        fixed = -sy * obb.h / 2
        wx, wy = rot(0, (fixed + py) / 2, obb.angle)
        return Obb(obb.cx + wx, obb.cy + wy, obb.w, abs(py - fixed), obb.angle)
    fixed = -sx * obb.w / 2
    wx, wy = rot((fixed + px) / 2, 0, obb.angle)
    return Obb(obb.cx + wx, obb.cy + wy, abs(px - fixed), obb.h, obb.angle)


def with_size(obb: Obb, w: float, h: float) -> Obb:
    """Novo tamanho mantendo o centro (campos numéricos)."""
    return replace(obb, w=w, h=h)


def angle_toward(center: Point, pointer: Point) -> float:
    """Ângulo (rad) da OBB para que a alça de rotação (acima do topo) aponte para o ponteiro."""
    return math.atan2(pointer[1] - center[1], pointer[0] - center[0]) + math.pi / 2


def rotate_handle(obb: Obb, gap: float = 28) -> Point:
    """Posição (px) da alça de rotação: acima do centro do topo, `gap` px além da borda."""
    rx, ry = rot(0, -obb.h / 2 - gap, obb.angle)
    return (obb.cx + rx, obb.cy + ry)


def rotate_points(pts: List[Point], center: Point, delta: float) -> List[Point]:
    out = []
    for x, y in pts:
        rx, ry = rot(x - center[0], y - center[1], delta)
        out.append((center[0] + rx, center[1] + ry))
    return out


def bbox(pts: List[Point]) -> Box:
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return Box(min(xs), min(ys), max(xs), max(ys))


def fit_inside(pts: List[Point], W: float, H: float) -> Optional[Tuple[List[Point], float, float]]:
    """Garante que a forma (px) fique dentro do quadro [0,W]x[0,H]: se passou da borda, empurra de volta.
    Devolve None se a forma é maior que o quadro (não cabe): o chamador descarta o passo."""
    b = bbox(pts)
    if b.x1 - b.x0 > W + EPS or b.y1 - b.y0 > H + EPS:
        return None
    dx = dy = 0.0
    if b.x0 < 0:
        dx = -b.x0
    elif b.x1 > W:
        dx = W - b.x1
    if b.y0 < 0:
        dy = -b.y0
    elif b.y1 > H:
        dy = H - b.y1
    return [(x + dx, y + dy) for x, y in pts], dx, dy


def thumb_points(points: List[Point], ar: float, width: float = 34, height: float = 24) -> List[Point]:
    """Pontos (já em coordenadas do ícone `width`×`height`) de uma prévia da forma. Respeita a proporção da imagem
    (`ar` = W/H): um retângulo girado aparece girado e um círculo continua redondo."""
    px = [(x * ar, y) for x, y in points]
    b = bbox(px)
    bw, bh = max(b.x1 - b.x0, EPS), max(b.y1 - b.y0, EPS)
    pad = 2
    k = min((width - 2 * pad) / bw, (height - 2 * pad) / bh)
    ox, oy = (width - bw * k) / 2 - b.x0 * k, (height - bh * k) / 2 - b.y0 * k
    return [(x * k + ox, y * k + oy) for x, y in px]


def catalog(shape: str) -> List[Point]:
    """Contorno normalizado de cada forma "de catálogo" (ícones dos botões), no quadro 1:1."""
    if shape == "poly":
        return [(0.1, 0.3), (0.55, 0.05), (0.95, 0.4), (0.75, 0.95), (0.2, 0.8)]
    if shape == "rect":
        obb = Obb(0.5, 0.5, 0.95, 0.6)
    elif shape == "square":
        obb = Obb(0.5, 0.5, 0.72, 0.72)
    else:
        obb = Obb(0.5, 0.5, 0.8, 0.8)
    return to_norm(outline(shape, obb), 1, 1)
