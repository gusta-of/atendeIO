import pytest

from atendeio.app.people_model import PeopleSmoother
from atendeio.app import map_model as M


def test_marker_slides_to_target_not_jumps():
    s = PeopleSmoother()
    s.update([(1, 7, 0.0, 0.0)], now=0.0)
    s.step(0.0)
    s.update([(1, 7, 1.0, 0.0)], now=0.25)
    m = s.step(0.30)[0]
    assert 0.0 < m.x < 1.0 and m.pid == 7
    for t in (0.5, 0.8, 1.2):
        m = s.step(t)[0]
    assert m.x > 0.95


def test_person_expires_after_ttl_and_trail_is_bounded():
    s = PeopleSmoother(ttl_s=1.0, trail_s=2.0)
    for i in range(10):
        s.update([(1, 1, i * 0.1, 0.0)], now=i * 0.5)
        m = s.step(i * 0.5)[0]
    assert all(t >= 0 for t, _ in m.trail) and len(m.trail) <= 5          # só os últimos 2 s
    assert s.step(10.0) == []


def test_scene_maps_feet_into_the_camera_section():
    cam = {"id": 1, "name": "A"}
    st = {"size": [1000, 500], "online": True, "areas": [], "people": 1,
          "tracks": [{"id": 3, "x": 0.5, "y": 1.0}]}
    sc = M.build_scene([cam], {1: []}, {1: st}, {1: M.Layout(10.0, 20.0, 2.0)})
    pid, x, y = sc.sections[0].people[0]
    assert pid == 3 and abs(x - (10.0 + 0.5 * 2.0 * 2.0)) < 1e-9 and abs(y - 22.0) < 1e-9


def test_no_people_when_camera_is_not_ok():
    cam = {"id": 1, "name": "A"}
    sc = M.build_scene([cam], {1: []}, {1: None}, {})
    assert sc.sections[0].people == []
