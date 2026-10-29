"""FPS por câmera: salvo no banco (None = padrão), validado e aplicado ao vivo no pipeline."""

import sqlite3
import threading
import time
from dataclasses import replace

import pytest

from atendeio.app.core import AppCore
from atendeio.db import Database
from atendeio.errors import NotFoundError, ValidationError
from tests.conftest import FakeDetector


@pytest.fixture
def core(settings, video_file):
    c = AppCore(replace(settings, mode="desktop", max_fps=30.0, monitor_fps=30.0), detector=FakeDetector(),
                device_lister=lambda: [{"ref": str(video_file), "name": "Câmera"}])
    c.start()
    yield c
    c.stop()


def frames_in(core, cam, seconds):
    n, lock = [0], threading.Lock()

    def cb(frame, state):
        with lock:
            n[0] += 1
    w = core.watch(cam, cb, boxes=False, areas=False)
    time.sleep(0.5)                       # aquecimento: o primeiro quadro demora
    with lock:
        n[0] = 0
    time.sleep(seconds)
    w.stop()
    with lock:
        return n[0]


def test_defaults_are_none_and_show_the_system_defaults(core, video_file):
    cam = core.add_local(str(video_file), "A")["id"]
    f = core.fps(cam)
    assert f["view"] is None and f["monitor"] is None
    assert f["default_view"] == 30.0 and f["default_monitor"] == 30.0


def test_saved_and_reset_to_default(core, video_file):
    cam = core.add_local(str(video_file), "A")["id"]
    assert core.set_fps(cam, 8, 0.5)["view"] == 8 and core.fps(cam)["monitor"] == 0.5
    assert core.set_fps(cam, None, None)["view"] is None                       # voltar ao padrão


@pytest.mark.parametrize("view,monitor", [(0.5, None), (31, None), (None, 0.1), (None, 11), (float("nan"), None), ("x", None)])
def test_out_of_range_or_garbage_is_refused_and_nothing_changes(core, video_file, view, monitor):
    cam = core.add_local(str(video_file), "A")["id"]
    core.set_fps(cam, 5, 1)
    with pytest.raises(ValidationError):
        core.set_fps(cam, view, monitor)
    assert (core.fps(cam)["view"], core.fps(cam)["monitor"]) == (5, 1)


def test_other_users_camera_is_not_found(core, video_file):
    with pytest.raises(NotFoundError):
        core.c.cameras.set_fps(999, core.user_id, 5, 1)


def test_lower_fps_really_slows_the_pipeline_and_applies_live(core, video_file):
    cam = core.add_local(str(video_file), "A")["id"]
    fast = frames_in(core, cam, 2.0)                                           # padrão de teste: 30 fps
    core.set_fps(cam, 2, None)
    slow = frames_in(core, cam, 2.0)
    assert fast > 15 and slow <= 6 and slow >= 1                               # ~2 fps: ≈4 quadros em 2 s
    core.set_fps(cam, None, None)
    assert frames_in(core, cam, 1.5) > 10                                      # voltou ao padrão


def test_saved_fps_is_loaded_when_the_pipeline_is_recreated(core, video_file):
    cam = core.add_local(str(video_file), "A")["id"]
    core.set_fps(cam, 3, 0.7)
    hub = core.c.registry.acquire(cam, core.user_id, lambda: core.c.cameras.source_for(core.camera(cam)))
    try:
        assert (hub.fps_view, hub.fps_monitor) == (3, 0.7)
    finally:
        core.c.registry.release(hub)
        core.c.registry.stop_all()


def test_monitoring_uses_the_monitor_fps_when_nobody_watches(core, video_file):
    cam = core.add_local(str(video_file), "A")["id"]
    core.set_recognition(cam, True, [0])
    core.set_fps(cam, 20, 2)
    core.set_monitor(cam, True)
    hub = None
    end = time.time() + 5
    while time.time() < end and (hub is None or not hub.ready.is_set()):
        hub = core.c.registry.get(cam)
        time.sleep(0.05)
    time.sleep(1.5)
    assert hub.fps_monitor == 2 and hub.fps <= 2.0                              # sem espectador: ritmo do monitoramento


def test_old_databases_get_the_new_columns(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, pw_hash TEXT, created REAL);
        CREATE TABLE cameras (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL,
        secret BLOB, monitor INTEGER NOT NULL DEFAULT 0, monitor_from TEXT, monitor_to TEXT,
        recognition INTEGER NOT NULL DEFAULT 1, classes TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL);
        INSERT INTO cameras(id, user_id, name, kind, ref, created) VALUES (1, 1, 'Velha', 'local', '/dev/x', 0);""")
    conn.commit(); conn.close()
    db = Database(path)
    db.init()                                                                   # migra sem perder a câmera
    cols = {r["name"] for r in db.connect().execute("PRAGMA table_info(cameras)")}
    assert {"fps_view", "fps_monitor"} <= cols
    assert db.connect().execute("SELECT name, fps_view FROM cameras").fetchone()["name"] == "Velha"
