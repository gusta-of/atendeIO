"""Alinhar as zonas de duas câmeras da mesma sala usando UMA pessoa que anda (puro, sem Qt).

Enquanto só uma pessoa está na sala, cada câmera a vê uma vez: cada instante dá um par (posição no plano da câmera B, posição no plano
da câmera A), em metros. Com alguns pares espalhados, o movimento rígido (giro + deslocamento) que leva B em A é o mínimo-quadrados
(Procrustes 2D). Daí sai o layout (posição, giro e escala) da zona de B no mapa, de modo que o chão dela coincida com o de A."""

import math
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .map_model import Layout

Pt = Tuple[float, float]
MIN_PAIRS = 8
MIN_SPREAD_M = 0.6          # as posições precisam cobrir pelo menos isto (senão o giro não é determinado)
MAX_RMS_M = 0.7             # erro médio aceitável depois do ajuste


class AlignError(ValueError):
    pass


def fit_rigid(pairs: Sequence[Tuple[Pt, Pt]]) -> Tuple[float, float, float, float]:
    """pairs: [(pB, pA)] em metros. Devolve (theta, tx, ty, rms) tal que pA ≈ R(theta)·pB + t."""
    if len(pairs) < MIN_PAIRS:
        raise AlignError(f"Poucos instantes com a pessoa nas duas câmeras ({len(pairs)}; precisa de {MIN_PAIRS}). "
                         "Fique sozinho(a) na sala, visível nas duas, e ande um pouco.")
    n = len(pairs)
    bx = sum(p[0][0] for p in pairs) / n
    by = sum(p[0][1] for p in pairs) / n
    ax = sum(p[1][0] for p in pairs) / n
    ay = sum(p[1][1] for p in pairs) / n
    spread = max(math.hypot(p[0][0] - bx, p[0][1] - by) for p in pairs)
    if spread < MIN_SPREAD_M / 2:
        raise AlignError("A pessoa quase não se moveu: ande pela sala (pelo menos uns 1,5 m) durante o alinhamento.")
    num = sum((p[0][0] - bx) * (p[1][1] - ay) - (p[0][1] - by) * (p[1][0] - ax) for p in pairs)
    den = sum((p[0][0] - bx) * (p[1][0] - ax) + (p[0][1] - by) * (p[1][1] - ay) for p in pairs)
    theta = math.atan2(num, den)
    c, s = math.cos(theta), math.sin(theta)
    tx, ty = ax - (c * bx - s * by), ay - (s * bx + c * by)
    err = [math.hypot(c * p[0][0] - s * p[0][1] + tx - p[1][0], s * p[0][0] + c * p[0][1] + ty - p[1][1]) for p in pairs]
    rms = math.sqrt(sum(e * e for e in err) / n)
    if rms > MAX_RMS_M:
        raise AlignError(f"As duas câmeras não concordam (erro de {rms:.1f} m). Confira a calibração do chão de cada uma "
                         "ou se havia mais de uma pessoa na sala.")
    return theta, tx, ty, rms


def layout_for(a: Layout, asp_a: float, k_a: float, asp_b: float, k_b: float, theta: float, tx: float, ty: float,
               scale_range: Tuple[float, float] = (0.4, 3.0)) -> Layout:
    """Layout da zona de B para que o chão dela coincida com o de A. k_* = unidades locais por metro (FloorCalib.units_per_m).
    A escala de B iguala os metros dos dois lados (u = escala·k constante); se a faixa permitida não deixar, levanta AlignError."""
    u = a.scale * k_a
    s_b = u / k_b
    if not (scale_range[0] <= s_b <= scale_range[1]):
        raise AlignError("A zona desta câmera ficaria grande ou pequena demais no mapa para coincidir com a outra. "
                         "Ajuste o tamanho (Zona +/−) da câmera de referência e tente de novo.")
    ra = math.radians(a.rot)
    ca, sa = math.cos(ra), math.sin(ra)
    # posição de A para o ponto do plano (tx, ty) em metros: o centro local de A + rotação de A · (u·t em unidades de escala 1)
    ox_a = a.x + a.scale * (asp_a / 2)
    oy_a = a.y + a.scale * 0.5
    wx = ox_a + ca * (u * tx) - sa * (u * ty)
    wy = oy_a + sa * (u * tx) + ca * (u * ty)            # onde cai, no mundo, a origem do plano de B (o centro da zona de B)
    return Layout(wx - s_b * (asp_b / 2), wy - s_b * 0.5, s_b, (a.rot + math.degrees(theta)) % 360.0)


# -- alinhar pelas IMAGENS do piso (funciona com a sala cheia: não depende de contar uma pessoa só) ---------------------------------
PX_PER_M = 100.0
MIN_INLIERS = 14
MAX_SCALE_ERR = 0.15


def _metric(tex_bgra: np.ndarray, aspect: float, k: float):
    """Textura da zona -> imagem em cinza com PX_PER_M pixels por metro (+ máscara do que a câmera vê) e o centro dela em px."""
    th, tw = tex_bgra.shape[:2]
    f = PX_PER_M / (tw / aspect * k)
    gray = cv2.cvtColor(np.ascontiguousarray(tex_bgra[..., :3]), cv2.COLOR_BGR2GRAY)
    mask = (tex_bgra[..., 3] > 0).astype(np.uint8) * 255
    size = (max(8, round(tw * f)), max(8, round(th * f)))
    gray = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
    mask = cv2.erode(cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST), np.ones((9, 9), np.uint8))   # tira a borda deformada
    return gray, mask, (size[0] / 2.0, size[1] / 2.0)


def fit_from_textures(tex_b: np.ndarray, asp_b: float, k_b: float, tex_a: np.ndarray, asp_a: float, k_a: float):
    """Giro e deslocamento (metros) que levam o plano de B ao de A, achados por pontos de interesse comuns (piso, tapete, rodapé...).
    Devolve (theta, tx, ty, erro_m). Levanta AlignError se as imagens não têm o que casar (chão liso, pouca sobreposição)."""
    ga, ma, ca = _metric(tex_a, asp_a, k_a)
    gb, mb, cb = _metric(tex_b, asp_b, k_b)
    orb = cv2.ORB_create(nfeatures=2500, fastThreshold=8)
    ka, da = orb.detectAndCompute(ga, ma)
    kb, db = orb.detectAndCompute(gb, mb)
    if da is None or db is None or len(ka) < MIN_INLIERS or len(kb) < MIN_INLIERS:
        raise AlignError("Não achei detalhes no chão das imagens para casar (piso muito liso ou ainda poucos quadros). "
                         "Espere o piso aparecer nas duas câmeras ou alinhe à mão.")
    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(db, da, k=2)
    good = [m[0] for m in matches if len(m) == 2 and m[0].distance < 0.8 * m[1].distance]
    if len(good) < MIN_INLIERS:
        raise AlignError("As duas câmeras quase não têm chão em comum nas imagens. Confira a calibração ou alinhe à mão.")
    src = np.float32([kb[m.queryIdx].pt for m in good])
    dst = np.float32([ka[m.trainIdx].pt for m in good])
    mat, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=6.0, maxIters=4000)
    if mat is None or int(inl.sum()) < MIN_INLIERS:
        raise AlignError("Não consegui casar o chão das duas câmeras (poucos pontos em comum). Alinhe à mão ou tente com menos gente parada.")
    s = float(math.hypot(mat[0, 0], mat[1, 0]))
    if abs(s - 1.0) > MAX_SCALE_ERR:
        raise AlignError("As escalas das duas calibrações não batem (largura/profundidade informadas). Refaça a calibração do chão.")
    theta = math.atan2(mat[1, 0], mat[0, 0])
    c, sn = math.cos(theta), math.sin(theta)
    # px_A = s·R·px_B + tp  ->  metros relativos ao centro de cada zona
    tx = ((s * (c * cb[0] - sn * cb[1]) + mat[0, 2]) - ca[0]) / PX_PER_M
    ty = ((s * (sn * cb[0] + c * cb[1]) + mat[1, 2]) - ca[1]) / PX_PER_M
    pts = src[inl.ravel() > 0]
    proj = (pts @ mat[:, :2].T + mat[:, 2])
    err = float(np.sqrt(np.mean(np.sum((proj - dst[inl.ravel() > 0]) ** 2, axis=1)))) / PX_PER_M
    return theta, tx, ty, err
