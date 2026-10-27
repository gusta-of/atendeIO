"""Áreas pintadas no vídeo: o que está na frente esconde o contorno."""

import time

import numpy as np

from atendeio.analytics.zones import Zone
from atendeio.vision.areas_draw import BLIND_BGR, STATUS_BGR, draw_areas

W, H = 320, 240
BG = (90, 85, 80)


def frame():
    return np.full((H, W, 3), BG, np.uint8)


def door():
    # retângulo x 100..200, y 60..180 (em pixels)
    return Zone(1, "Porta", "entrada", ((100 / W, 60 / H), (200 / W, 60 / H), (200 / W, 180 / H), (100 / W, 180 / H)))


def same(px, color, tol=6):
    return all(abs(int(a) - int(b)) <= tol for a, b in zip(px, color))


def person_poly(x0, y0, x1, y1):
    return [(x0 / W, y0 / H), (x1 / W, y0 / H), (x1 / W, y1 / H), (x0 / W, y1 / H)]


def test_outline_and_fill_are_painted_without_occluders():
    f = frame()
    draw_areas(f, [door()], {})
    assert not same(f[120, 100], BG)                    # contorno (borda esquerda)
    assert not same(f[120, 150], BG)                    # preenchimento (interior)
    assert same(f[20, 20], BG) and same(f[220, 300], BG)  # fora da área: intacto


def test_person_in_front_hides_outline_and_fill():
    plain = frame()
    draw_areas(plain, [door()], {})
    f = frame()
    # uma "pessoa" larga cobrindo a borda esquerda da porta e parte do interior
    draw_areas(f, [door()], {}, occluders=[person_poly(80, 40, 140, 200)])
    assert same(f[120, 100], BG, tol=2)                 # onde havia contorno: agora vídeo original
    assert same(f[120, 120], BG, tol=2)                 # interior atrás do corpo: sem preenchimento
    assert not same(f[120, 190], BG)                    # fora do corpo: a área continua pintada
    assert not np.array_equal(plain[120, 100], f[120, 100])


def test_edge_does_not_leak_through_the_silhouette_border():
    f = frame()
    draw_areas(f, [door()], {}, occluders=[person_poly(90, 40, 150, 200)])
    # 1-2 px DENTRO da silhueta (x=91..92) o contorno em x=100 não pode aparecer, e a borda é suave
    assert same(f[120, 100], BG, tol=2)
    row = f[120, 85:160].astype(int)
    assert np.abs(np.diff(row, axis=0)).max() < 120     # sem degrau seco de cor na transição


def test_mesa_color_follows_status_and_blind_is_gray():
    z = Zone(5, "Mesa 1", "mesa", ((0.2, 0.2), (0.6, 0.2), (0.6, 0.6), (0.2, 0.6)))
    for status in ("livre", "ocupada", "a_limpar"):
        f = frame()
        draw_areas(f, [z], {5: status})
        edge = f[int(0.2 * H), 150]                     # sobre a borda de cima
        assert same(edge, STATUS_BGR[status], tol=30), status
    f = frame()
    draw_areas(f, [z], {5: "livre"}, blind=True)        # sem leitura: nunca finge "livre"
    assert same(f[int(0.2 * H), 150], BLIND_BGR, tol=30)


def test_no_zones_or_off_frame_zone_is_a_noop():
    f = frame()
    ref = f.copy()
    draw_areas(f, [], {})
    assert np.array_equal(f, ref)
    outside = Zone(2, "Fora", "area", ((1.2, 1.2), (1.5, 1.2), (1.5, 1.5)))
    draw_areas(f, [outside], {})
    assert np.array_equal(f, ref)


def test_many_zones_are_cheap():  # inclui a sombra de assentos de cada mesa
    zones = [Zone(i, f"M{i}", "mesa", ((0.02 + (i % 10) * 0.09, 0.1 + (i // 10) * 0.4),
                                       (0.09 + (i % 10) * 0.09, 0.1 + (i // 10) * 0.4),
                                       (0.09 + (i % 10) * 0.09, 0.45 + (i // 10) * 0.4),
                                       (0.02 + (i % 10) * 0.09, 0.45 + (i // 10) * 0.4)), 0.05) for i in range(20)]
    big = np.full((480, 640, 3), BG, np.uint8)
    polys = [person_poly(100, 50, 220, 230)]
    t0 = time.perf_counter()
    for _ in range(10):
        draw_areas(big, zones, {z.id: "livre" for z in zones}, occluders=polys)
    per_frame_ms = (time.perf_counter() - t0) / 10 * 1000
    assert per_frame_ms < 40, f"{per_frame_ms:.1f} ms por quadro"


# ── sombra de assentos desenhada no vídeo ─────────────────────────────────────────────────────────
def desk(margin=0.12):
    return Zone(7, "Mesa 1", "mesa", ((0.5, 0.5), (0.8, 0.5), (0.8, 0.8), (0.5, 0.8)), margin)


def test_seat_shadow_fades_away_from_the_table_edge():
    f = frame()
    draw_areas(f, [desk()], {7: "livre"})
    left_edge = int(0.5 * W)                           # x da borda esquerda da mesa
    y = int(0.65 * H)
    near = np.abs(f[y, left_edge - 4].astype(int) - BG).sum()
    mid = np.abs(f[y, left_edge - 14].astype(int) - BG).sum()
    far = np.abs(f[y, left_edge - 60].astype(int) - BG).sum()   # além da margem (~29 px): intacto
    assert near > mid > far
    assert far == 0


def test_no_margin_means_no_shadow():
    f = frame()
    draw_areas(f, [desk(0.0)], {7: "livre"})
    y, x = int(0.65 * H), int(0.5 * W) - 6
    assert same(f[y, x], BG, tol=1)


def test_person_in_front_hides_the_shadow_too():
    f = frame()
    # pessoa sentada à esquerda da mesa, em cima da sombra
    draw_areas(f, [desk()], {7: "livre"}, occluders=[person_poly(100, 90, 150, 210)])
    assert same(f[int(0.65 * H), 145], BG, tol=2)                # x=145 está dentro do corpo (100..150): sombra escondida
    assert not same(f[int(0.65 * H), 156], BG, tol=2)            # x=156 está fora do corpo: a sombra continua ali
    g = frame()
    draw_areas(g, [desk()], {7: "livre"})
    assert not same(g[int(0.65 * H), 145], BG, tol=2)            # sem a pessoa, a sombra aparece nesse mesmo pixel
