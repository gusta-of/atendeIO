"""Chave geral + escolha de objetos por câmera (padrão: nada marcado)."""

import time

from atendeio.vision import classes as coco

SQ = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]


def make_camera(client, video_file):
    return client.post("/api/cameras/local", json={"ref": str(video_file)}).json()["camera"]["id"]


def owner_and_cam(container, client, cam):
    uid = container.auth.user_for_token(client.cookies.get("atendeio_session"))["id"]
    return uid, container.cameras.get_owned(cam, uid)


def test_catalog_has_every_yolo_class_once(new_client):
    c = new_client("ana")
    data = c.get("/api/recognition/classes").json()
    ids = [x["id"] for x in data["classes"]]
    assert sorted(ids) == list(range(80)) and len(set(ids)) == 80
    assert {x["name"] for x in data["classes"]} >= {"person", "cup", "laptop", "dining table"}
    assert all(x["label"] and x["group"] for x in data["classes"])
    preset = data["presets"][0]
    assert 0 in preset["classes"] and coco.ids_for(["cup"])[0] in preset["classes"]


def test_catalog_requires_login(new_client):
    assert new_client().get("/api/recognition/classes").status_code == 401


def test_new_camera_starts_with_nothing_selected(new_client, video_file):
    c = new_client("ana")
    cam = make_camera(c, video_file)
    assert c.get(f"/api/cameras/{cam}/recognition").json() == {"enabled": True, "classes": []}


def test_save_dedupes_validates_and_persists(new_client, video_file):
    c = new_client("ana")
    cam = make_camera(c, video_file)
    ok = c.put(f"/api/cameras/{cam}/recognition", json={"enabled": False, "classes": [41, 0, 41, 63]})
    assert ok.json() == {"enabled": False, "classes": [0, 41, 63]}
    assert c.get(f"/api/cameras/{cam}/recognition").json() == {"enabled": False, "classes": [0, 41, 63]}
    for bad in ([80], [-1], [0.5], ["person"], [True], list(range(81))):
        assert c.put(f"/api/cameras/{cam}/recognition", json={"enabled": True, "classes": bad}).status_code in (400, 422), bad
    assert c.get(f"/api/cameras/{cam}/recognition").json()["classes"] == [0, 41, 63]   # nada mudou


def test_recognition_is_isolated_between_users(new_client, video_file):
    alice, bob = new_client("alice"), new_client("bob")
    cam = make_camera(alice, video_file)
    assert bob.get(f"/api/cameras/{cam}/recognition").status_code == 404
    assert bob.put(f"/api/cameras/{cam}/recognition", json={"enabled": False, "classes": [0]}).status_code == 404
    assert alice.get(f"/api/cameras/{cam}/recognition").json()["enabled"] is True


def test_old_database_gets_recognition_columns(tmp_path):
    import sqlite3
    from atendeio.db import Database
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, pw_hash TEXT, created REAL);
        CREATE TABLE cameras (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, kind TEXT, ref TEXT, secret BLOB, created REAL);
        INSERT INTO cameras VALUES (1, 1, 'Sala', 'local', '/dev/x', NULL, 0);
    """)
    old.commit(); old.close()
    Database(path).init()
    row = sqlite3.connect(path).execute("SELECT recognition, classes FROM cameras").fetchone()
    assert row == (1, "[]")


def _run_hub(container, client, cam, seconds=0.5):
    uid, owned = owner_and_cam(container, client, cam)
    from atendeio.services.recognition import parse
    enabled, classes = parse(owned)
    return container.registry.acquire(cam, uid, lambda: container.cameras.source_for(owned), (), enabled, classes)


def test_nothing_selected_means_the_model_never_runs(new_client, container, video_file):
    c = new_client("ana")
    cam = make_camera(c, video_file)
    hub = _run_hub(container, c, cam)
    try:
        assert hub.ready.wait(10)
        time.sleep(0.4)
        st = c.get("/api/states").json()["states"][str(cam)]
        assert st["total"] == 0 and st["people"] == 0
        assert st["recognition"] == {"enabled": True, "classes": 0, "person": False}
        assert container.detector.calls == 0          # sem objetos marcados, o YOLO nem é chamado
    finally:
        container.registry.release(hub)
        container.registry.stop_all()


def test_only_selected_classes_are_requested_and_changes_apply_live(new_client, container, video_file):
    c = new_client("ana")
    cam = make_camera(c, video_file)
    c.put(f"/api/cameras/{cam}/recognition", json={"enabled": True, "classes": [0]})
    hub = _run_hub(container, c, cam)
    try:
        assert hub.ready.wait(10)
        deadline = time.time() + 5
        while time.time() < deadline and c.get("/api/states").json()["states"][str(cam)]["people"] != 1:
            time.sleep(0.05)
        assert c.get("/api/states").json()["states"][str(cam)]["people"] == 1
        assert container.detector.last_classes == frozenset({0})   # o filtro chega ao detector
        assert c.get("/api/states").json()["states"][str(cam)]["recognition"]["person"] is True

        # desligar na hora: pára de reconhecer, não inventa "0 pessoas" e as mesas somem do estado
        c.put(f"/api/cameras/{cam}/recognition", json={"enabled": False, "classes": [0]})
        calls = container.detector.calls
        time.sleep(0.5)
        st = c.get("/api/states").json()["states"][str(cam)]
        assert st["people"] is None and st["areas"] == [] and st["recognition"]["enabled"] is False
        assert container.detector.calls <= calls + 1             # o modelo parou de rodar
        # religar volta a contar
        c.put(f"/api/cameras/{cam}/recognition", json={"enabled": True, "classes": [0]})
        deadline = time.time() + 5
        while time.time() < deadline and c.get("/api/states").json()["states"][str(cam)]["people"] != 1:
            time.sleep(0.05)
        assert c.get("/api/states").json()["states"][str(cam)]["people"] == 1
    finally:
        container.registry.release(hub)
        container.registry.stop_all()
