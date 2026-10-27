from atendeio.analytics.geometry import (box_overlap_fraction, feet_in_zone, iou, membership_score, point_in_polygon,
                                         polygon_area, point_polygon_distance, zone_coverage_fraction)

SQUARE = [(0.2, 0.2), (0.6, 0.2), (0.6, 0.6), (0.2, 0.6)]
L_SHAPE = [(0, 0), (1, 0), (1, 0.4), (0.4, 0.4), (0.4, 1), (0, 1)]  # côncavo


def test_point_in_polygon():
    assert point_in_polygon(0.4, 0.4, SQUARE)
    assert not point_in_polygon(0.7, 0.4, SQUARE)
    assert not point_in_polygon(0.4, 0.1, SQUARE)


def test_concave_polygon():
    assert point_in_polygon(0.2, 0.8, L_SHAPE)       # braço vertical do L
    assert point_in_polygon(0.8, 0.2, L_SHAPE)       # braço horizontal
    assert not point_in_polygon(0.8, 0.8, L_SHAPE)   # o "buraco" do L


def test_area_and_iou():
    assert abs(polygon_area(SQUARE) - 0.16) < 1e-9
    assert polygon_area([(0, 0), (1, 1), (2, 2)]) == 0  # degenerado
    assert iou((0, 0, 1, 1), (0, 0, 1, 1)) == 1
    assert iou((0, 0, 1, 1), (2, 2, 3, 3)) == 0
    assert 0.3 < iou((0, 0, 2, 2), (1, 0, 3, 2)) < 0.34


def test_box_overlap_fraction():
    assert box_overlap_fraction((0.3, 0.3, 0.5, 0.5), SQUARE) == 1.0          # tudo dentro
    assert box_overlap_fraction((0.7, 0.7, 0.9, 0.9), SQUARE) == 0.0          # tudo fora
    half = box_overlap_fraction((0.4, 0.3, 0.8, 0.5), SQUARE)                 # metade dentro
    assert 0.45 < half < 0.55
    assert box_overlap_fraction((0.2, 0.2, 0.2, 0.5), SQUARE) == 0.0          # box sem largura
    assert box_overlap_fraction((0.6, 0.6, 1.0, 1.0), L_SHAPE) == 0.0         # no "buraco" do L


def test_zone_coverage_and_membership_score():
    small = [(0.55, 0.2), (0.67, 0.2), (0.67, 0.62), (0.55, 0.62)]
    big_person = (0.40, 0.28, 1.0, 1.0)
    assert box_overlap_fraction(big_person, small) < 0.2          # pouco do box está na área...
    assert zone_coverage_fraction(big_person, small) > 0.5        # ...mas ele cobre boa parte dela
    assert membership_score(big_person, small) > 0.5
    assert membership_score((0.0, 0.7, 0.2, 1.0), small) == 0.0   # longe: nada


def test_feet_in_zone():
    door = [(0.55, 0.2), (0.67, 0.2), (0.67, 0.62), (0.55, 0.62)]
    assert feet_in_zone((0.56, 0.25, 0.66, 0.60), door)          # pés dentro
    assert feet_in_zone((0.56, 0.25, 0.66, 0.65), door)          # pés um pouco abaixo (tolerância)
    assert not feet_in_zone((0.56, 0.25, 0.66, 0.75), door)      # pés bem abaixo: está na frente
    assert not feet_in_zone((0.56, 0.25, 0.66, 1.0), door)       # pés fora do quadro
    assert not feet_in_zone((0.10, 0.25, 0.20, 0.60), door)      # fora na horizontal


def test_point_polygon_distance():
    assert point_polygon_distance(0.4, 0.4, SQUARE) == 0.0                 # dentro
    assert abs(point_polygon_distance(0.7, 0.4, SQUARE) - 0.1) < 1e-9      # ao lado de uma aresta
    assert abs(point_polygon_distance(0.7, 0.7, SQUARE) - (0.02 ** 0.5)) < 1e-9  # junto de um canto
    assert abs(point_polygon_distance(0.8, 0.8, L_SHAPE) - 0.4) < 1e-9 or point_polygon_distance(0.8, 0.8, L_SHAPE) > 0
