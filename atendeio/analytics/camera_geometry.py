"""Geometria da câmera a partir do chão calibrado (puro, numpy): posição de pessoas e mesas em METROS, para qualquer posição de câmera.

Com o retângulo do chão calibrado (4 pontos + largura × profundidade reais) a homografia plano→imagem é conhecida. Supondo pixel quadrado e centro
óptico no centro da imagem, ela fixa a distância focal e a pose da câmera (altura e inclinação): é a calibração por plano de Zhang. Daí:
  - o PÉ de uma pessoa (ponto do chão) vira posição em metros;
  - o polígono de uma mesa, desenhado no TAMPO, desce até o chão (retroprojetado à altura do tampo): é a pegada real da mesa;
  - quem está sentado/encoberto (caixa que não chega ao chão) é posicionado pela cabeça, a uma altura de cabeça sentada.
Assim "está na mesa" é a distância real entre pessoa e mesa, sem constantes ajustadas por cena."""

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

Pt = Tuple[float, float]
TABLE_H = 0.75           # altura do tampo (m)
STAND_H = 1.70           # altura de uma pessoa em pé (m)
SEAT_HEAD_H = 1.30       # altura do TOPO da cabeça de quem está sentado (m): assento ~0,45 + tronco e cabeça ~0,85
SEAT_BOX_H = 0.45        # altura do fundo da caixa de quem está sentado com as pernas encobertas (assento / joelhos)
F_RANGE = (0.55, 1.5)    # distância focal plausível (em alturas de imagem): campo horizontal de ~125° a ~65°; câmeras comuns (webcam, IP)
F_PRIOR = 0.9            # usada (no lugar da estimada) quando a estimada sai do intervalo: calibração manual com 4 pontos é ruidosa
HYPOTHESES = ((0.0, STAND_H), (0.0, SEAT_HEAD_H), (SEAT_BOX_H, SEAT_HEAD_H))   # (altura do fundo, altura do topo da caixa): em pé; sentada com os
                                                                              # pés à vista; sentada com as pernas encobertas
RESIDUAL_TIE = 0.04      # hipóteses cujo erro no topo da caixa fica a esta distância da melhor também são plausíveis
BOTTOM = 0.985           # caixa colada embaixo: pés fora do quadro


@dataclass
class CameraGeometry:
    f: float
    R: np.ndarray
    t: np.ndarray
    C: np.ndarray
    s_z: float                 # +1 se "para cima" é +Z no referencial do plano, -1 se for -Z
    aspect: float
    valid: bool = True

    # -- construção ------------------------------------------------------------------------------------------------
    @staticmethod
    def from_calibration(img_to_unit: np.ndarray, width_m: float, depth_m: float, aspect: float) -> "CameraGeometry":
        """`img_to_unit`: homografia 3×3 de (x, y, 1) normalizados da imagem para o retângulo do chão (0..1)."""
        bad = CameraGeometry(1.0, np.eye(3), np.zeros(3), np.zeros(3), 1.0, aspect, valid=False)
        try:
            to_plan = np.diag([width_m, depth_m, 1.0]) @ img_to_unit
            a_inv = np.linalg.inv(np.array([[aspect, 0, -0.5 * aspect], [0, 1, -0.5], [0, 0, 1.0]]))
            hpi = np.linalg.inv(to_plan @ a_inv)                       # plano (X, Y, 1) -> imagem (u, v, 1), em unidades de altura
            h1, h2, h3 = hpi[:, 0], hpi[:, 1], hpi[:, 2]
            # 1/f² por mínimos quadrados das duas restrições (colunas ortogonais e de mesma norma)
            c = np.array([h1[0] * h2[0] + h1[1] * h2[1], (h1[0] ** 2 + h1[1] ** 2) - (h2[0] ** 2 + h2[1] ** 2)])
            d = np.array([h1[2] * h2[2], h1[2] ** 2 - h2[2] ** 2])
            a = -float(c @ d) / float(c @ c)
            if not (a > 0):
                a = 1.0 / (F_PRIOR * F_PRIOR)
            f = 1.0 / math.sqrt(a)
            if not (F_RANGE[0] <= f <= F_RANGE[1]):
                f = F_PRIOR                                           # estimativa implausível (pontos imprecisos): vale a distância focal típica
            kinv = np.diag([1.0 / f, 1.0 / f, 1.0])
            r1, r2, t = kinv @ h1, kinv @ h2, kinv @ h3
            lam = 2.0 / (np.linalg.norm(r1) + np.linalg.norm(r2))
            r1, r2, t = r1 * lam, r2 * lam, t * lam
            if t[2] < 0:                                              # o plano tem de ficar na frente da câmera
                r1, r2, t = -r1, -r2, -t
            r3 = np.cross(r1, r2)
            u, _s, vt = np.linalg.svd(np.column_stack([r1, r2, r3]))   # ortonormaliza (ruído nos 4 pontos)
            rot = u @ vt
            if np.linalg.det(rot) < 0:
                rot = u @ np.diag([1, 1, -1]) @ vt
            center = -rot.T @ t
            s_z = 1.0 if center[2] > 0 else -1.0
            return CameraGeometry(f, rot, t, center, s_z, aspect)
        except (np.linalg.LinAlgError, ValueError, ZeroDivisionError):
            return bad

    # -- câmera <-> mundo ---------------------------------------------------------------------------------------
    @property
    def height_m(self) -> float:
        return abs(float(self.C[2]))

    def _ray(self, x: float, y: float) -> np.ndarray:
        u, v = (x - 0.5) * self.aspect, y - 0.5
        return self.R.T @ np.array([u / self.f, v / self.f, 1.0])

    def at_height(self, x: float, y: float, h: float) -> Optional[Pt]:
        """Ponto (X, Y) em metros no plano do chão que está sob o ponto da imagem (x, y) quando este está a `h` metros de altura."""
        d = self._ray(x, y)
        z = self.s_z * h
        if abs(d[2]) < 1e-9:
            return None
        lam = (z - self.C[2]) / d[2]
        if lam <= 0:
            return None
        p = self.C + lam * d
        return (float(p[0]), float(p[1]))

    def project(self, X: float, Y: float, Z_up: float) -> Tuple[float, float]:
        """Ponto do mundo (X, Y em m; altura Z_up em m) -> (x, y) normalizados da imagem."""
        pc = self.R @ np.array([X, Y, self.s_z * Z_up]) + self.t
        return (self.f * pc[0] / pc[2] / self.aspect + 0.5, self.f * pc[1] / pc[2] + 0.5)

    # -- mesas e pessoas -------------------------------------------------------------------------------------------
    def table_footprint(self, polygon: Sequence[Pt], table_h: float = TABLE_H) -> Optional[List[Pt]]:
        """A pegada da mesa no chão (m): o polígono do tampo (imagem) retroprojetado à altura do tampo."""
        out = []
        for x, y in polygon:
            p = self.at_height(x, y, table_h)
            if p is None:
                return None
            out.append(p)
        return out

    def person_candidates(self, box: Tuple[float, float, float, float]) -> List[Tuple[Pt, float]]:
        """Posições plausíveis da pessoa no chão (m), da mais para a menos provável, com o erro (altura da imagem) da hipótese.

        Para cada hipótese (em pé; sentada com os pés à vista; sentada com as pernas encobertas) o fundo da caixa dá um ponto do chão e o
        TOPO da caixa confere: onde cairia a cabeça dessa pessoa na imagem? O erro entre isso e o topo observado escolhe a hipótese; as que
        ficam quase tão boas também são devolvidas (a ambiguidade é real). Cada posição é a média da estimativa pelo fundo e pela cabeça.
        Pés fora do quadro: só a cabeça (em pé)."""
        x1, y1, x2, y2 = box
        cx = (x1 + x2) / 2
        head_visible = y1 > 0.01
        if y2 >= BOTTOM:
            p = self.at_height(cx, y1, STAND_H) if head_visible else self.at_height(cx, y2, 0.0)
            return [(p, 0.0)] if p is not None else []
        out: List[Tuple[Pt, float]] = []
        for hb, ht in HYPOTHESES:
            bottom = self.at_height(cx, y2, hb)
            if bottom is None:
                continue
            if not head_visible:
                out.append((bottom, 0.5))                                # sem a cabeça não há conferência: só o fundo, com pouca confiança
                continue
            top_pred = self.project(bottom[0], bottom[1], ht)[1]
            head = self.at_height(cx, y1, ht)
            out.append((_mid(bottom, head) if head is not None else bottom, abs(top_pred - y1)))
        out.sort(key=lambda c: c[1])
        return out

    def person_floor(self, box: Tuple[float, float, float, float]) -> Optional[Pt]:
        """A posição mais provável da pessoa no chão (m): a melhor hipótese de `person_candidates`."""
        c = self.person_candidates(box)
        return c[0][0] if c else None

    def person_floor_options(self, box: Tuple[float, float, float, float]) -> List[Pt]:
        """Todas as posições plausíveis (a melhor e as que ficam quase tão boas): quem decide "está na mesa?" dá o benefício da dúvida."""
        c = self.person_candidates(box)
        return [p for p, r in c if r <= c[0][1] + RESIDUAL_TIE] if c else []


def _mid(a: Pt, b: Pt) -> Pt:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
