"""Envio de eventos à cloud: contrato, outbox, configuração, retries e API. Sem rede real (exceto o servidor local do último teste)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from atendeio.analytics import cloud_events as ce
from atendeio.analytics.flow import FlowAggregator
from atendeio.errors import ValidationError
from atendeio.repositories.cloud import OutboxRepository
from atendeio.services.cloud import normalize_url
from atendeio.streaming.events import EventBus
from atendeio.streaming.uploader import CloudExporter, http_post

SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "schemas" / "atendeio-event-1.json").read_text("utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
DEVICE = "6f1c2a52-3a42-4b8e-9d27-0d7d1f5d9a10"
CAM = {"id": 1, "name": "Sala"}


def change(name, data, ts_ms=1_700_000_000_000):
    return {"seq": 1, "ts": ts_ms, "time": "x", "camera": 1, "type": "change", "event": name, "data": data}


STATUS = change("area.status", {"id": 7, "name": "Mesa 1", "kind": "mesa", "from": "livre", "to": "ocupada", "people": 2})


def valid(env):
    errors = sorted(VALIDATOR.iter_errors(env), key=lambda e: list(e.path))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]


# ── contrato ─────────────────────────────────────────────────────────────────────────────────

def test_every_exported_event_type_matches_the_json_schema():
    events = [
        ce.from_change(DEVICE, CAM, STATUS),
        ce.from_change(DEVICE, CAM, change("area.status", {"id": 7, "name": "Mesa 1", "kind": "mesa", "from": None,
                                                           "to": "livre", "people": 0})),
        ce.from_change(DEVICE, CAM, change("area.cleaned", {"id": 7, "name": "Mesa 1"})),
        ce.from_change(DEVICE, CAM, change("area.people", {"id": 3, "name": "Fila", "kind": "fila", "from": 1, "to": 4})),
        ce.from_change(DEVICE, CAM, change("camera.offline", {"reason": "perdi o frame"})),
        ce.from_change(DEVICE, CAM, change("camera.online", {})),
    ]
    agg = FlowAggregator(1)
    agg.sample(1_700_000_000, 3, [{"id": 7, "name": "Mesa 1", "kind": "mesa", "people": 2}])
    agg.sample(1_700_000_001, 5, [{"id": 7, "name": "Mesa 1", "kind": "mesa", "people": 1}])
    events.append(ce.from_flow_batch(DEVICE, CAM, agg.flush(), 1_700_000_002))
    events.append(ce.snapshot(DEVICE, CAM, {"online": True, "people": 4, "areas": [
        {"id": 7, "name": "Mesa 1", "kind": "mesa", "status": "a_limpar", "people": 0, "seconds": 12.5},
        {"id": 3, "name": "Fila", "kind": "fila", "people": 2}]}, 1_700_000_003))
    assert all(events)
    for env in events:
        valid(env)
    assert len({e["event_id"] for e in events}) == len(events)


def test_events_not_meant_for_the_cloud_are_dropped():
    for name in ("people.changed", "objects.changed", "recognition.changed", "zones.updated", "hub.started"):
        assert ce.from_change(DEVICE, CAM, change(name, {})) is None


def test_a_bad_event_fails_the_schema():
    env = ce.from_change(DEVICE, CAM, STATUS)
    env["data"]["to"] = "explodiu"
    assert list(VALIDATOR.iter_errors(env))


def test_flow_batch_keeps_partial_sums():
    agg = FlowAggregator(1)
    for people in (2, 6, 4):
        agg.sample(1_700_000_000, people)
    env = ce.from_flow_batch(DEVICE, CAM, agg.flush(), 1_700_000_001)
    minute = env["data"]["minutes"][0]
    assert (minute["samples"], minute["people_sum"], minute["people_max"], minute["people_min"]) == (3, 12, 6, 2)


def test_event_bus_tap_only_sees_change_events_and_never_breaks_the_camera():
    seen = []
    bus = EventBus(1, tap=seen.append)
    bus.emit("change", "area.status", {"x": 1})
    bus.emit("snapshot", "state", {"x": 2})
    bus.emit("frame", "frame", {"x": 3})
    assert [e["event"] for e in seen] == ["area.status"]

    def boom(_ev):
        raise RuntimeError("cloud caiu")

    broken = EventBus(1, tap=boom)
    assert broken.emit("change", "area.status", {})["seq"] == 1   # a câmera segue


# ── endereço ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("https://api.exemplo.pt", "https://api.exemplo.pt"),
    ("https://api.exemplo.pt/", "https://api.exemplo.pt"),
    ("  https://api.exemplo.pt/base/  ", "https://api.exemplo.pt/base"),
    ("http://127.0.0.1:9000", "http://127.0.0.1:9000"),
    ("http://localhost:9000", "http://localhost:9000"),
])
def test_valid_urls(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "api.exemplo.pt", "ftp://api.exemplo.pt", "http://api.exemplo.pt",
    "http://192.168.1.10", "https://user:senha@api.exemplo.pt", "https://api.exemplo.pt/?a=1", "https://x.pt/#frag",
    "https://" + "a" * 300 + ".pt",
])
def test_invalid_urls(raw):
    with pytest.raises(ValidationError):
        normalize_url(raw)


# ── configuração ─────────────────────────────────────────────────────────────────────────────

def test_config_never_returns_the_key_and_keeps_it_when_not_resent(container):
    cloud = container.cloud
    assert cloud.public()["enabled"] is False and cloud.credentials() is None
    device = cloud.public()["device_id"]
    pub = cloud.update(True, "https://api.exemplo.pt", "chave-do-dispositivo")
    assert pub == {"enabled": True, "url": "https://api.exemplo.pt", "key_set": True, "device_id": device}
    assert "chave-do-dispositivo" not in json.dumps(pub)
    assert cloud.credentials() == {"url": "https://api.exemplo.pt", "key": "chave-do-dispositivo", "device_id": device}
    cloud.update(True, "https://outra.exemplo.pt")              # sem chave: mantém a guardada
    assert cloud.credentials()["key"] == "chave-do-dispositivo"
    cloud.update(False, "https://outra.exemplo.pt")
    assert cloud.credentials() is None                          # desligado = sem credenciais


def test_key_is_encrypted_at_rest(container):
    container.cloud.update(True, "https://api.exemplo.pt", "chave-do-dispositivo")
    with container.db.connect() as c:
        stored = c.execute("SELECT api_key FROM cloud_config").fetchone()[0]
    assert b"chave-do-dispositivo" not in stored


def test_enabling_requires_url_and_key(container):
    with pytest.raises(ValidationError):
        container.cloud.update(True, "https://api.exemplo.pt")            # sem chave
    with pytest.raises(ValidationError):
        container.cloud.update(True, "", "chave")                          # sem endereço
    with pytest.raises(ValidationError):
        container.cloud.update(False, "https://api.exemplo.pt", "   ")    # chave vazia


# ── outbox ───────────────────────────────────────────────────────────────────────────────────

def test_outbox_is_ordered_deduplicated_and_trimmed(container):
    box = OutboxRepository(container.db)
    assert box.add_many([("a", "{}"), ("b", "{}"), ("a", "{}")]) == 2     # "a" repetido é ignorado
    assert [r["event_id"] for r in box.pending(10)] == ["a", "b"]
    box.add_many([(f"e{i}", "{}") for i in range(5)])
    assert box.trim(max_pending=3, rejected_older_than_s=3600) == 4        # ficam os 3 mais recentes
    assert [r["event_id"] for r in box.pending(10)] == ["e2", "e3", "e4"]
    box.reject([box.pending(1)[0]["id"]])
    assert box.counts() == {"pending": 2, "rejected": 1}


# ── exportador ───────────────────────────────────────────────────────────────────────────────

class Clock:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class FakePost:
    """Respostas na ordem; sem mais respostas = 200. Um item pode ser int, exceção ou função(body) -> int."""
    def __init__(self):
        self.calls, self.responses = [], []

    def __call__(self, url, key, body, timeout):
        parsed = json.loads(body)
        self.calls.append({"url": url, "key": key, "body": parsed})
        r = self.responses.pop(0) if self.responses else 200
        if isinstance(r, Exception):
            raise r
        return r(parsed) if callable(r) else r


@pytest.fixture
def rig(container):
    container.cloud.update(True, "https://cloud.test", "chave-secreta")
    clock, post = Clock(), FakePost()
    outbox = OutboxRepository(container.db)
    exporter = CloudExporter(container.cloud, outbox, lambda cam, owner: {"id": cam, "name": "Sala"},
                             lambda: [], container.settings, clock=clock, post=post)
    exporter.refresh()
    return exporter, post, clock, outbox


def test_a_change_event_reaches_the_cloud_and_leaves_the_outbox(rig):
    exporter, post, clock, outbox = rig
    exporter.submit("change", 1, 1, STATUS)
    exporter.run_once()
    assert len(post.calls) == 1
    call = post.calls[0]
    assert call["url"] == "https://cloud.test/v1/events" and call["key"] == "chave-secreta"
    assert call["body"]["device_id"] == exporter._creds["device_id"]
    [event] = call["body"]["events"]
    valid(event)
    assert event["type"] == "table.status_changed" and event["camera"] == {"id": 1, "name": "Sala"}
    assert event["data"] == {"zone_id": 7, "name": "Mesa 1", "from": "livre", "to": "ocupada", "people": 2}
    assert outbox.counts() == {"pending": 0, "rejected": 0}
    assert exporter.state == "ok" and exporter.sent == 1 and exporter.last_error is None


def test_internet_down_keeps_events_and_retries_with_backoff(rig):
    exporter, post, clock, outbox = rig
    exporter.submit("change", 1, 1, STATUS)
    post.responses = [OSError("sem rede")]
    exporter.run_once()
    assert exporter.state == "retrying" and outbox.counts()["pending"] == 1
    clock.advance(1)
    exporter.run_once()
    assert len(post.calls) == 1                       # ainda dentro da espera de 5 s
    clock.advance(10)
    exporter.run_once()
    assert len(post.calls) == 2 and outbox.counts()["pending"] == 0 and exporter.state == "ok"


def test_events_survive_a_restart(container):
    """O que está na outbox é reenviado por um exportador novo (o PC reiniciou)."""
    container.cloud.update(True, "https://cloud.test", "chave")
    outbox = OutboxRepository(container.db)
    clock = Clock()
    first = CloudExporter(container.cloud, outbox, lambda c, o: {"id": c, "name": "Sala"}, lambda: [],
                          container.settings, clock=clock, post=FakePost())
    first.refresh()
    first.submit("change", 1, 1, STATUS)
    first._post = FakePost()
    first._post.responses = [503]
    first.run_once()
    assert outbox.counts()["pending"] == 1
    post = FakePost()
    second = CloudExporter(container.cloud, outbox, lambda c, o: {"id": c, "name": "Sala"}, lambda: [],
                           container.settings, clock=clock, post=post)
    second.refresh()
    second.run_once()
    assert len(post.calls[0]["body"]["events"]) == 1 and outbox.counts()["pending"] == 0


def test_rejected_key_waits_five_minutes_and_keeps_the_events(rig):
    exporter, post, clock, outbox = rig
    exporter.submit("change", 1, 1, STATUS)
    post.responses = [401]
    exporter.run_once()
    assert exporter.state == "auth_failed" and "chave" in exporter.last_error and outbox.counts()["pending"] == 1
    clock.advance(100)
    exporter.run_once()
    assert len(post.calls) == 1
    clock.advance(250)
    exporter.run_once()
    assert len(post.calls) == 2 and exporter.state == "ok" and outbox.counts()["pending"] == 0


def test_one_bad_event_does_not_block_the_good_ones(rig):
    exporter, post, clock, outbox = rig
    names = ["Mesa 1", "Veneno", "Mesa 3"]
    for i, name in enumerate(names):
        exporter.submit("change", 1, 1, change("area.status", {"id": i, "name": name, "kind": "mesa",
                                                               "from": "livre", "to": "ocupada", "people": 1}))
    post.responses = [lambda b: 422 if any(e["data"]["name"] == "Veneno" for e in b["events"]) else 200] * 10
    for _ in range(8):
        exporter.run_once()
    delivered = [e["data"]["name"] for c in post.calls if c["body"]["events"] and not
                 any(e["data"]["name"] == "Veneno" for e in c["body"]["events"]) for e in c["body"]["events"]]
    assert sorted(delivered) == ["Mesa 1", "Mesa 3"]
    assert outbox.counts() == {"pending": 0, "rejected": 1}


def test_disabled_exporter_queues_nothing_and_sends_nothing(container):
    outbox = OutboxRepository(container.db)
    post = FakePost()
    exporter = CloudExporter(container.cloud, outbox, lambda c, o: {"id": c, "name": "Sala"}, lambda: [],
                             container.settings, clock=Clock(), post=post)
    exporter.refresh()
    exporter.submit("change", 1, 1, STATUS)
    exporter.run_once()
    assert post.calls == [] and outbox.counts() == {"pending": 0, "rejected": 0} and exporter.state == "off"


def test_removed_camera_events_are_skipped(container):
    container.cloud.update(True, "https://cloud.test", "chave")
    post = FakePost()
    exporter = CloudExporter(container.cloud, OutboxRepository(container.db), lambda c, o: None, lambda: [],
                             container.settings, clock=Clock(), post=post)
    exporter.refresh()
    exporter.submit("change", 99, 1, STATUS)
    exporter.run_once()
    assert post.calls == []


def test_periodic_snapshot_is_sent_with_every_live_camera(container):
    container.cloud.update(True, "https://cloud.test", "chave")
    clock, post = Clock(), FakePost()
    states = [(1, 1, {"online": True, "people": 2, "areas": [
        {"id": 7, "name": "Mesa 1", "kind": "mesa", "status": "ocupada", "people": 2, "seconds": 30.0}]})]
    exporter = CloudExporter(container.cloud, OutboxRepository(container.db), lambda c, o: {"id": c, "name": "Sala"},
                             lambda: states, container.settings, clock=clock, post=post)
    exporter.refresh()
    exporter.run_once()
    [event] = post.calls[0]["body"]["events"]
    valid(event)
    assert event["type"] == "state.snapshot" and event["data"]["areas"][0]["status"] == "ocupada"
    clock.advance(60)
    exporter.run_once()
    assert len(post.calls) == 1                       # próximo só daqui a cloud_snapshot_every_s
    clock.advance(container.settings.cloud_snapshot_every_s)
    exporter.run_once()
    assert len(post.calls) == 2


def test_full_queue_drops_the_oldest_and_never_blocks(container):
    container.cloud.update(True, "https://cloud.test", "chave")
    exporter = CloudExporter(container.cloud, OutboxRepository(container.db), lambda c, o: {"id": c, "name": "Sala"},
                             lambda: [], container.settings, clock=Clock(), post=FakePost(), queue_max=3)
    exporter.refresh()
    for i in range(10):
        exporter.submit("change", 1, 1, change("area.cleaned", {"id": i, "name": f"M{i}"}))
    assert exporter.dropped == 7


# ── HTTP real (servidor local) ───────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/redirect/v1/events":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/roubar-chave")
            self.end_headers()
            return
        _Handler.received.append((self.path, self.headers["Authorization"], json.loads(body)))
        self.send_response(202)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    _Handler.received = []
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_real_http_post_sends_the_bearer_key_and_does_not_follow_redirects(local_server):
    assert http_post(local_server + "/v1/events", "chave-1", b'{"events":[]}', 5) == 202
    assert _Handler.received[0][:2] == ("/v1/events", "Bearer chave-1")
    assert http_post(local_server + "/redirect/v1/events", "chave-1", b"{}", 5) == 302


def test_end_to_end_with_a_real_local_server(container, local_server):
    container.cloud.update(True, local_server, "chave-e2e")
    outbox = OutboxRepository(container.db)
    exporter = CloudExporter(container.cloud, outbox, lambda c, o: {"id": c, "name": "Sala"}, lambda: [],
                             container.settings)
    exporter.refresh()
    exporter.submit("change", 1, 1, STATUS)
    exporter.run_once()
    path, auth, body = _Handler.received[0]
    assert (path, auth) == ("/v1/events", "Bearer chave-e2e")
    valid(body["events"][0])
    assert outbox.counts()["pending"] == 0


# ── API ──────────────────────────────────────────────────────────────────────────────────────

def test_cloud_api_requires_login(new_client):
    anon = new_client()
    assert anon.get("/api/cloud").status_code == 401
    assert anon.put("/api/cloud", json={"enabled": False}).status_code == 401


def test_cloud_api_validates_saves_and_hides_the_key(new_client):
    alice = new_client("alice")
    assert alice.get("/api/cloud").json()["enabled"] is False
    assert alice.put("/api/cloud", json={"enabled": True, "url": "http://api.exemplo.pt", "api_key": "k"}).status_code == 400
    assert alice.put("/api/cloud", json={"enabled": True, "url": "https://api.exemplo.pt"}).status_code == 400
    r = alice.put("/api/cloud", json={"enabled": True, "url": "https://api.exemplo.pt", "api_key": "chave-secreta"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] and body["key_set"] and body["status"]["state"] == "ok"
    assert "chave-secreta" not in r.text and "chave-secreta" not in alice.get("/api/cloud").text
    r = alice.put("/api/cloud", json={"enabled": False, "url": "https://api.exemplo.pt"})
    assert r.json()["enabled"] is False and r.json()["key_set"] is True and r.json()["status"]["state"] == "off"


# ── ligação real: hub ao vivo → exportador ───────────────────────────────────────────────────

def test_live_hub_events_reach_the_cloud(settings, video_file):
    """A câmera ao vivo (hub real, detector falso) alimenta o exportador: mesa ocupada, fluxo e retrato."""
    import time
    from fastapi.testclient import TestClient
    from atendeio.api.app import create_app
    from atendeio.container import build_container
    from tests.conftest import FakeDetector

    post = FakePost()
    container = build_container(settings, device_lister=lambda: [{"ref": str(video_file), "name": "Teste"}],
                                detector=FakeDetector(), cloud_post=post)
    container.cloud.update(True, "https://cloud.test", "chave-live")
    container.exporter.refresh()
    client = TestClient(create_app(container=container), base_url="http://testserver")
    assert client.post("/api/auth/register", json={"username": "ana", "password": "senha-segura-123"}).status_code == 200
    cam = client.post("/api/cameras/local", json={"ref": str(video_file), "name": "Sala"}).json()["camera"]["id"]
    sq = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
    client.put(f"/api/cameras/{cam}/zones", json={"zones": [{"name": "Mesa 1", "kind": "mesa", "points": sq}]})
    user_id = container.auth.user_for_token(client.cookies.get("atendeio_session"))["id"]
    owned = container.cameras.get_owned(cam, user_id)
    hub = container.registry.acquire(cam, user_id, lambda: container.cameras.source_for(owned),
                                     container.zones.load(cam))
    try:
        assert hub.ready.wait(10)
        seen, deadline = {}, time.time() + 8
        while time.time() < deadline and not {"table.status_changed", "flow.batch", "state.snapshot"} <= set(seen):
            container.exporter.run_once()
            for call in post.calls:
                for event in call["body"]["events"]:
                    seen.setdefault(event["type"], event)
            time.sleep(0.2)
    finally:
        container.registry.release(hub)
        container.registry.stop_all()

    assert {"table.status_changed", "flow.batch", "state.snapshot"} <= set(seen), sorted(seen)
    for event in seen.values():
        valid(event)
    status = [e for c in post.calls for e in c["body"]["events"] if e["type"] == "table.status_changed"]
    assert any(e["data"]["to"] == "ocupada" and e["data"]["name"] == "Mesa 1" for e in status)
    assert all(e["camera"] == {"id": cam, "name": "Sala"} for e in seen.values())
    assert all(c["key"] == "chave-live" for c in post.calls)
