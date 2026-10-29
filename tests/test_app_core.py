"""AppCore: o motor do app desktop, em processo, sem HTTP."""

import subprocess
import sys
import threading
import time
from dataclasses import replace

import pytest

from atendeio.app.core import AppCore
from atendeio.errors import CredentialsRequired, NotFoundError
from tests.conftest import FakeDetector

PASSWORD = "S3nh@-Nativa-4471"


@pytest.fixture
def core(settings, video_file):
    devices = [{"ref": str(video_file), "name": "Câmera de teste"}]
    c = AppCore(replace(settings, mode="desktop"), detector=FakeDetector(), device_lister=lambda: devices)
    c.start()
    yield c
    c.stop()


def wait(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.03)
    return False


def test_the_app_core_does_not_pull_in_any_web_server():
    code = ("import sys, atendeio.app.core\n"
            "bad = [m for m in ('fastapi', 'uvicorn', 'starlette', 'httpx') if m in sys.modules]\n"
            "print(','.join(bad))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "", f"o núcleo do app desktop importou um servidor web: {out}"


def test_local_owner_is_fixed_and_idempotent(settings, video_file):
    a = AppCore(replace(settings, mode="desktop"), detector=FakeDetector(), device_lister=lambda: [])
    b = AppCore(replace(settings, mode="desktop"), detector=FakeDetector(), device_lister=lambda: [])
    assert a.user_id == b.user_id                                         # mesmo banco: mesmo dono local, sem duplicar


def test_add_watch_and_stop_a_local_camera(core, video_file):
    cam = core.add_local(str(video_file), "Entrada")
    assert core.cameras()[0]["name"] == "Entrada" and cam["id"] == core.cameras()[0]["id"]
    got, lock = [], threading.Lock()

    def on_frame(frame, state):
        with lock:
            got.append((frame.shape, state["people"]))

    w = core.watch(cam["id"], on_frame, boxes=False, areas=False)
    try:
        assert wait(lambda: len(got) >= 2)
        assert core.states()[cam["id"]]["online"] is True
    finally:
        w.stop()
        w.stop()                                                          # idempotente
    assert core.c.registry.get(cam["id"]).viewers == 0


def test_remove_camera_stops_its_pipeline(core, video_file):
    cam = core.add_local(str(video_file), "X")
    w = core.watch(cam["id"], lambda f, s: None)
    assert core.c.registry.get(cam["id"]) is not None
    core.remove_camera(cam["id"])
    assert core.c.registry.get(cam["id"]) is None and core.cameras() == []
    w.stop()


def test_rtsp_password_is_memory_only_and_asked_again_after_restart(settings, video_file):
    cfg = replace(settings, mode="desktop")
    first = AppCore(cfg, detector=FakeDetector(), device_lister=lambda: [])
    cam = first.add_rtsp("Salão", "192.168.1.77", 554, "operador", PASSWORD, "stream1")
    assert cam["needs_credentials"] is False and first.cameras_needing_credentials() == []

    blob = b"".join(p.read_bytes() for p in cfg.data_dir.rglob("*") if p.is_file())
    assert PASSWORD.encode() not in blob                                  # nenhuma senha em disco

    second = AppCore(cfg, detector=FakeDetector(), device_lister=lambda: [])      # "reiniciou o computador"
    assert [c["id"] for c in second.cameras_needing_credentials()] == [cam["id"]]
    assert second.cameras()[0]["ref"] == "rtsp://192.168.1.77:554/stream1"        # IP e porta persistem
    with pytest.raises(CredentialsRequired):
        second.watch(cam["id"], lambda f, s: None)
    second.set_credentials(cam["id"], "operador", PASSWORD)
    assert second.cameras_needing_credentials() == []


def test_recognition_and_zones_roundtrip_and_apply_to_the_live_camera(core, video_file):
    cam = core.add_local(str(video_file), "Salão")["id"]
    assert core.recognition(cam) == {"enabled": True, "classes": []}
    assert core.set_recognition(cam, True, [0, 41])["classes"] == [0, 41]
    mesa = {"name": "Mesa 1", "kind": "mesa", "shape": "rect", "angle": 0, "margin": 0.06,
            "points": [[0.2, 0.2], [0.6, 0.2], [0.6, 0.6], [0.2, 0.6]]}
    saved = core.replace_zones(cam, [mesa])
    assert saved[0]["name"] == "Mesa 1" and core.zones(cam)[0]["id"] == saved[0]["id"]

    seen, lock = [], threading.Lock()
    w = core.watch(cam, lambda f, s: (lock.acquire(), seen.append(s), lock.release()), areas=True, boxes=False)
    try:
        assert wait(lambda: any(s.get("areas") for s in seen))
        zid = saved[0]["id"]
        core.mark_clean(cam, zid)                                          # existe e é da câmera
        with pytest.raises(NotFoundError):
            core.mark_clean(cam, 9999)
    finally:
        w.stop()


def test_monitor_needs_person_and_flows_into_history(core, video_file):
    cam = core.add_local(str(video_file), "Salão")["id"]
    core.set_recognition(cam, True, [0])
    assert core.set_monitor(cam, True)["enabled"] is True
    assert wait(lambda: core.c.registry.get(cam) is not None and core.c.registry.get(cam).monitor)
