"""Calibração do chão por 4 pontos (puro, sem Qt): corrige a perspectiva da câmera para o Mapa.

O utilizador marca na imagem os 4 cantos de um retângulo do chão (ex.: uma mesa, um ladrilho, a faixa de uma porta) e diz o
tamanho real dele. A homografia leva qualquer ponto do chão da imagem para a planta, então a pessoa e as áreas caem onde estão
de verdade, mesmo com a câmera alta ou inclinada. Sem calibração o Mapa usa o mapeamento linear aproximado."""

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

Pt = Tuple[float, float]
FILL = 0.7          # fração da zona da câmera que o retângulo calibrado ocupa no mapa
OUTSIDE = 0.6       # os pontos podem ficar até isso FORA da imagem (o chão continua além do que a câmera mostra)
LIMIT = 1.5         # fora disso (em zonas) o ponto é recortado: perto do horizonte a projeção explode


def _cross(o: Pt, a: Pt, b: Pt) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def canonical(pts: Sequence[Pt]) -> Tuple[Pt, ...]:
    """Põe os 4 pontos na ordem fundo-esquerda, fundo-direita, frente-direita, frente-esquerda, qualquer que tenha sido a ordem
    dos cliques: os dois de cima na imagem são o fundo (mais longe da câmera), os de baixo a frente; em cada par, esquerda antes de direita."""
    if len(pts) != 4:
        return tuple(pts)
    by_y = sorted(pts, key=lambda p: p[1])
    far, near = sorted(by_y[:2], key=lambda p: p[0]), sorted(by_y[2:], key=lambda p: p[0])
    return (far[0], far[1], near[1], near[0])


def validate(pts: Sequence[Pt], width: float, depth: float) -> None:
    """Levanta ValueError (mensagem para o utilizador) se os pontos não formam um quadrilátero convexo com tamanho real válido."""
    if len(pts) != 4:
        raise ValueError("Marque exatamente 4 pontos.")
    for x, y in pts:
        if not (-OUTSIDE <= x <= 1.0 + OUTSIDE and -OUTSIDE <= y <= 1.0 + OUTSIDE):
            raise ValueError("Um ponto está longe demais da imagem.")
    if not (0.05 <= width <= 1000 and 0.05 <= depth <= 1000):
        raise ValueError("Informe a largura e a profundidade reais (em metros).")
    signs = [_cross(pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]) for i in range(4)]
    if not (all(s > 1e-5 for s in signs) or all(s < -1e-5 for s in signs)):
        raise ValueError("Os 4 pontos devem formar um quadrilátero do chão (sem três em linha reta e sem se cruzar).")


def _homography(src: Sequence[Pt], dst: Sequence[Pt]) -> np.ndarray:
    a, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    h = np.linalg.solve(np.array(a, float), np.array(b, float))
    return np.append(h, 1.0).reshape(3, 3)


@dataclass(frozen=True)
class FloorCalib:
    pts: Tuple[Pt, ...]      # 4 pontos da imagem (0..1, podem sair um pouco da imagem), guardados como fundo-esq, fundo-dir, frente-dir, frente-esq
    width: float             # metros, de um lado ao outro (esquerda-direita na imagem)
    depth: float             # metros, do fundo à frente

    def __post_init__(self):
        object.__setattr__(self, "pts", canonical(self.pts))      # a ordem dos cliques não importa
        validate(self.pts, self.width, self.depth)

    def _h(self) -> np.ndarray:
        return _homography(self.pts, [(0, 0), (1, 0), (1, 1), (0, 1)])

    def to_local(self, x: float, y: float, aspect: float) -> Optional[Pt]:
        """Ponto da imagem (0..1) -> coordenada local da zona da câmera (x em 0..aspect, y em 0..1), ou None se não houver chão ali."""
        p = self._h() @ np.array([x, y, 1.0])
        if abs(p[2]) < 1e-9:
            return None
        u, v = p[0] / p[2], p[1] / p[2]
        k = FILL * min(aspect / self.width, 1.0 / self.depth)          # metros -> unidades locais
        lx = aspect / 2 + (u - 0.5) * self.width * k
        ly = 0.5 + (v - 0.5) * self.depth * k
        return (min(max(lx, -LIMIT * aspect), (1 + LIMIT) * aspect), min(max(ly, -LIMIT), 1 + LIMIT))

    def to_dict(self) -> dict:
        return {"pts": [list(p) for p in self.pts], "width": self.width, "depth": self.depth}

    @staticmethod
    def from_dict(d: dict) -> "FloorCalib":
        return FloorCalib(tuple((float(x), float(y)) for x, y in d["pts"]), float(d["width"]), float(d["depth"]))
