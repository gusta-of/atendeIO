"""Matemática das formas (porta de web/src/app/shared/shapes.spec.ts, mesmos casos)."""

import math

import pytest

from atendeio.app import shapes as S

W, H = 640, 480


def close(a, b, eps=1e-6):
    assert abs(a - b) < eps, f"{a} != {b}"


def area(p):
    return abs(sum(x * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * y for i, (x, y) in enumerate(p))) / 2


@pytest.mark.parametrize("deg", [0, 30, 90, -45, 137])
def test_rect_points_obb_round_trip(deg):
    obb = S.Obb(300, 200, 120, 60, S.deg2rad(deg))
    back = S.obb_from_points(S.points_from_obb("rect", obb, W, H), deg, W, H)
    close(back.cx, 300); close(back.cy, 200); close(back.w, 120); close(back.h, 60)


@pytest.mark.parametrize("shape", ["ellipse", "triangle"])
def test_ellipse_and_triangle_recover_center_and_size(shape):
    obb = S.Obb(320, 240, 100, 80, S.deg2rad(25))
    back = S.obb_from_points(S.points_from_obb(shape, obb, W, H), 25, W, H)
    close(back.cx, 320, 1e-3); close(back.cy, 240, 1e-3); close(back.w, 100, 1e-3); close(back.h, 80, 1e-3)


def test_rotating_90_swaps_width_and_height_and_keeps_area():
    a = S.outline("rect", S.Obb(300, 200, 120, 40, 0))
    b = S.outline("rect", S.Obb(300, 200, 120, 40, math.pi / 2))
    close(area(a), area(b))
    bb = S.bbox(b)
    close(bb.x1 - bb.x0, 40); close(bb.y1 - bb.y0, 120)


def test_triangle_points_up():
    apex, br, bl = S.outline("triangle", S.Obb(100, 100, 60, 40, 0))
    assert [round(v) for v in apex] == [100, 80]
    assert [round(v) for v in br] == [130, 120]
    assert [round(v) for v in bl] == [70, 120]


def test_circle_has_32_points_all_at_the_same_distance():
    pts = S.outline("ellipse", S.Obb(200, 200, 100, 100, 0.7))
    assert len(pts) == 32
    for x, y in pts:
        close(math.hypot(x - 200, y - 200), 50)


def test_corner_resize_keeps_the_opposite_corner_even_rotated():
    obb = S.Obb(300, 200, 100, 60, S.deg2rad(40))
    before = S.corners(obb)
    tx, ty = S.rot(80, 50, obb.angle)
    nxt = S.resize_from_corner(obb, 2, (obb.cx + tx, obb.cy + ty))
    after = S.corners(nxt)
    close(after[0][0], before[0][0]); close(after[0][1], before[0][1])
    close(nxt.w, 130); close(nxt.h, 80); close(nxt.angle, obb.angle)


def test_rotate_handle_sits_above_the_top_and_angle_toward_returns_to_it():
    obb = S.Obb(300, 200, 100, 60, 0)
    hnd = S.rotate_handle(obb, 28)
    close(hnd[0], 300); close(hnd[1], 200 - 30 - 28)
    close(S.angle_toward((300, 200), hnd), 0)
    turned = S.Obb(300, 200, 100, 60, S.deg2rad(60))
    close(S.angle_toward((300, 200), S.rotate_handle(turned)), S.deg2rad(60), 1e-9)


def test_rotate_points_keeps_distances_to_the_pivot():
    pts = [(10, 10), (50, 10), (30, 40)]
    out = S.rotate_points(pts, (30, 20), S.deg2rad(77))
    for p, q in zip(pts, out):
        close(math.hypot(p[0] - 30, p[1] - 20), math.hypot(q[0] - 30, q[1] - 20), 1e-9)


def test_fit_inside_pushes_back_and_refuses_what_does_not_fit():
    pts, dx, dy = S.fit_inside([(-10, 20), (50, 20), (50, 80)], W, H)
    assert dx == 10 and all(x >= 0 for x, _ in pts)
    assert S.fit_inside([(0, 0), (W + 50, 0), (0, 10)], W, H) is None


def test_wrap_deg():
    assert S.wrap_deg(190) == -170 and S.wrap_deg(-190) == 170 and S.wrap_deg(180) == -180 and S.wrap_deg(45) == 45


def test_edge_handle_changes_only_width_or_only_height_even_rotated():
    obb = S.Obb(300, 200, 100, 60, S.deg2rad(30))
    ox, oy = S.rot(50 + 40, 0, obb.angle)
    r = S.resize_from_edge(obb, 1, (obb.cx + ox, obb.cy + oy))
    close(r.w, 140); close(r.h, 60)
    left0, left1 = S.edge_midpoints(obb)[3], S.edge_midpoints(r)[3]
    close(left1[0], left0[0]); close(left1[1], left0[1])
    ux, uy = S.rot(0, -30 - 20, obb.angle)
    t = S.resize_from_edge(obb, 0, (obb.cx + ux, obb.cy + uy))
    close(t.w, 100); close(t.h, 80)


def test_keep_ratio_preserves_proportion_when_dragging_a_corner():
    sq = S.Obb(200, 200, 80, 80, 0)
    r = S.resize_from_corner(sq, 2, (320, 280), True)
    close(r.w, r.h, 1e-9); close(r.w, 160, 1e-9)
    tl = S.corners(r)[0]
    close(tl[0], 160); close(tl[1], 160)
    free = S.resize_from_corner(sq, 2, (320, 280), False)
    close(free.w, 160); close(free.h, 120)


def test_with_size_keeps_center_and_angle():
    o = S.with_size(S.Obb(50, 60, 10, 20, 1), 30, 40)
    assert (o.cx, o.cy, o.w, o.h, o.angle) == (50, 60, 30, 40, 1)


def test_square_has_equal_sides_and_rect_icon_is_wider_than_tall():
    sq = S.outline("square", S.Obb(100, 100, 60, 60, 0))
    close(math.hypot(sq[1][0] - sq[0][0], sq[1][1] - sq[0][1]), math.hypot(sq[2][0] - sq[1][0], sq[2][1] - sq[1][1]))
    b, q = S.bbox(S.catalog("rect")), S.bbox(S.catalog("square"))
    assert (b.x1 - b.x0) > (b.y1 - b.y0) * 1.3
    close(q.x1 - q.x0, q.y1 - q.y0, 1e-9)


def test_thumb_points_fit_the_icon_keeping_the_image_aspect():
    pts = S.thumb_points(S.catalog("square"), 16 / 9, 34, 24)
    assert min(x for x, _ in pts) >= 0 and max(x for x, _ in pts) <= 34
    assert min(y for _, y in pts) >= 0 and max(y for _, y in pts) <= 24
