import math

import numpy as np

import pytest

from atendeio.app import map_model as M
from atendeio.app.room_align import AlignError, fit_rigid, layout_for


def rot(p, th, t=(0.0, 0.0)):
    c, s = math.cos(th), math.sin(th)
    return (c * p[0] - s * p[1] + t[0], s * p[0] + c * p[1] + t[1])


WALK = [(math.cos(i / 3) * 2.0, math.sin(i / 2) * 1.5) for i in range(20)]       # uma caminhada de ~4 m


def test_fit_recovers_a_known_rotation_and_shift():
    th, t = math.radians(35), (1.2, -0.7)
    theta, tx, ty, rms = fit_rigid([(p, rot(p, th, t)) for p in WALK])
    assert theta == pytest.approx(th) and (tx, ty) == pytest.approx(t) and rms < 1e-9


def test_fit_tolerates_noise_and_rejects_bad_data():
    th, t = math.radians(-80), (0.3, 2.0)
    noisy = [(p, (rot(p, th, t)[0] + 0.05 * (-1) ** i, rot(p, th, t)[1] - 0.05 * (-1) ** i)) for i, p in enumerate(WALK)]
    theta, *_ = fit_rigid(noisy)
    assert theta == pytest.approx(th, abs=0.05)
    with pytest.raises(AlignError):
        fit_rigid([(p, rot(p, th, t)) for p in WALK[:3]])                          # poucos pares
    with pytest.raises(AlignError):
        fit_rigid([((1.0, 1.0), (2.0, 2.0)) for _ in range(20)])                   # parado
    with pytest.raises(AlignError):
        fit_rigid([(p, (p[0] * 5 % 3, p[1] * 7 % 4)) for p in WALK])               # as câmeras não concordam


def test_aligned_layout_makes_the_two_floors_coincide_in_the_map():
    """Fim a fim: dois planos de câmeras diferentes, relação verdadeira conhecida; depois do layout, o mesmo ponto físico cai no mesmo lugar do mundo."""
    la, asp_a, k_a = M.Layout(1.0, 2.0, 1.3, 25.0), 16 / 9, 0.20
    asp_b, k_b = 4 / 3, 0.30
    th, t = math.radians(47), (0.8, -1.1)                       # pA = R pB + t (em metros)
    lb = layout_for(la, asp_a, k_a, asp_b, k_b, th, *t)
    assert lb.scale * k_b == pytest.approx(la.scale * k_a)       # os metros dos dois lados são iguais

    def world(lay, asp, k, p):                                   # ponto do plano (m, origem no centro da zona) -> mundo
        return lay.world(asp / 2 + p[0] * k, 0.5 + p[1] * k, asp)
    for pb in ((0.0, 0.0), (1.5, -0.4), (-2.0, 1.2), (0.7, 2.2)):
        pa = rot(pb, th, t)
        assert world(lb, asp_b, k_b, pb) == pytest.approx(world(la, asp_a, k_a, pa), abs=1e-9)


def test_layout_refuses_an_impossible_scale():
    with pytest.raises(AlignError):
        layout_for(M.Layout(0, 0, 3.0, 0), 1.7, 0.2, 1.3, 0.1, 0.0, 0.0, 0.0)


def _floor_world(seed=3, size=(1500, 1100)):
    """Um "chão" qualquer com bastante detalhe (ruído suavizado + formas), em coordenadas de metros × 100."""
    import cv2
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (size[1], size[0]), dtype=np.uint8)
    base = cv2.GaussianBlur(base, (0, 0), 2.5)
    base = cv2.normalize(base, None, 0, 255, cv2.NORM_MINMAX)
    for _ in range(60):
        cv2.circle(base, (int(rng.integers(0, size[0])), int(rng.integers(0, size[1]))), int(rng.integers(6, 30)), int(rng.integers(0, 255)), -1)
    return base


def _view(world, center, theta, w=700, h=400):
    """Textura BGRA (como a de uma câmera) de um recorte do chão centrado em `center` (px do mundo) e girado em `theta`."""
    import cv2
    c, s = math.cos(theta), math.sin(theta)
    # px_textura -> px_mundo: gira em torno do centro da textura e desloca para `center`
    m = np.array([[c, -s, center[0] - (c * w / 2 - s * h / 2)], [s, c, center[1] - (s * w / 2 + c * h / 2)]], np.float32)
    g = cv2.warpAffine(world, m, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    return np.dstack([g, g, g, np.full_like(g, 255)])


def test_image_alignment_recovers_the_relation_between_two_views_of_the_same_floor():
    from atendeio.app.room_align import fit_from_textures
    import numpy as np  # noqa
    world = _floor_world()
    asp, k = 700 / 400, 0.25                                   # 700 px / 1,75 · 0,25 = 100 px por metro nas duas
    ca, cb = (600.0, 500.0), (800.0, 560.0)                    # centros das duas câmeras no mundo (px)
    th = math.radians(20)
    a, b = _view(world, ca, 0.0), _view(world, cb, th)         # B vê o mesmo chão girado 20°
    theta, tx, ty, err = fit_from_textures(b, asp, k, a, asp, k)
    # verdade: o centro de B no plano de A, em metros
    true_t = ((cb[0] - ca[0]) / 100, (cb[1] - ca[1]) / 100)
    assert theta == pytest.approx(th, abs=math.radians(1.5)) and (tx, ty) == pytest.approx(true_t, abs=0.08) and err < 0.1


def test_image_alignment_works_with_people_standing_in_the_floor_and_refuses_a_blank_floor():
    import cv2
    from atendeio.app.room_align import fit_from_textures
    world = _floor_world(seed=5)
    asp, k = 700 / 400, 0.25
    a, b = _view(world, (600.0, 500.0), 0.0), _view(world, (760.0, 520.0), math.radians(-12))
    rng = np.random.default_rng(1)
    for tex in (a, b):                                          # sala cheia: dezenas de pessoas (manchas) em cada imagem, em lugares diferentes
        for _ in range(55):
            cv2.circle(tex, (int(rng.integers(0, 700)), int(rng.integers(0, 400))), 12, (30, 30, 200, 255), -1)
    theta, tx, ty, err = fit_from_textures(b, asp, k, a, asp, k)
    assert theta == pytest.approx(math.radians(-12), abs=math.radians(2.5)) and (tx, ty) == pytest.approx((1.6, 0.2), abs=0.15)
    blank = np.full((400, 700, 4), 120, np.uint8)
    with pytest.raises(AlignError):
        fit_from_textures(blank, asp, k, blank, asp, k)
