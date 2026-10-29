"""Mapa do ambiente no motor: câmeras presas só com o mapa aberto, layout salvo por câmera e histórico por área."""

import time
from dataclasses import replace

import pytest

from atendeio.app.core import AppCore
from atendeio.errors import NotFoundError, ValidationError
from tests.conftest import FakeDetector


def wait(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.03)
    return False


@pytest.fixture
def core(settings, tmp_path):
    import cv2
    import numpy as np
    paths = []
    for i in range(3):
        p = tmp_path / f"cam{i}.avi"
        w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"MJPG"), 30, (320, 180))
        for k in range(300):
            w.write(np.full((180, 320, 3), k % 255, np.uint8))
        w.release()
        paths.append(p)
    devices = [{"ref": str(p), "name": f"Câmera {i}"} for i, p in enumerate(paths)]
    c = AppCore(replace(settings, mode="desktop", max_cameras=10, max_cameras_per_user=1, monitor_fps=20.0),
                detector=FakeDetector(), device_lister=lambda: devices)
    c.start()
    c.paths = [str(p) for p in paths]
    yield c
    c.stop()


def test_opening_the_map_reads_every_camera_without_counting_viewers(core):
    ids = [core.add_local(p, f"C{i}")["id"] for i, p in enumerate(core.paths)]
    core.map_enter()
    for cid in ids:
        assert wait(lambda cid=cid: core.c.registry.get(cid) is not None), cid
        hub = core.c.registry.get(cid)
        assert hub.map_pin and hub.viewers == 0                                   # preso, mas não é espectador
    assert len(core.c.registry._hubs) == 3                                         # as 3, apesar de max_cameras_per_user=1
    assert wait(lambda: all(core.c.registry.get(c).snapshot_state()["online"] for c in ids))
    snap = core.map_snapshot()
    assert set(snap["states"]) == set(ids) and all(snap["states"][c] is not None for c in ids)


def test_closing_the_map_releases_unmonitored_cameras_but_keeps_monitored_ones(core):
    a, b, c = [core.add_local(p, f"C{i}")["id"] for i, p in enumerate(core.paths)]
    core.set_recognition(b, True, [0])
    core.set_monitor(b, True)                                                      # a câmera b é monitorada
    core.map_enter()
    assert wait(lambda: all(core.c.registry.get(x) is not None for x in (a, b, c)))
    core.map_leave()
    assert wait(lambda: core.c.registry.get(a) is None and core.c.registry.get(c) is None, timeout=8)   # liberadas
    assert core.c.registry.get(b) is not None and not core.c.registry.get(b).map_pin                    # monitorada continua


def test_a_camera_watched_by_the_user_survives_the_map(core):
    a = core.add_local(core.paths[0], "A")["id"]
    w = core.watch(a, lambda f, s: None)
    core.map_enter()
    core.map_leave()
    time.sleep(0.6)                                                                # além do idle_ttl do teste
    assert core.c.registry.get(a) is not None and core.c.registry.get(a).viewers == 1
    w.stop()


def test_global_camera_limit_is_reported_instead_of_failing(settings, tmp_path, core):
    small = AppCore(replace(settings, mode="desktop", max_cameras=1), detector=FakeDetector(),
                    device_lister=lambda: [{"ref": p, "name": "x"} for p in core.paths])
    small.start()
    try:
        ids = [small.add_local(p, f"C{i}")["id"] for i, p in enumerate(core.paths[:2])]
        small.map_enter()
        snap = small.map_snapshot()
        assert len(snap["limited"]) == 1 and snap["limited"][0] in ids             # a 2ª não coube: aparece como "limite"
        assert len(small.c.registry._hubs) == 1
    finally:
        small.stop()


def test_rtsp_camera_without_credentials_is_skipped_by_the_map(core):
    cam = core.add_rtsp("Caixa", "192.168.1.55", 554, "u", "p", "s")["id"]
    core.c.credentials.forget(cam)                                                 # como depois de reiniciar o computador
    core.map_enter()
    time.sleep(0.3)
    assert core.c.registry.get(cam) is None                                        # não tenta abrir sem senha
    assert core.map_snapshot()["cameras"][0]["needs_credentials"] is True


def test_map_layout_persists_per_camera_with_validation_and_cascade(core):
    a, b = [core.add_local(p, n)["id"] for p, n in zip(core.paths, "AB")]
    assert core.map_layouts() == {}
    core.set_map_layout(a, 2.5, -1.0, 1.4)
    core.set_map_layout(a, 3.0, 0.5, 9.0)                                          # sobrescreve; escala presa a 3
    assert core.map_layouts() == {a: (3.0, 0.5, 3.0, 0.0)}
    for bad in (float("nan"), "x", 1e9):
        with pytest.raises(ValidationError):
            core.set_map_layout(b, bad, 0, 1)
    with pytest.raises(NotFoundError):
        core.set_map_layout(999, 0, 0, 1)                                          # câmera de outro dono / inexistente
    core.set_map_layout(b, 1, 1, 0.01)
    assert core.map_layouts()[b][2] == 0.4                                          # escala mínima
    core.remove_camera(a)
    assert a not in core.map_layouts()                                              # some junto com a câmera
    core.reset_map_layout()
    assert core.map_layouts() == {}


def test_zone_cache_is_refreshed_when_areas_change(core):
    a = core.add_local(core.paths[0], "A")["id"]
    assert core.map_snapshot()["zones"][a] == []
    z = {"name": "Mesa 1", "kind": "mesa", "shape": "rect", "angle": 0, "margin": 0.06,
         "points": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.5], [0.1, 0.5]]}
    core.replace_zones(a, [z])
    assert [x["name"] for x in core.map_snapshot()["zones"][a]] == ["Mesa 1"]       # o cache não ficou velho
    core.replace_zones(a, [])
    assert core.map_snapshot()["zones"][a] == []


def test_area_profile_gives_hourly_avg_and_peak_for_one_zone_only(core):
    a = core.add_local(core.paths[0], "A")["id"]
    now = int(time.time())
    h = now // 3600
    batch = {"camera_id": a, "minute": {}, "hour": {},
             "area": {(1, h - 1): (3600, 3600 * 4, 7, "Mesa 1", "mesa"), (1, h - 2): (1800, 1800 * 2, 3, "Mesa 1", "mesa"),
                      (2, h - 1): (3600, 3600 * 9, 9, "Fila", "fila")}}
    core.c.flow_writer.submit(batch)
    assert wait(lambda: core.c.flow_writer.written >= 1)
    prof = core.area_profile(a, 1, days=2)
    assert prof["samples"] == 3600 + 1800 and prof["peak"]["value"] == 7
    filled = [x for x in prof["hourly"] if x["samples"]]
    assert len(filled) == 2 and all(x["avg"] is not None for x in filled)
    assert all(x["avg"] is None and x["max"] is None for x in prof["hourly"] if not x["samples"])   # lacuna, nunca zero
    assert core.area_profile(a, 2, days=2)["peak"]["value"] == 9                                      # outra área, outro perfil
    assert core.area_profile(a, 99, days=2)["samples"] == 0
    with pytest.raises(NotFoundError):
        core.area_profile(999, 1)


# ── só as câmeras SELECIONADAS ─────────────────────────────────────────────────────────────────────────
def test_map_reads_and_returns_only_the_selected_cameras(core):
    a, b, c = [core.add_local(p, f"C{i}")["id"] for i, p in enumerate(core.paths)]
    core.map_enter([a])                                                           # só a câmera a está selecionada
    assert wait(lambda: core.c.registry.get(a) is not None)
    time.sleep(0.4)
    assert core.c.registry.get(b) is None and core.c.registry.get(c) is None      # as outras nem são abertas
    snap = core.map_snapshot([a])
    assert [x["id"] for x in snap["cameras"]] == [a] and set(snap["states"]) == {a} and set(snap["zones"]) == {a}
    assert {x["id"] for x in core.map_snapshot()["cameras"]} == {a, b, c}         # sem filtro: todas (uso por outras telas)


def test_selection_changes_pin_new_cameras_and_release_deselected_ones_live(core):
    a, b = [core.add_local(p, f"C{i}")["id"] for i, p in enumerate(core.paths[:2])]
    core.map_enter([a])
    assert wait(lambda: core.c.registry.get(a) is not None)
    core.map_select([a, b])                                                       # marcou a câmera b com o mapa aberto
    assert wait(lambda: core.c.registry.get(b) is not None and core.c.registry.get(b).map_pin)
    core.map_select([b])                                                          # desmarcou a: solta (não é monitorada)
    assert wait(lambda: core.c.registry.get(a) is None, timeout=8)
    assert core.c.registry.get(b) is not None
    core.map_select([])                                                           # nenhuma selecionada: nada preso
    assert wait(lambda: core.c.registry.get(b) is None, timeout=8)
    assert core.map_snapshot([])["cameras"] == []


def test_a_deselected_monitored_camera_keeps_running_but_leaves_the_map(core):
    a, b = [core.add_local(p, f"C{i}")["id"] for i, p in enumerate(core.paths[:2])]
    core.set_recognition(a, True, [0])
    core.set_monitor(a, True)
    core.map_enter([a, b])
    assert wait(lambda: core.c.registry.get(a) is not None and core.c.registry.get(b) is not None)
    core.map_select([b])
    assert wait(lambda: core.c.registry.get(a) is not None and not core.c.registry.get(a).map_pin)   # a é monitorada: segue lendo
    assert [x["id"] for x in core.map_snapshot([b])["cameras"]] == [b]                               # mas some do mapa


class WalkingDetector(FakeDetector):
    """Uma pessoa que anda da esquerda para a direita a cada leitura."""
    def detect(self, frame, classes=None, masks=False):
        out = super().detect(frame, classes, masks)
        if out:
            x = min(0.1 + 0.02 * self.calls, 0.9)
            out[0]["box"] = (x - 0.05, 0.3, x + 0.05, 0.8)
        return out


def test_map_reads_walking_people_with_a_stable_id_and_faster_than_monitoring(settings, tmp_path):
    import cv2
    import numpy as np
    p = tmp_path / "walk.avi"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"MJPG"), 30, (320, 180))
    for k in range(300):
        w.write(np.full((180, 320, 3), k % 255, np.uint8))
    w.release()
    c = AppCore(replace(settings, mode="desktop", monitor_fps=1.0, map_fps=20.0),
                detector=WalkingDetector(), device_lister=lambda: [{"ref": str(p), "name": "A"}])
    c.start()
    try:
        cid = c.add_local(str(p), "A")["id"]
        c.set_recognition(cid, True, [0])
        c.map_enter()
        assert wait(lambda: c.map_snapshot()["states"].get(cid) and len(c.map_snapshot()["states"][cid].get("tracks", [])) == 1)
        first = c.map_snapshot()["states"][cid]["tracks"][0]
        assert wait(lambda: c.map_snapshot()["states"][cid]["tracks"] and c.map_snapshot()["states"][cid]["tracks"][0]["x"] > first["x"] + 0.1)
        later = c.map_snapshot()["states"][cid]["tracks"][0]
        assert later["id"] == first["id"] and abs(later["y"] - 0.8) < 1e-6 and abs(later["h"] - 0.5) < 1e-6 and later["full"] is True     # mesmo id; "y" = os pés (base da caixa)
        assert c.c.registry.get(cid).fps > 3.0                                  # ritmo do mapa, não o 1 fps do monitor
    finally:
        c.stop()


def test_without_the_map_or_areas_no_tracking_runs(core):
    cid = core.add_local(core.paths[0], "A")["id"]
    core.set_recognition(cid, True, [0])
    core.set_monitor(cid, True)                       # a câmera fica lida pelo monitor, sem mapa e sem áreas
    assert wait(lambda: core.c.registry.get(cid) is not None and core.c.registry.get(cid).snapshot_state()["online"])
    assert wait(lambda: core.c.registry.get(cid).snapshot_state()["people"] is not None)
    assert core.c.registry.get(cid).snapshot_state()["tracks"] == []


def test_floor_calibration_persists_is_validated_and_follows_the_camera(core):
    cid = core.add_local(core.paths[0], "A")["id"]
    pts = [(0.35, 0.4), (0.65, 0.4), (0.9, 0.9), (0.1, 0.9)]
    assert core.map_calibrations() == {}
    core.set_map_calibration(cid, pts, 4.0, 3.0)
    got = core.map_calibrations()[cid]
    assert got.width == 4.0 and got.pts[0] == (0.35, 0.4)
    with pytest.raises(ValidationError):
        core.set_map_calibration(cid, pts[:3], 4.0, 3.0)
    with pytest.raises(ValidationError):
        core.set_map_calibration(cid, pts, 0, 3.0)
    core.clear_map_calibration(cid)
    assert core.map_calibrations() == {}
    core.set_map_calibration(cid, pts, 4.0, 3.0)
    core.remove_camera(cid)
    assert core.map_calibrations() == {}                  # some junto com a câmera (cascade)


def test_zone_rotation_is_saved_per_camera_and_old_layouts_default_to_zero(core):
    a, b = [core.add_local(p, n)["id"] for p, n in zip(core.paths[:2], "AB")]
    core.set_map_layout(a, 1.0, 2.0, 1.5)                                   # forma antiga (sem rotação)
    core.set_map_layout(b, 3.0, 4.0, 1.0, 450.0)                            # 450° = 90°
    got = core.map_layouts()
    assert got[a] == (1.0, 2.0, 1.5, 0.0) and got[b] == (3.0, 4.0, 1.0, 90.0)
    with pytest.raises(ValidationError):
        core.set_map_layout(a, 1.0, 2.0, 1.0, float("nan"))


def test_an_old_database_gets_the_rotation_column(tmp_path):
    import sqlite3
    from atendeio.db import Database
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript("CREATE TABLE map_layout (camera_id INTEGER PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL, scale REAL NOT NULL DEFAULT 1);")
    c.commit(); c.close()
    db = Database(path)
    db.init()
    c = sqlite3.connect(path)
    assert "rot" in {r[1] for r in c.execute("PRAGMA table_info(map_layout)")}
