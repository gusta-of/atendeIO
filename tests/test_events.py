"""Telemetria em JSON em tempo real: barramento, diffs, hub, SSE e isolamento."""

import asyncio
import json
import time

import pytest

from atendeio.analytics.zones import Zone
from atendeio.streaming import sse
from atendeio.streaming.events import (EventBus, counts_of, diff_counts, diff_states, frame_of, iso,
                                       snapshot_of)


# ── diffs (puros) ─────────────────────────────────────────────────────────────────────────────
def st(people=0, areas=(), counts=()):
    return {"people": people, "areas": list(areas), "counts": [{"name": n, "count": c} for n, c in counts]}


def area(i, status="livre", people=0, name="Mesa 1", kind="mesa"):
    return {"id": i, "name": name, "kind": kind, "status": status, "people": people}


def test_no_events_on_first_state_or_when_nothing_changed():
    assert diff_states(None, st(3)) == []
    a = st(2, [area(1)])
    assert diff_states(a, st(2, [area(1)])) == []


def test_people_and_table_changes_are_reported_with_before_and_after():
    prev = st(1, [area(1, "livre", 0)])
    cur = st(2, [area(1, "ocupada", 2)])
    ev = dict(diff_states(prev, cur))
    assert ev["people.changed"] == {"from": 1, "to": 2}
    assert ev["area.status"]["from"] == "livre" and ev["area.status"]["to"] == "ocupada"
    assert ev["area.status"]["name"] == "Mesa 1" and ev["area.status"]["people"] == 2


def test_people_count_change_inside_an_area_without_status_change():
    ev = dict(diff_states(st(1, [area(1, "ocupada", 1)]), st(1, [area(1, "ocupada", 2)])))
    assert ev == {"area.people": {"id": 1, "name": "Mesa 1", "kind": "mesa", "from": 1, "to": 2}}


def test_a_new_area_announces_its_initial_status_with_null_from():
    ev = diff_states(st(0, [area(1)]), st(0, [area(1), area(2, "ocupada", 1, name="Mesa 2")]))
    assert ev == [("area.status", {"id": 2, "name": "Mesa 2", "kind": "mesa", "from": None, "to": "ocupada", "people": 1})]
    first = diff_states(None, st(1, [area(1, "livre")]))          # o log começa com o status de cada mesa
    assert first == [("area.status", {"id": 1, "name": "Mesa 1", "kind": "mesa", "from": None, "to": "livre", "people": 0})]


def test_object_count_changes():
    assert diff_counts(None, {"cup": 1}) == []
    assert diff_counts({"cup": 1, "bottle": 0}, {"cup": 1, "bottle": 2, "laptop": 1}) == [
        ("objects.changed", {"class": "bottle", "from": 0, "to": 2}),
        ("objects.changed", {"class": "laptop", "from": 0, "to": 1})]
    assert diff_counts({"cup": 2}, {}) == [("objects.changed", {"class": "cup", "from": 2, "to": 0})]


def test_snapshot_and_frame_payloads_are_plain_json():
    state = {**st(1, [area(1, "ocupada", 1)], [("person", 1)]), "recognition": {"enabled": True}, "size": [640, 480]}
    snap = snapshot_of(state, 14.96, 2, True)
    assert snap["fps"] == 15.0 and snap["objects"] == {"person": 1} and snap["areas"][0]["status"] == "ocupada"
    dets = [{"name": "person", "conf": 0.9137, "box": (0.4, 0.3, 0.6, 0.7), "poly": [(0, 0)]}]
    frame = frame_of(dets, state, 14.96)
    assert frame["detections"] == [{"class": "person", "conf": 0.91, "box": [0.4, 0.3, 0.6, 0.7]}]
    json.dumps(snap), json.dumps(frame)  # tudo serializável


# ── barramento ────────────────────────────────────────────────────────────────────────────────
def test_envelope_has_seq_timestamps_and_camera():
    bus = EventBus(7, clock=lambda: 1_793_093_698.117)
    ev = bus.emit("change", "people.changed", {"from": 0, "to": 1})
    assert ev["seq"] == 1 and ev["camera"] == 7 and ev["type"] == "change" and ev["event"] == "people.changed"
    assert ev["ts"] == 1_793_093_698_117 and ev["time"] == iso(ev["ts"]) and ev["time"].endswith("Z")


def test_ring_buffer_keeps_only_the_latest_and_backlog_respects_since():
    bus = EventBus(1, history=5)
    for i in range(8):
        bus.emit("change", "x", {"i": i})
    loop = asyncio.new_event_loop()
    try:
        _, backlog = bus.subscribe(loop)
        assert [e["data"]["i"] for e in backlog] == [3, 4, 5, 6, 7]         # só os últimos 5
        _, resumed = bus.subscribe(loop, since=6)                            # reconexão: só o que perdeu
        assert [e["seq"] for e in resumed] == [7, 8]
        _, none = bus.subscribe(loop, history=False)
        assert none == []
    finally:
        loop.close()


def test_frame_events_exist_only_for_detail_listeners_and_are_never_buffered():
    bus = EventBus(1)
    loop = asyncio.new_event_loop()
    try:
        assert bus.emit("frame", "frame", {}) is None                       # ninguém ouve: nem é montado
        assert not bus.wants_detail()
        plain, _ = bus.subscribe(loop, detail=False)
        assert bus.emit("frame", "frame", {}) is None                       # ouvinte comum não pede quadros
        det, _ = bus.subscribe(loop, detail=True)
        assert bus.wants_detail()
        assert bus.emit("frame", "frame", {"n": 1})["type"] == "frame"
        assert [e for e in bus.recent(10) if e["type"] == "frame"] == []    # nunca vai pro buffer
        bus.unsubscribe(det)
        assert not bus.wants_detail()
    finally:
        loop.close()


def test_slow_listener_drops_oldest_and_counts():
    async def go():
        bus = EventBus(1)
        sub, _ = bus.subscribe(asyncio.get_running_loop())
        for i in range(1500):                         # fila do ouvinte é de 1000
            bus.emit("change", "x", {"i": i})
        await asyncio.sleep(0.2)
        return sub
    sub = asyncio.run(go())
    assert sub.queue.qsize() == 1000 and sub.dropped == 500
    assert sub.queue.get_nowait()["data"]["i"] == 500   # os mais antigos foram os descartados


# ── SSE ───────────────────────────────────────────────────────────────────────────────────────
def test_sse_encoding_is_one_json_line_with_id_and_event():
    ev = {"seq": 9, "ts": 1, "time": "t", "camera": 1, "type": "change", "event": "area.status", "data": {"a": "é"}}
    raw = sse.encode(ev).decode()
    assert raw.startswith("id: 9\nevent: change\ndata: ") and raw.endswith("\n\n")
    data = raw.split("data: ", 1)[1].strip()
    assert "\n" not in data and json.loads(data)["data"] == {"a": "é"}
    assert sse.parse_last_event_id("12") == 12 and sse.parse_last_event_id("x") is None and sse.parse_last_event_id(None) is None


class _FakeHub:
    def __init__(self):
        import threading
        self.stop_event = threading.Event()


def test_sse_stream_sends_backlog_heartbeat_dropped_notice_and_stops_with_the_hub():
    async def go():
        hub, bus = _FakeHub(), EventBus(1)
        bus.emit("change", "hub.started", {})
        sub, backlog = bus.subscribe(asyncio.get_running_loop())
        authorized = {"ok": True}

        async def still():
            return authorized["ok"]

        out = []
        async for chunk in sse.events_stream(hub, sub, backlog, still, recheck_every_s=999, heartbeat_s=0.05):
            out.append(chunk.decode())
            if len(out) == 4:                                  # retry + backlog + 2 heartbeats
                sub.dropped = 3                                # simula ouvinte que ficou pra trás
            if any("events.dropped" in c for c in out):
                hub.stop_event.set()                           # câmera removida: o stream termina sozinho
        return out
    out = asyncio.run(go())
    assert out[0] == "retry: 3000\n\n"
    assert out[1].startswith("id: 1\nevent: change") and "hub.started" in out[1]
    assert ": ping\n\n" in out
    dropped = next(c for c in out if "events.dropped" in c)
    assert '"count":3' in dropped and "id:" not in dropped    # aviso do canal: sem id (não entra no buffer)


def test_sse_stream_stops_when_the_session_is_no_longer_valid():
    async def go():
        hub, bus = _FakeHub(), EventBus(1)
        sub, backlog = bus.subscribe(asyncio.get_running_loop())

        async def revoked():
            return False

        n = 0
        async for _ in sse.events_stream(hub, sub, backlog, revoked, recheck_every_s=0.0, heartbeat_s=0.05):
            n += 1
        return n
    assert asyncio.run(asyncio.wait_for(go(), 5)) <= 3        # encerra por conta própria (logout corta a telemetria)


# ── hub de verdade (câmera de teste + detector falso) ─────────────────────────────────────────
def _wait(cond, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_hub_emits_connection_snapshot_and_changes(container, video_file):
    zone = Zone(1, "Mesa 1", "mesa", ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)), 0.0)
    hub = container.registry.acquire(1, 10, lambda: str(video_file), (zone,))
    try:
        assert hub.ready.wait(10)
        names = lambda: [(e["type"], e["event"]) for e in hub.events.recent(200)]
        assert _wait(lambda: ("snapshot", "state") in names())
        assert ("change", "hub.started") in names() and ("change", "camera.online") in names()
        assert _wait(lambda: ("change", "area.status") in names())           # o detector falso põe gente na mesa
        status = next(e for e in hub.events.recent(200) if e["event"] == "area.status")
        assert status["data"]["to"] == "ocupada" and status["data"]["name"] == "Mesa 1" and status["data"]["from"] is None
        snap = next(e for e in reversed(hub.events.recent(200)) if e["type"] == "snapshot")
        assert snap["data"]["people"] == 1 and snap["data"]["objects"] == {"person": 1}
        assert snap["data"]["areas"][0]["status"] == "ocupada"
    finally:
        container.registry.release(hub)
        container.registry.stop_all()


def test_hub_announces_config_changes_and_manual_cleaning(container, video_file):
    zone = Zone(1, "Mesa 1", "mesa", ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)))
    hub = container.registry.acquire(1, 10, lambda: str(video_file), (zone,))
    try:
        assert hub.ready.wait(10)
        hub.set_recognition(True, frozenset({0, 41}))
        hub.set_zones([zone])
        hub.mark_clean(1)
        got = {e["event"]: e["data"] for e in hub.events.recent(200)}
        assert got["recognition.changed"] == {"enabled": True, "classes": [0, 41], "count": 2}
        assert got["zones.updated"] == {"count": 1}
        assert got["area.cleaned"] == {"id": 1, "name": "Mesa 1"}
    finally:
        container.registry.release(hub)
        container.registry.stop_all()


def test_hub_builds_frame_detail_only_while_a_detail_listener_exists(container, video_file):
    hub = container.registry.acquire(1, 10, lambda: str(video_file))
    loop = asyncio.new_event_loop()
    try:
        assert hub.ready.wait(10)
        time.sleep(0.3)
        assert hub.events.wants_detail() is False
        sub, _ = hub.events.subscribe(loop, detail=True)
        assert _wait(lambda: hub.events.wants_detail())
        got = []

        async def drain():
            for _ in range(3):
                got.append(await asyncio.wait_for(sub.queue.get(), 5))
        loop.run_until_complete(drain())
        frames = [e for e in got if e["type"] == "frame"]
        assert frames and frames[0]["data"]["detections"][0]["class"] == "person"
        assert frames[0]["data"]["size"] == [320, 240]
    finally:
        loop.close()
        container.registry.release(hub)
        container.registry.stop_all()


# ── API: isolamento ───────────────────────────────────────────────────────────────────────────
def test_events_endpoint_requires_login_and_hides_other_users_cameras(new_client, video_file):
    alice, bob, anon = new_client("alice"), new_client("bob"), new_client()
    cam = alice.post("/api/cameras/local", json={"ref": str(video_file)}).json()["camera"]["id"]
    assert anon.get(f"/api/cameras/{cam}/events").status_code == 401
    assert bob.get(f"/api/cameras/{cam}/events").status_code == 404        # câmera alheia = inexistente
    assert bob.get("/api/cameras/999999/events").status_code == 404
