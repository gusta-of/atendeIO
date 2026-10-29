import math

import numpy as np
import pytest

from atendeio.analytics.camera_geometry import STAND_H, TABLE_H, CameraGeometry

ASPECT = 16 / 9


def make_camera(f, cam_pos, look_at, aspect=ASPECT):
    """Câmera pinhole "de verdade" (altura, inclinação e giro livres) para gerar imagens sintéticas. Mundo: X, Y no chão, Z para cima."""
    cam = np.array(cam_pos, float)
    z = np.array(look_at, float) - cam
    z /= np.linalg.norm(z)
    x = np.cross(z, [0, 0, 1.0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)                                         # y da imagem aponta para baixo
    rot = np.vstack([x, y, z])                                 # mundo -> câmera
    t = -rot @ cam

    def project(P):
        pc = rot @ np.array(P, float) + t
        return (f * pc[0] / pc[2] / aspect + 0.5, f * pc[1] / pc[2] + 0.5)
    return project, cam


def calibrate(project, rect_m):
    """Gera a calibração (4 cantos marcados no chão + medidas) e a homografia imagem->retângulo, como o app faz."""
    (x0, y0), (x1, y1) = rect_m
    corners_world = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]           # fundo-esq, fundo-dir, frente-dir, frente-esq
    img = [project((X, Y, 0.0)) for X, Y in corners_world]
    from atendeio.app.floor_calib import FloorCalib
    cal = FloorCalib(tuple(img), x1 - x0, y1 - y0)
    return cal, corners_world


def geometry_from(project, rect_m):
    """(geometria, calibração, mapa mundo->plano): o plano do app é definido pela IMAGEM (fundo à esquerda = origem, X à direita, Y para a frente),
    então o mundo de teste pode estar espelhado/girado em relação a ele; o mapa afim mundo->plano sai dos 4 cantos."""
    cal, corners_world = calibrate(project, rect_m)
    g = CameraGeometry.from_calibration(cal._h(), cal.width, cal.depth, ASPECT)
    img = [project((X, Y, 0.0)) for X, Y in corners_world]
    plan_of = {0: None}
    pairs = []
    for (wx, wy), pt in zip(corners_world, img):
        k = min(range(4), key=lambda i: (cal.pts[i][0] - pt[0]) ** 2 + (cal.pts[i][1] - pt[1]) ** 2)       # qual canto canônico é este
        pairs.append(((wx, wy), [(0, 0), (cal.width, 0), (cal.width, cal.depth), (0, cal.depth)][k]))
    a = np.array([[wx, wy, 1.0] for (wx, wy), _ in pairs])
    bx = np.array([p[0] for _, p in pairs])
    by = np.array([p[1] for _, p in pairs])
    cx, *_ = np.linalg.lstsq(a, bx, rcond=None)
    cy, *_ = np.linalg.lstsq(a, by, rcond=None)
    to_plan = lambda pt: (float(cx @ [pt[0], pt[1], 1.0]), float(cy @ [pt[0], pt[1], 1.0]))
    return g, cal, to_plan


# três câmeras bem diferentes olhando a mesma sala (5 × 4 m): alta e inclinada, baixa e de frente, quase de cima
POSES = [
    ("alta e inclinada", 1.1, (2.5, 9.0, 2.6), (2.5, 2.0, 0.0)),
    ("baixa, de frente", 0.9, (2.5, 8.0, 1.4), (2.5, 2.0, 0.6)),
    ("quase de cima",    1.0, (2.0, 3.0, 4.5), (2.5, 2.2, 0.0)),
]
RECT = ((0.0, 0.0), (5.0, 4.0))


@pytest.mark.parametrize("name,f,pos,look", POSES)
def test_recovers_focal_length_and_camera_height_from_the_floor_calibration(name, f, pos, look):
    project, cam = make_camera(f, pos, look)
    g, _cal, _tp = geometry_from(project, RECT)
    assert g.valid, name
    assert g.f == pytest.approx(f, rel=0.03), name
    assert g.height_m == pytest.approx(pos[2], rel=0.04), name


@pytest.mark.parametrize("name,f,pos,look", POSES)
def test_table_footprint_and_person_floor_position_are_metric_for_any_camera_pose(name, f, pos, look):
    project, _ = make_camera(f, pos, look)
    g, _, to_plan = geometry_from(project, RECT)
    # uma mesa 1,2 × 0,8 m, tampo a 0,75 m, com o canto em (3.0, 1.0)
    table = [(3.0, 1.0), (4.2, 1.0), (4.2, 1.8), (3.0, 1.8)]
    top_img = [project((X, Y, TABLE_H)) for X, Y in table]
    foot = g.table_footprint(top_img)
    assert foot is not None
    for got, want in zip(foot, table):
        assert got == pytest.approx(to_plan(want), abs=0.12), name         # pegada recuperada a ~10 cm em qualquer câmera
    # pessoa em pé em (2.0, 3.0): caixa do pé à cabeça (1,7 m)
    px, py = 2.0, 3.0
    fx, fy = project((px, py, 0.0))
    hx, hy = project((px, py, STAND_H))
    box = (fx - 0.04, hy, fx + 0.04, fy)
    assert g.person_floor(box) == pytest.approx(to_plan((px, py)), abs=0.15), name
    # sentada com os PÉS À VISTA (caixa do chão até a cabeça a 1,3 m): vale o ponto dos pés, bem mais exato que em pé/oculta
    ex, ey = project((px, py, 0.0))
    ehx, ehy = project((px, py, 1.30))
    seated_feet = (ex - 0.04, ehy, ex + 0.04, ey)
    got = g.person_floor(seated_feet)
    assert got is not None and math.dist(got, to_plan((px, py))) < 0.3, name
    # a mesma pessoa SENTADA (caixa só do assento para cima): posicionada pela cabeça, ainda a < 0,5 m
    sx, sy = project((px, py, 0.45))
    shx, shy = project((px, py, 1.30))
    seated = (sx - 0.04, shy, sx + 0.04, sy)
    got = g.person_floor(seated)
    assert got is not None and math.dist(got, to_plan((px, py))) < 0.45, name


@pytest.mark.parametrize("name,f,pos,look", POSES)
def test_person_passing_in_front_of_the_camera_is_far_from_the_table_in_metres(name, f, pos, look):
    project, cam = make_camera(f, pos, look)
    g, _, _tp = geometry_from(project, RECT)
    table = [(0.5, 0.5), (1.5, 0.5), (1.5, 1.2), (0.5, 1.2)]
    foot = g.table_footprint([project((X, Y, TABLE_H)) for X, Y in table])
    from atendeio.analytics.geometry import point_polygon_distance
    # alguém a ~1 m da câmera, diretamente "na frente" da mesa na imagem, mas a vários metros dela no chão
    px = min(max(cam[0], 0.3), 4.7)
    near_cam = (px, min(cam[1], 3.9) if cam[1] < 4 else 3.7)
    fx, fy = project((near_cam[0], near_cam[1], 0.0))
    hx, hy = project((near_cam[0], near_cam[1], STAND_H))
    pos_m = g.person_floor((fx - 0.05, min(hy, fy), fx + 0.05, max(hy, fy)))
    if pos_m is not None:
        assert point_polygon_distance(pos_m[0], pos_m[1], foot) > 1.5, name
    # e alguém encostado na mesa: a 0,3 m da borda
    side = (1.5 + 0.3, 0.85)
    sfx, sfy = project((side[0], side[1], 0.0))
    shx, shy = project((side[0], side[1], STAND_H))
    near = g.person_floor((sfx - 0.04, shy, sfx + 0.04, sfy))
    assert point_polygon_distance(near[0], near[1], foot) < 0.5, name


def test_a_noisy_calibration_with_an_implausible_focal_length_falls_back_to_the_typical_one_instead_of_inventing_a_telephoto():
    """Calibrar com 4 pontos à mão dá focais absurdas (caso real: 2,4 ≈ 40° de campo). Fora do intervalo plausível vale a típica."""
    from atendeio.analytics.camera_geometry import F_RANGE
    project, _ = make_camera(*POSES[0][1:])
    # estraga os pontos: desloca 4% da imagem em direções diferentes
    cal, _c = calibrate(project, RECT)
    pts = [(x + dx, y + dy) for (x, y), (dx, dy) in zip(cal.pts, ((0.05, -0.04), (-0.04, 0.05), (0.06, 0.03), (-0.05, -0.06)))]
    from atendeio.app.floor_calib import FloorCalib
    noisy = FloorCalib(tuple(pts), 5.0, 4.0)
    g = CameraGeometry.from_calibration(noisy._h(), 5.0, 4.0, ASPECT)
    assert g.valid and F_RANGE[0] <= g.f <= F_RANGE[1]


def test_an_impossible_calibration_is_marked_invalid_instead_of_inventing_geometry():
    g = CameraGeometry.from_calibration(np.zeros((3, 3)), 4.0, 3.0, ASPECT)             # homografia degenerada
    assert not g.valid


# ---- a decisão de mesa ocupada, em metros, para câmeras em posições diferentes -------------------------------------------------
from atendeio.analytics.zones import AnalyticsConfig, Zone, ZoneAnalyzer          # noqa: E402

CFG = AnalyticsConfig(occupy_after_s=0, free_after_s=0, item_hold_s=3, clean_after_s=20, people_window=1)
TABLE = [(3.0, 1.0), (4.2, 1.0), (4.2, 1.8), (3.0, 1.8)]                          # a mesa no chão do mundo de teste (tampo a 0,75 m)


def person_box(project, X, Y, seated=False):
    """Caixa (imagem normalizada) de uma pessoa de ~0,5 m de largura em (X, Y)."""
    pts = [project((X + dx, Y + dy, z)) for dx in (-0.25, 0.25) for dy in (-0.25, 0.25) for z in ((0.45, 1.15, 1.3) if seated else (0.0, 1.0, 1.7))]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (max(min(xs), 0.0), max(min(ys), 0.0), min(max(xs), 1.0), min(max(ys), 1.0))


def analyzer_for(project):
    g, cal, _tp = geometry_from(project, RECT)
    az = ZoneAnalyzer(CFG, [Zone(1, "Mesa", "mesa", tuple(project((X, Y, TABLE_H))[:2] for X, Y in TABLE), margin=0.06)])
    az.set_geometry(lambda aspect: CameraGeometry.from_calibration(cal._h(), cal.width, cal.depth, aspect))
    return az


def people_at(az, box):
    return az.update([(1, box)], [], 0.0, ASPECT)["areas"][0]["people"]


@pytest.mark.parametrize("name,f,pos,look", POSES)
def test_table_is_occupied_only_by_people_really_at_it_for_any_camera_position(name, f, pos, look):
    project, cam = make_camera(f, pos, look)
    # encostada na mesa (0,35 m da borda), em pé e sentada à mesa: contam
    assert people_at(analyzer_for(project), person_box(project, 4.2 + 0.35, 1.4)) == 1, name
    assert people_at(analyzer_for(project), person_box(project, 3.6, 1.8 + 0.4, seated=True)) == 1, name
    # a 1,4 m da borda (fora da sombra de assentos de 0,6 m): não conta
    assert people_at(analyzer_for(project), person_box(project, 4.2 + 1.4, 1.4)) == 0, name
    # alguém perto da CÂMERA, na linha de visão da mesa (cobre o polígono na imagem), a metros dela no chão: não conta
    top_center = np.array([3.6, 1.4, TABLE_H])
    lam = (cam[2] - 1.4) / (cam[2] - TABLE_H) if cam[2] > 1.5 else 0.25      # ponto da linha de visão em que uma pessoa a bloquearia
    ground = np.array(cam) + lam * (top_center - np.array(cam))
    if math.dist(ground[:2], top_center[:2]) < 1.6:
        return        # câmera quase de cima: quem "cobriria" a mesa na imagem está, de fato, junto dela: não existe esse falso positivo
    box = person_box(project, ground[0], ground[1])
    tbl = [project((X, Y, TABLE_H)) for X, Y in TABLE]
    overlap = not (box[2] < min(p[0] for p in tbl) or box[0] > max(p[0] for p in tbl) or box[3] < min(p[1] for p in tbl) or box[1] > max(p[1] for p in tbl))
    assert overlap, f"{name}: o cenário precisa cobrir a mesa na imagem"
    assert people_at(analyzer_for(project), box) == 0, name


def test_without_a_calibrated_floor_the_image_rule_is_used_and_geometry_is_per_camera():
    project, _ = make_camera(*POSES[0][1:])
    az = ZoneAnalyzer(CFG, [Zone(1, "Mesa", "mesa", tuple(project((X, Y, TABLE_H))[:2] for X, Y in TABLE))])
    assert az._geom is None                                                       # sem calibração: sem geometria
    box = person_box(project, 3.6, 2.2)
    assert az.update([(1, box)], [], 0.0, ASPECT)["areas"][0]["people"] in (0, 1)  # só garante que a regra antiga continua rodando sem erro
