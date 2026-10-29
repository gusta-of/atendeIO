import numpy as np
import pytest

from atendeio.app.floor_calib import FloorCalib
from atendeio.app.floor_texture import FloorMedian, tex_size, warp_floor

ASPECT = 16 / 9
CAL = FloorCalib(((0.30, 0.40), (0.70, 0.40), (0.90, 0.90), (0.10, 0.90)), 4.0, 3.0)


def frame(color=(40, 120, 200), w=320, h=180):
    f = np.zeros((h, w, 3), np.uint8)
    f[:] = color
    return f


def test_the_texture_has_the_zone_proportion_and_keeps_the_colors_of_the_floor_it_sees():
    tex = warp_floor(frame(), CAL, ASPECT, width=320)
    assert tex.shape == (180, 320, 4) and tex_size(ASPECT, 320) == (320, 180)
    h, w = tex.shape[:2]
    cx, cy = w // 2, h // 2                                          # o centro do chão calibrado aparece, com a cor da imagem
    assert tex[cy, cx, 3] == 255 and tuple(tex[cy, cx, :3]) == (40, 120, 200)


def test_perspective_is_undone_a_checker_floor_becomes_square_cells():
    """Tabuleiro com células iguais NO CHÃO, visto em perspectiva, volta a ter células de mesmo tamanho (vista de cima)."""
    cal = FloorCalib(((0.30, 0.40), (0.70, 0.40), (0.90, 0.90), (0.10, 0.90)), 2.0, 2.0)
    import cv2
    h, w = 360, 640
    # desenha na imagem a grade 4x4 do chão (cantos conhecidos): cada célula é um quadrilátero em perspectiva
    img = np.zeros((h, w, 3), np.uint8)
    inv = np.linalg.inv(cal._h())
    for i in range(4):
        for j in range(4):
            if (i + j) % 2:
                continue
            cell = [(i / 4, j / 4), ((i + 1) / 4, j / 4), ((i + 1) / 4, (j + 1) / 4), (i / 4, (j + 1) / 4)]
            pts = []
            for u, v in cell:
                p = inv @ np.array([u, v, 1.0])
                pts.append((p[0] / p[2] * w, p[1] / p[2] * h))
            cv2.fillPoly(img, [np.array(pts, np.int32)], (255, 255, 255))
    tex = warp_floor(img, cal, ASPECT, width=640)
    th, tw = tex.shape[:2]
    # o chão (2 m x 2 m) ocupa 70% da menor dimensão da zona: um quadrado centrado
    side = int(0.7 * min(tw / ASPECT * 1.0, th) * 1.0)
    x0, y0 = tw // 2 - side // 2, th // 2 - side // 2
    cell = side // 4
    white = lambda i, j: tex[y0 + j * cell + cell // 2, x0 + i * cell + cell // 2, 0] > 128
    for i in range(4):
        for j in range(4):
            assert white(i, j) == ((i + j) % 2 == 0), (i, j)


def test_median_erases_a_person_who_walked_through_and_keeps_the_floor():
    med = FloorMedian()
    for i in range(5):
        f = frame((50, 50, 50))
        if i == 2:
            f[60:120, 100:140] = (255, 255, 255)                     # alguém passou num só quadro
        med.add(warp_floor(f, CAL, ASPECT, width=320))
    out = med.image()
    assert med.samples == 5 and out.shape == (180, 320, 4)
    ys, xs = np.where(out[..., 3] > 0)
    assert (out[ys, xs, :3] <= 60).all()                              # a pessoa (255) sumiu; só sobrou o piso (bordas interpoladas ficam abaixo de 50)


def test_median_with_few_samples_and_size_change():
    med = FloorMedian()
    assert med.image() is None
    t = warp_floor(frame(), CAL, ASPECT, width=320)
    med.add(t)
    assert med.image() is not None and med.samples == 1
    med.add(warp_floor(frame(), CAL, 4 / 3, width=320))               # proporção diferente: recomeça
    assert med.samples == 1
