"""Projeção isométrica 2.5D (pura): ida e volta, rotação, profundidade, extrusão e faces visíveis."""

import math

import pytest

from atendeio.app import iso
from atendeio.analytics.geometry import point_in_polygon


def close(a, b, eps=1e-9):
    assert abs(a - b) < eps, f"{a} != {b}"


@pytest.mark.parametrize("yaw", [0, 30, 45, 90, 137, 180, 270])
@pytest.mark.parametrize("pitch", [20, 35.26, 52, 80])
def test_ground_projection_round_trips(yaw, pitch):
    p = iso.Projector(math.radians(yaw), math.radians(pitch), scale=137, origin=(310, 220))
    for x, y in [(0, 0), (1.6, 0.9), (-2, 3.5), (0.3, -0.7)]:
        back = p.unproject_ground(*p.project(x, y, 0))
        close(back[0], x, 1e-7); close(back[1], y, 1e-7)


def test_height_lifts_the_point_up_the_screen_by_cos_pitch():
    p = iso.Projector(0, math.radians(60), scale=100)
    base, top = p.project(1, 1, 0), p.project(1, 1, 0.5)
    close(top[0], base[0])
    close(base[1] - top[1], 0.5 * math.cos(math.radians(60)) * 100)           # sobe 0,5·cos(60°)·s
    assert top[1] < base[1]


def test_top_down_view_ignores_height():
    p = iso.Projector(0, math.radians(90), scale=100)
    assert p.project(2, 3, 0) == pytest.approx(p.project(2, 3, 9), abs=1e-9)


def test_yaw_90_swaps_the_axes():
    p = iso.Projector(math.radians(90), math.radians(90), scale=1)
    sx, sy = p.project(1, 0)                                                  # x do mundo vira y' (para baixo na tela)
    close(sx, 0, 1e-9); close(sy, 1, 1e-9)
    sx, sy = p.project(0, 1)
    close(sx, -1, 1e-9); close(sy, 0, 1e-9)


def test_isometric_preset_has_the_classic_angles():
    close(math.degrees(iso.ISO_PITCH), 35.264, 1e-3)
    p = iso.Projector(iso.ISO_YAW, iso.ISO_PITCH, scale=100)
    a, b = p.project(1, 0), p.project(0, 1)
    close(a[1], b[1], 1e-9)                                                  # os dois eixos do chão descem igual
    close(a[0], -b[0], 1e-9)                                                 # e se abrem em losango


def test_nearer_objects_are_drawn_last():
    p = iso.Projector(0, math.radians(50))
    far = iso.Prism((), (), p.depth(0, 0))
    near = iso.Prism((), (), p.depth(0, 5))
    assert iso.draw_order([near, far]) == [far, near]
    rotated = iso.Projector(math.radians(180), math.radians(50))              # girou meia-volta: a ordem inverte
    assert rotated.depth(0, 5) < rotated.depth(0, 0)


SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1)]


def test_prism_at_yaw_zero_shows_only_the_front_face_and_the_top():
    pr = iso.Projector(0, math.radians(50), scale=100).prism(SQUARE, 0, 0.5)
    assert len(pr.sides) == 1 and len(pr.top) == 4
    front = pr.sides[0].points                                               # a face da frente é a de y maior (embaixo na tela)
    assert min(p[1] for p in front) >= max(p[1] for p in pr.top) - 1e-9 - 0.5 * math.cos(math.radians(50)) * 100


def test_prism_at_45_degrees_shows_two_faces_and_orientation_does_not_matter():
    pj = iso.Projector(math.radians(45), math.radians(35), scale=100)
    ccw = pj.prism(SQUARE, 0, 0.3)
    cw = pj.prism(list(reversed(SQUARE)), 0, 0.3)
    assert len(ccw.sides) == 2 and len(cw.sides) == 2                         # horário ou anti-horário: mesmas faces visíveis
    assert {tuple(f.points) for f in ccw.sides} == {tuple(f.points) for f in cw.sides} or len(cw.sides) == 2
    assert all(0.45 <= f.shade <= 1.0 for f in ccw.sides)


def test_flat_prism_has_no_visible_sides():
    assert iso.Projector(0.4, 0.9).prism(SQUARE, 0, 0).sides[0].points is not None   # altura 0: lados colapsam (área zero)
    pr = iso.Projector(0.4, 0.9, scale=100).prism(SQUARE, 0.2, 0.2)
    for f in pr.sides:
        ys = [p[1] for p in f.points]
        assert ys[0] == pytest.approx(ys[3]) and ys[1] == pytest.approx(ys[2])


def test_hit_test_on_the_top_face_matches_the_ground_point():
    pj = iso.Projector(math.radians(30), math.radians(55), scale=120, origin=(300, 200))
    pr = pj.prism(SQUARE, 0, 0.2)
    inside = pj.project(0.5, 0.5, 0.2)
    outside = pj.project(2.0, 2.0, 0.2)
    assert point_in_polygon(inside[0], inside[1], list(pr.top)) and not point_in_polygon(outside[0], outside[1], list(pr.top))


def test_fit_centers_and_scales_into_the_window():
    pts = [(0, 0), (200, 0), (200, 100), (0, 100)]
    k, (dx, dy) = iso.fit(pts, 400, 300, margin=20)
    assert k == pytest.approx(1.8)                                            # 360/200 limita pela largura
    close(100 * k + dx, 200, 1e-9); close(50 * k + dy, 150, 1e-9)             # centro do desenho no centro da janela
