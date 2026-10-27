"""Monitoramento contínuo: a câmera é analisada sem ninguém assistindo, em ritmo baixo, e o histórico é amostrado."""

import asyncio
import time
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from atendeio.container import build_container
from atendeio.services.monitor import in_window
from tests.conftest import FakeDetector

TZ = ZoneInfo("America/Sao_Paulo")


def at(hh, mm=0):
    return datetime(2026, 1, 20, hh, mm, tzinfo=TZ)


def wait(cond, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.03)
    return False


# ── horário de funcionamento ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("now,frm,to,expected", [
    ("03:00", "", "", True), ("03:00", None, None, True),                   # sem horário = o dia todo
    ("10:59", "11:00", "23:00", False), ("11:00", "11:00", "23:00", True),
    ("22:59", "11:00", "23:00", True), ("23:00", "11:00", "23:00", False),  # o fim é exclusivo
    ("23:30", "22:00", "02:00", True), ("01:59", "22:00", "02:00", True),   # vira a meia-noite
    ("02:00", "22:00", "02:00", False), ("12:00", "22:00", "02:00", False),
])
def test_in_window(now, frm, to, expected):
    assert in_window(now, frm, to) is expected


# ── API ───────────────────────────────────────────────────────────────────────────────────────
def make_cam(client, video_file, classes=None):
    cam = client.post("/api/cameras/local", json={"ref": str(video_file)}).json()["camera"]["id"]
    if classes is not None:
        client.put(f"/api/cameras/{cam}/recognition", json={"enabled": True, "classes": classes})
    return cam


def test_monitoring_requires_recognition_with_person(new_client, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file)                                           # câmera nova: nada marcado
    r = c.put(f"/api/cameras/{cam}/monitor", json={"enabled": True})
    assert r.status_code == 400 and "Pessoa" in r.json()["detail"]
    c.put(f"/api/cameras/{cam}/recognition", json={"enabled": True, "classes": [41]})   # só copo: sem Pessoa
    assert c.put(f"/api/cameras/{cam}/monitor", json={"enabled": True}).status_code == 400
    c.put(f"/api/cameras/{cam}/recognition", json={"enabled": True, "classes": [0, 41]})
    assert c.put(f"/api/cameras/{cam}/monitor", json={"enabled": True}).json()["enabled"] is True
    assert c.put(f"/api/cameras/{cam}/monitor", json={"enabled": False}).json()["enabled"] is False  # desligar não exige nada


def test_monitor_hours_are_validated_and_saved(new_client, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file, [0])
    put = lambda **b: c.put(f"/api/cameras/{cam}/monitor", json={"enabled": True, **b})
    assert put(**{"from": "11:00"}).status_code == 400                      # só um dos dois
    assert put(**{"from": "25:00", "to": "23:00"}).status_code == 400
    assert put(**{"from": "9:00", "to": "23:00"}).status_code == 400        # formato HH:MM
    assert put(**{"from": "11:00", "to": "11:00"}).status_code == 400
    ok = put(**{"from": "11:00", "to": "23:30"}).json()
    assert ok == {"enabled": True, "from": "11:00", "to": "23:30", "person_ready": True}
    assert c.get(f"/api/cameras/{cam}/monitor").json() == ok


def test_monitor_is_isolated_between_users(new_client, video_file):
    alice, bob, anon = new_client("alice"), new_client("bob"), new_client()
    cam = make_cam(alice, video_file, [0])
    assert bob.get(f"/api/cameras/{cam}/monitor").status_code == 404
    assert bob.put(f"/api/cameras/{cam}/monitor", json={"enabled": True}).status_code == 404
    assert anon.get(f"/api/cameras/{cam}/monitor").status_code == 401


# ── agendador ─────────────────────────────────────────────────────────────────────────────────
def test_monitored_camera_runs_without_any_viewer_and_survives_the_reaper(new_client, container, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file, [0])
    c.put(f"/api/cameras/{cam}/monitor", json={"enabled": True})
    out = container.scheduler.tick(at(15))
    assert out["held"] == [cam] and out["errors"] == []
    hub = container.registry.get(cam)
    try:
        assert hub.monitor and hub.viewers == 0                              # de pé, mas não conta como espectador
        assert hub.ready.wait(10) and wait(lambda: hub.snapshot_state()["people"] == 1)   # medindo, sem ninguém olhando
        assert hub.last_jpeg(False) == b""                                   # e sem gerar vídeo
        time.sleep(0.4)                                                      # idle_ttl_s = 0.1 nos testes
        container.registry.reap_idle()
        assert container.registry.get(cam) is hub                            # o reaper não derruba hub monitorado
    finally:
        container.scheduler.stop()
        container.registry.stop_all()


def test_outside_business_hours_the_hold_is_released_and_the_hub_goes_idle(new_client, container, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file, [0])
    c.put(f"/api/cameras/{cam}/monitor", json={"enabled": True, "from": "11:00", "to": "23:00"})
    assert container.scheduler.tick(at(15))["held"] == [cam]
    hub = container.registry.get(cam)
    try:
        out = container.scheduler.tick(at(3))                                # madrugada: fora do horário
        assert out["held"] == [] and out["released"] == [cam] and not hub.monitor
        time.sleep(0.4)
        container.registry.reap_idle()
        assert container.registry.get(cam) is None                           # ocioso e sem monitor: sai (poupa CPU)
        assert container.scheduler.tick(at(12))["held"] == [cam]             # volta quando abre
    finally:
        container.scheduler.stop()
        container.registry.stop_all()


def test_turning_monitoring_off_or_removing_person_stops_it(new_client, container, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file, [0])
    c.put(f"/api/cameras/{cam}/monitor", json={"enabled": True})
    container.scheduler.tick(at(15))
    try:
        c.put(f"/api/cameras/{cam}/recognition", json={"enabled": True, "classes": [41]})   # tirou "Pessoa"
        out = container.scheduler.tick(at(15))
        assert out["held"] == [] and out["errors"] == [(cam, "sem_pessoa")] and out["released"] == [cam]
    finally:
        container.scheduler.stop()
        container.registry.stop_all()


def test_a_dead_pipeline_is_recreated_not_left_as_a_zombie(new_client, container, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file, [0])
    c.put(f"/api/cameras/{cam}/monitor", json={"enabled": True})
    container.scheduler.tick(at(15))
    first = container.registry.get(cam)
    try:
        assert first.ready.wait(10) and first.alive
        first.stop_event.set()                                               # simula a thread morrendo
        first._wake.set()
        assert wait(lambda: not first.alive)
        container.scheduler.tick(at(15))
        second = container.registry.get(cam)
        assert second is not first and second.alive and second.monitor
    finally:
        container.scheduler.stop()
        container.registry.stop_all()


def test_one_broken_camera_does_not_block_the_others(new_client, container, video_file):
    c = new_client("ana")
    container.registry._cfg = replace(container.settings, max_cameras=1)     # só cabe uma câmera: a segunda estoura o teto
    good = make_cam(c, video_file, [0])
    bad = c.post("/api/cameras/rtsp", json={"host": "192.168.1.9", "username": "u", "password": "p"}).json()["camera"]["id"]
    c.put(f"/api/cameras/{bad}/recognition", json={"enabled": True, "classes": [0]})
    try:
        c.put(f"/api/cameras/{good}/monitor", json={"enabled": True})        # (o PUT já dispara uma passada do agendador)
        c.put(f"/api/cameras/{bad}/monitor", json={"enabled": True})         # esta não cabe, e o PUT ainda assim responde 200
        out = container.scheduler.tick(at(15))
        assert out["held"] == [good]                                         # a boa segue de pé
        assert [cid for cid, _ in out["errors"]] == [bad]                    # a outra fica registrada com o motivo
    finally:
        container.scheduler.stop()
        container.registry.stop_all()


# ── ritmo dinâmico: devagar sem vídeo, cheio com vídeo ────────────────────────────────────────
def test_pace_is_slow_without_video_and_full_with_video(settings, video_file):
    det = FakeDetector()
    cfg = replace(settings, max_fps=30.0, monitor_fps=2.0)
    c = build_container(cfg, device_lister=lambda: [], detector=det)
    hub = c.registry.hold(1, 10, lambda: str(video_file))
    loop = asyncio.new_event_loop()
    try:
        assert hub.ready.wait(10)
        t0, n0 = time.time(), det.calls
        time.sleep(2.0)
        slow = (det.calls - n0) / (time.time() - t0)
        assert 0.5 <= slow <= 4.0, f"sem vídeo deveria ficar perto de 2 quadros/s, ficou {slow:.1f}"

        q = hub.subscribe(loop, boxes=False, areas=False)                    # alguém abre o vídeo
        first = loop.run_until_complete(asyncio.wait_for(q.get(), 1.0))      # o JPEG chega rápido (acordou o laço)
        assert first[:2] == b"\xff\xd8"
        t1, n1 = time.time(), det.calls
        time.sleep(1.0)
        fast = (det.calls - n1) / (time.time() - t1)
        assert fast > 10, f"com vídeo deveria subir pro ritmo cheio, ficou {fast:.1f}"

        hub.unsubscribe(q)                                                    # fecha o vídeo: volta a ser devagar
        time.sleep(0.6)                                                       # (deixa o laço perceber)
        t2, n2 = time.time(), det.calls
        time.sleep(2.0)
        assert (det.calls - n2) / (time.time() - t2) < 5
    finally:
        loop.close()
        c.registry.stop_all()


# ── amostragem do histórico ───────────────────────────────────────────────────────────────────
class _Sink:
    def __init__(self):
        self.batches = []

    def __call__(self, batch):
        self.batches.append(batch)


def _hub(settings, video_file, sink, enabled=True, classes=None):
    from atendeio.streaming.registry import HubRegistry
    reg = HubRegistry(settings, FakeDetector(), flow_sink=sink)
    return reg, reg.hold(1, 10, lambda: str(video_file), (), enabled, classes)


def test_hub_samples_one_per_second_and_flushes_batches(settings, video_file):
    sink = _Sink()
    reg, hub = _hub(settings, video_file, sink, classes=frozenset({0}))
    try:
        assert wait(lambda: len(sink.batches) >= 1, 8)                       # flow_flush_s = 0.4 nos testes
        total = sum(v[0] for b in sink.batches for v in b["hour"].values())
        assert total >= 1
        row = next(iter(sink.batches[0]["hour"].values()))
        assert row[1] == row[0] * 1 and row[2] == 1                          # o detector falso sempre vê 1 pessoa
    finally:
        reg.stop_all()
    assert sum(v[0] for b in sink.batches for v in b["minute"].values()) >= 1


def test_stopping_the_hub_flushes_what_was_still_in_memory(settings, video_file):
    sink = _Sink()
    reg, hub = _hub(replace_(settings, flow_flush_s=999), video_file, sink, classes=frozenset({0}))   # nunca "vence"
    assert wait(lambda: hub._flow._hour, 8)
    assert sink.batches == []                                                # ainda só em memória
    reg.stop_all()
    assert len(sink.batches) == 1 and sink.batches[0]["camera_id"] == 1      # parar entrega o que sobrou


def replace_(s, **kw):
    return replace(s, **kw)


def test_no_samples_when_person_is_not_recognized_so_gaps_never_look_like_empty(settings, video_file):
    for enabled, classes in ((True, frozenset({41})), (False, frozenset({0})), (True, frozenset())):
        sink = _Sink()
        reg, hub = _hub(settings, video_file, sink, enabled, classes)
        try:
            assert hub.ready.wait(10)
            time.sleep(1.3)
            assert not hub._flow._hour and sink.batches == [], (enabled, classes)   # sem medida = sem linha (lacuna)
        finally:
            reg.stop_all()
