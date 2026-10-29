"""Projeção isométrica/oblíqua 2.5D (sem Qt): do "mundo" para a tela, extrusão de polígonos e ordem de desenho.

Mundo: `x` à direita, `y` na profundidade (para baixo na imagem da câmera) e `z` na altura. O olhar é uma órbita:
`yaw` gira o mundo em torno do eixo vertical e `pitch` inclina a câmera (90° = vista de cima; ~35° com yaw 45° = isométrico clássico).

    x' = x·cos(yaw) − y·sin(yaw)        y' = x·sin(yaw) + y·cos(yaw)         (y' cresce em direção ao observador)
    sx = x'·s                           sy = (y'·sin(pitch) − z·cos(pitch))·s

Tudo é função pura, então é testável sem tela e barata de desenhar com QPainter em software (sem GPU)."""

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

Point = Tuple[float, float]
ISO_PITCH = math.asin(math.tan(math.radians(30)))      # ≈ 35,26°: inclinação do isométrico clássico
ISO_YAW = math.radians(45)


@dataclass(frozen=True)
class Face:
    points: Tuple[Point, ...]      # em coordenadas de tela
    shade: float                   # 0..1: multiplicador de brilho (1 = topo/iluminado)


@dataclass(frozen=True)
class Prism:
    """Polígono extrudido: faces laterais VISÍVEIS (já sombreadas) + topo. Desenhe as laterais e depois o topo."""
    sides: Tuple[Face, ...]
    top: Tuple[Point, ...]
    depth: float                   # chave de ordenação (y' do centroide): maior = mais perto do observador


def rotate(x: float, y: float, yaw: float) -> Point:
    c, s = math.cos(yaw), math.sin(yaw)
    return (x * c - y * s, x * s + y * c)


class Projector:
    def __init__(self, yaw: float = math.radians(20), pitch: float = math.radians(52), scale: float = 100.0,
                 origin: Point = (0.0, 0.0)):
        self.yaw, self.pitch, self.scale, self.origin = yaw, pitch, scale, origin

    # -- ponto a ponto --------------------------------------------------------------------------------------
    def project(self, x: float, y: float, z: float = 0.0) -> Point:
        xr, yr = rotate(x, y, self.yaw)
        s = self.scale
        return (self.origin[0] + xr * s, self.origin[1] + (yr * math.sin(self.pitch) - z * math.cos(self.pitch)) * s)

    def depth(self, x: float, y: float) -> float:
        """Distância ao observador (maior = mais perto): serve para desenhar de trás para frente."""
        return rotate(x, y, self.yaw)[1]

    def unproject_ground(self, sx: float, sy: float) -> Optional[Point]:
        """Ponto do mundo (no chão, z = 0) sob um pixel da tela. None se a vista é de lado (pitch ≈ 0)."""
        sp = math.sin(self.pitch)
        if abs(sp) < 1e-6:
            return None
        xr = (sx - self.origin[0]) / self.scale
        yr = (sy - self.origin[1]) / (self.scale * sp)
        return rotate(xr, yr, -self.yaw)

    # -- polígonos ----------------------------------------------------------------------------------------------
    def polygon(self, pts: Sequence[Point], z: float = 0.0) -> List[Point]:
        return [self.project(x, y, z) for x, y in pts]

    def prism(self, pts: Sequence[Point], z0: float, z1: float) -> Prism:
        """Extrusão de `pts` (no chão) de `z0` até `z1`: topo + só as laterais voltadas para o observador."""
        rot = [rotate(x, y, self.yaw) for x, y in pts]
        area = sum(rot[i][0] * rot[(i + 1) % len(rot)][1] - rot[(i + 1) % len(rot)][0] * rot[i][1] for i in range(len(rot)))
        sign = 1.0 if area > 0 else -1.0
        sides = []
        for i in range(len(pts)):
            j = (i + 1) % len(pts)
            dx, dy = rot[j][0] - rot[i][0], rot[j][1] - rot[i][1]
            length = math.hypot(dx, dy)
            if length < 1e-9:
                continue
            nx, ny = sign * dy / length, -sign * dx / length          # normal para fora, no espaço girado
            if ny <= 1e-9:                                           # de costas para o observador: não aparece
                continue
            shade = max(0.45, min(1.0, 0.55 + 0.35 * ny - 0.15 * nx))
            a, b = pts[i], pts[j]
            quad = (self.project(a[0], a[1], z0), self.project(b[0], b[1], z0),
                    self.project(b[0], b[1], z1), self.project(a[0], a[1], z1))
            sides.append(Face(quad, shade))
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        return Prism(tuple(sides), tuple(self.polygon(pts, z1)), self.depth(cx, cy))


def draw_order(items: Sequence, key=lambda it: it.depth) -> list:
    """Ordem de desenho de trás para frente (o mais distante primeiro)."""
    return sorted(items, key=key)


def bounds(points: Sequence[Point]) -> Tuple[float, float, float, float]:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def fit(points: Sequence[Point], width: float, height: float, margin: float = 24.0) -> Tuple[float, Point]:
    """(fator de escala, deslocamento) para caber `points` (em tela, com scale=1/origem=0) numa área `width`×`height`."""
    x0, y0, x1, y1 = bounds(points)
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    k = min((width - 2 * margin) / w, (height - 2 * margin) / h)
    return k, (width / 2 - (x0 + x1) / 2 * k, height / 2 - (y0 + y1) / 2 * k)
