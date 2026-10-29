import pytest

from atendeio.app.floor_calib import FloorCalib

# retângulo do chão visto em perspectiva: o fundo é mais estreito que a frente
PTS = ((0.35, 0.40), (0.65, 0.40), (0.90, 0.90), (0.10, 0.90))
ASPECT = 16 / 9


def test_the_four_clicked_corners_land_on_the_corners_of_the_plan():
    c = FloorCalib(PTS, 4.0, 3.0)
    k = 0.7 * min(ASPECT / 4.0, 1 / 3.0)
    x0, x1 = ASPECT / 2 - 2.0 * k, ASPECT / 2 + 2.0 * k
    y0, y1 = 0.5 - 1.5 * k, 0.5 + 1.5 * k
    got = [c.to_local(x, y, ASPECT) for x, y in PTS]
    want = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for g, w in zip(got, want):
        assert g == pytest.approx(w, abs=1e-9)


def test_perspective_is_undone_the_far_half_is_not_squeezed():
    """A metade da imagem (y=0,65) NÃO é a metade do chão: o fundo é comprimido, então a metade real fica mais perto do fundo."""
    c = FloorCalib(PTS, 4.0, 3.0)
    assert c.to_local(0.5, 0.65, ASPECT)[1] > 0.5 + 0.02   # linear diria 0,5; passou do meio do chão
    far, near = c.to_local(0.5, 0.40, ASPECT)[1], c.to_local(0.5, 0.90, ASPECT)[1]
    assert far < c.to_local(0.5, 0.60, ASPECT)[1] < near


def test_points_near_the_horizon_are_clamped_not_exploded():
    c = FloorCalib(PTS, 4.0, 3.0)
    x, y = c.to_local(0.5, 0.0, ASPECT) or (0, 0)
    assert -1.5 <= y <= 2.5 and abs(x) < 10


@pytest.mark.parametrize("pts,w,d", [
    (PTS[:3], 4, 3),                                                           # faltam pontos
    (((0.1, 0.5), (0.4, 0.5), (0.6, 0.5), (0.9, 0.5)), 4, 3),                  # colineares
    (((0.1, 0.1), (2.2, 0.1), (0.9, 0.9), (0.1, 0.9)), 4, 3),                  # longe demais da imagem
    (PTS, 0, 3),                                                               # tamanho inválido
])
def test_bad_calibrations_are_rejected(pts, w, d):
    with pytest.raises(ValueError):
        FloorCalib(pts, w, d)


def test_round_trip_dict():
    c = FloorCalib(PTS, 4.0, 3.0)
    assert FloorCalib.from_dict(c.to_dict()) == c


def test_scene_uses_the_calibration_for_people_and_areas_and_falls_back_without_it():
    from atendeio.app import map_model as M
    cam = {"id": 1, "name": "A"}
    zone = {"id": 1, "name": "M", "kind": "mesa", "points": [(0.45, 0.5), (0.55, 0.5), (0.55, 0.6), (0.45, 0.6)]}
    st = {"size": [1600, 900], "online": True, "areas": [], "people": 1, "tracks": [{"id": 1, "x": 0.5, "y": 0.65}]}
    lin = M.build_scene([cam], {1: [zone]}, {1: st}, {})
    cal = M.build_scene([cam], {1: [zone]}, {1: st}, {}, calibs={1: FloorCalib(PTS, 4.0, 3.0)})
    assert lin.sections[0].people[0][2] != pytest.approx(cal.sections[0].people[0][2], abs=1e-3)   # a perspectiva moveu a pessoa
    assert lin.sections[0].blocks[0].footprint != cal.sections[0].blocks[0].footprint             # e as áreas junto
    # sem calibração = o mesmo resultado de antes
    assert M.build_scene([cam], {1: [zone]}, {1: st}, {}, calibs={}).sections[0].people == lin.sections[0].people


def test_click_order_does_not_matter_it_is_normalized_to_far_left_far_right_near_right_near_left():
    a = FloorCalib(PTS, 4.0, 3.0)
    for order in ((3, 2, 1, 0), (2, 0, 3, 1), (1, 3, 0, 2)):          # inclusive "fundo" clicado embaixo, como numa captura real
        b = FloorCalib(tuple(PTS[i] for i in order), 4.0, 3.0)
        assert b.pts == a.pts and b.to_local(0.5, 0.65, ASPECT) == a.to_local(0.5, 0.65, ASPECT)


def test_floor_corners_may_be_outside_the_image():
    """O chão passa da borda da imagem: dá para marcar cantos fora dela (a perspectiva é calculada igual)."""
    out = ((0.30, 0.30), (0.70, 0.30), (1.25, 1.2), (-0.25, 1.2))
    c = FloorCalib(out, 6.0, 4.0)
    inside = c.to_local(0.5, 0.8, ASPECT)
    assert inside is not None and 0.0 < inside[0] < ASPECT and 0.0 < inside[1] < 1.0
