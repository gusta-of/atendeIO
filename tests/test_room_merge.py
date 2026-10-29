import pytest

from atendeio.app import map_model as M
from atendeio.app.floor_calib import FloorCalib
from atendeio.app.room_merge import Dot, merge

UPM = 2.0          # 2 unidades do mundo por metro


def dot(cam, pid, x, y, room="Salão", upm=UPM):
    return Dot(cam, pid, x, y, room, upm)


def test_the_same_person_seen_by_two_cameras_of_the_same_room_counts_once():
    people, dup = merge([dot(1, 7, 3.0, 2.0), dot(2, 4, 3.4, 2.2)])          # 0,45 m de distância
    assert dup == 1 and len(people) == 1
    p = people[0]
    assert p.key == (1, 7) and p.members == [(1, 7), (2, 4)]                  # o marcador fica com a câmera de menor id
    assert (p.x, p.y) == pytest.approx((3.2, 2.1))                            # na média das duas leituras


def test_people_farther_than_half_a_meter_stay_two():
    people, dup = merge([dot(1, 1, 3.0, 2.0), dot(2, 1, 4.2, 2.0)])           # 0,6 m
    assert dup == 0 and len(people) == 2


def test_different_rooms_or_no_room_or_no_calibration_are_never_merged():
    assert merge([dot(1, 1, 0, 0, "A"), dot(2, 1, 0, 0, "B")])[1] == 0
    assert merge([dot(1, 1, 0, 0, ""), dot(2, 1, 0, 0, "")])[1] == 0
    assert merge([dot(1, 1, 0, 0, upm=None), dot(2, 1, 0, 0)])[1] == 0
    assert merge([dot(1, 1, 0, 0, "Salão"), dot(2, 1, 0, 0, "  salão ")])[1] == 1      # maiúsculas e espaços não contam


def test_two_people_of_the_same_camera_are_never_merged_even_if_close():
    people, dup = merge([dot(1, 1, 3.0, 2.0), dot(1, 2, 3.2, 2.0)])
    assert dup == 0 and len(people) == 2


def test_each_person_pairs_with_the_closest_one_of_the_other_camera():
    people, dup = merge([dot(1, 1, 0.0, 0.0), dot(1, 2, 1.0, 0.0), dot(2, 1, 0.1, 0.0), dot(2, 2, 1.1, 0.0)])
    assert dup == 2 and sorted(p.members for p in people) == [[(1, 1), (2, 1)], [(1, 2), (2, 2)]]


def test_three_cameras_see_one_person():
    people, dup = merge([dot(1, 1, 0, 0), dot(2, 1, 0.2, 0), dot(3, 1, 0.1, 0.1)])
    assert dup == 2 and len(people) == 1 and len(people[0].members) == 3


def test_the_scene_totals_do_not_double_count_a_person_seen_by_two_calibrated_cameras():
    cal = FloorCalib(((0.3, 0.3), (0.7, 0.3), (0.95, 0.95), (0.05, 0.95)), 4.0, 3.0)
    cams = [{"id": 1, "name": "A", "room": "Salão"}, {"id": 2, "name": "B", "room": "Salão"}]
    st = {"size": [1600, 900], "online": True, "areas": [], "people": 1, "tracks": [{"id": 1, "x": 0.5, "y": 0.6}]}
    both = M.build_scene(cams, {1: [], 2: []}, {1: st, 2: st}, {1: M.Layout(0, 0, 1.0), 2: M.Layout(0, 0, 1.0)}, calibs={1: cal, 2: cal})
    assert both.totals["people"] == 1 and both.totals["duplicates"] == 1 and len(both.crowd) == 1
    # sem sala: duas pessoas (como antes)
    nosala = M.build_scene([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}], {1: [], 2: []}, {1: st, 2: st},
                           {1: M.Layout(0, 0, 1.0), 2: M.Layout(0, 0, 1.0)}, calibs={1: cal, 2: cal})
    assert nosala.totals["people"] == 2 and len(nosala.crowd) == 2


def test_merge_is_sticky_while_walking_and_releases_far_apart():
    from atendeio.app.room_merge import RoomMerger
    m = RoomMerger(max_m=0.5)
    assert m.merge([dot(1, 1, 0.0, 0.0), dot(2, 1, 0.8, 0.0)], 0.0)[1] == 1          # 0,4 m: junta
    for i, gap_m in enumerate((0.6, 0.8, 0.85, 0.7), start=1):                       # andando: a distância passa do raio de 0,5 m
        assert m.merge([dot(1, 1, 0.0, 0.0), dot(2, 1, gap_m * UPM, 0.0)], i * 0.25)[1] == 1     # mas continua UMA pessoa
    assert m.merge([dot(1, 1, 0.0, 0.0), dot(2, 1, 1.2 * UPM, 0.0)], 2.0)[1] == 0    # 1,2 m (> 0,9 m = 1,8 × 0,5): se separam
    # uma dupla que nunca foi unida NÃO usa a folga
    n = RoomMerger(max_m=0.5)
    assert n.merge([dot(1, 1, 0.0, 0.0), dot(2, 1, 0.8 * UPM, 0.0)], 0.0)[1] == 0


def test_link_is_forgotten_after_the_hold_time_if_a_track_disappears():
    from atendeio.app.room_merge import RoomMerger
    m = RoomMerger(max_m=0.5)
    m.merge([dot(1, 1, 0.0, 0.0), dot(2, 1, 0.4, 0.0)], 0.0)
    m.merge([dot(1, 1, 0.0, 0.0)], 0.5)                                               # a outra câmera perdeu a pessoa um instante
    assert m.merge([dot(1, 1, 0.0, 0.0), dot(2, 1, 0.7 * UPM, 0.0)], 0.9)[1] == 1     # voltou: ainda ligada
    m.merge([dot(1, 1, 0.0, 0.0)], 1.0)
    assert m.merge([dot(1, 1, 0.0, 0.0), dot(2, 1, 0.7 * UPM, 0.0)], 3.0)[1] == 0     # ligação esquecida


def test_crowded_room_caps_the_merge_radius_and_stays_fast_with_sixty_people_per_camera():
    import random
    import time
    from atendeio.app.room_merge import RoomMerger
    random.seed(4)
    cam1 = [dot(1, i, random.uniform(0, 20), random.uniform(0, 20)) for i in range(60)]                 # 60 pessoas na câmera 1
    cam2 = [dot(2, i, d.x + random.uniform(-0.15, 0.15), d.y + random.uniform(-0.15, 0.15)) for i, d in enumerate(cam1)]   # as mesmas, com ruído
    m = RoomMerger(max_m=1.5)                                                                           # raio grande (alinhamento ruim)
    t0 = time.perf_counter()
    for k in range(5):
        people, dup = m.merge(cam1 + cam2, k * 0.25)
    assert (time.perf_counter() - t0) / 5 < 0.15                                                       # cada tick, 120 detecções
    assert dup >= 55 and len(people) <= 65                                                             # quase todas casadas, sem fundir estranhos
    # raio limitado em sala cheia: pares a 1 m (UPM unidades = 1 m) unem em sala vazia (raio 1,5) mas NÃO em sala cheia
    def pairs(n):
        a = [dot(1, i, i * 40.0, 0.0) for i in range(n)]
        return a + [dot(2, i, i * 40.0 + 1.0 * UPM, 0.0) for i in range(n)]
    assert merge(pairs(5), 1.5)[1] == 5            # 10 detecções: raio de 1,5 m, tudo casa
    assert merge(pairs(8), 1.5)[1] == 0            # 16 detecções (sala cheia): raio limitado a 0,6 m, ninguém casa a 1 m


def test_scene_with_sixty_people_per_camera_builds_quickly():
    import time
    from atendeio.app.floor_calib import FloorCalib
    cal = FloorCalib(((0.3, 0.3), (0.7, 0.3), (0.95, 0.95), (0.05, 0.95)), 4.0, 3.0)
    cams = [{"id": 1, "name": "A", "room": "S"}, {"id": 2, "name": "B", "room": "S"}]
    tracks = [{"id": i, "x": 0.1 + 0.8 * (i % 10) / 10, "y": 0.3 + 0.6 * (i // 10) / 6, "h": 0.2, "full": True} for i in range(60)]
    st = {"size": [1600, 900], "online": True, "areas": [], "people": 60, "tracks": tracks}
    t0 = time.perf_counter()
    for _ in range(5):
        sc = M.build_scene(cams, {1: [], 2: []}, {1: st, 2: st}, {1: M.Layout(0, 0, 1.0), 2: M.Layout(0, 0, 1.0)}, calibs={1: cal, 2: cal})
    assert (time.perf_counter() - t0) / 5 < 0.2
    assert sc.totals["people"] <= 65 and len(sc.crowd) <= 65          # as mesmas 60 pessoas nas duas câmeras ≈ 60 (não 120)


FLOOR_A = [(0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (0.0, 8.0)]            # 4 m × 4 m em unidades do mundo (UPM = 2)
FLOOR_B = [(1.0, 1.0), (9.0, 1.0), (9.0, 9.0), (1.0, 9.0)]            # a outra câmera, deslocada ~1 m na diagonal (alinhamento ruim)


def seen(cam, pid, x, y, floor):
    return Dot(cam, pid, x, y, "Sala", UPM, 0.2, floor)


def test_same_count_in_both_cameras_merges_even_with_a_poor_alignment_if_both_should_see_it():
    """Caso real: a mesma (única) pessoa cai a ~2 m nas duas câmeras porque o alinhamento é aproximado: conta UMA vez."""
    a = seen(1, 1, 3.0, 3.0, FLOOR_A)
    b = seen(2, 1, 7.0, 5.5, FLOOR_B)                                  # 2,4 m de distância (> raio de 0,5 m)
    people, dup = merge([a, b])
    assert dup == 1 and len(people) == 1
    # contagens diferentes: não vale o raio largo (1 pessoa numa câmera e 2 na outra)
    assert merge([a, b, seen(1, 2, 0.5, 0.5, FLOOR_A)])[1] == 0


def test_wide_radius_never_applies_to_people_neither_camera_could_both_see():
    a = seen(1, 1, 0.5, 0.5, FLOOR_A)                                  # canto de A...
    b = seen(2, 1, 17.0, 17.0, FLOOR_B)                                # ...e canto oposto de B, longe de A (8 m de distância, > 3 m)
    assert merge([a, b])[1] == 0
    # perto na distância mas longe do chão da outra câmera (> 1,5 m): uma pessoa que só uma câmera deveria ver
    far_a = seen(1, 1, -6.0, -6.0, FLOOR_A)
    near_b = seen(2, 1, -3.0, -3.0, FLOOR_B)                           # 2,1 m entre elas
    assert merge([far_a, near_b])[1] == 0
    # sem o chão das câmeras não dá para afirmar que as duas deveriam vê-la: vale só o raio normal
    assert merge([seen(1, 1, 3.0, 3.0, None), seen(2, 1, 7.0, 5.5, None)])[1] == 0


def test_a_crowd_with_equal_counts_above_the_limit_does_not_use_the_wide_radius():
    a = [seen(1, i, 3.0 + i * 10, 3.0, FLOOR_A) for i in range(6)]
    b = [seen(2, i, 3.0 + i * 10 + 4.0, 3.0, FLOOR_B) for i in range(6)]            # 2 m de cada um, 6 por câmera (> 4)
    assert merge(a + b)[1] == 0
