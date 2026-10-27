import time

SQ = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]


def zone(name, kind="mesa", points=SQ, **extra):
    return {"name": name, "kind": kind, "points": points, **extra}


def make_camera(client, video_file):
    return client.post("/api/cameras/local", json={"ref": str(video_file)}).json()["camera"]["id"]


def test_save_list_and_preserve_ids(new_client, video_file):
    c = new_client("ana")
    cam = make_camera(c, video_file)
    saved = c.put(f"/api/cameras/{cam}/zones", json={"zones": [zone("Mesa 1"), zone("Porta", "entrada")]}).json()["zones"]
    assert [z["name"] for z in saved] == ["Mesa 1", "Porta"]
    ids = {z["name"]: z["id"] for z in saved}

    # editar mantém o id; remover some; trocar nomes entre duas zonas não quebra o índice único
    again = c.put(f"/api/cameras/{cam}/zones", json={"zones": [
        zone("Porta", "mesa", id=ids["Mesa 1"]), zone("Mesa 1", "entrada", id=ids["Porta"])]}).json()["zones"]
    assert {z["name"]: z["id"] for z in again} == {"Porta": ids["Mesa 1"], "Mesa 1": ids["Porta"]}
    assert c.get(f"/api/cameras/{cam}/zones").json()["zones"] == again

    c.put(f"/api/cameras/{cam}/zones", json={"zones": []})
    assert c.get(f"/api/cameras/{cam}/zones").json()["zones"] == []


def test_validation(new_client, video_file):
    c = new_client("ana")
    cam = make_camera(c, video_file)

    def put(*zs):
        return c.put(f"/api/cameras/{cam}/zones", json={"zones": list(zs)})

    assert put(zone("")).status_code == 400                                   # sem nome
    assert put(zone("X", kind="cozinha")).status_code == 400                  # tipo inválido
    assert put(zone("X", points=[[0, 0], [1, 1]])).status_code == 400         # poucos pontos
    assert put(zone("X", points=[[0, 0], [2, 0], [1, 1]])).status_code == 400  # fora da imagem
    assert put(zone("X", points=[[0, 0], [0.5, 0.5], [1, 1]])).status_code == 400  # sem área
    assert put(zone("X", points=[[0.1, 0.1], [0.11, 0.1], [0.11, 0.11]])).status_code == 400  # minúscula
    assert put(zone("Mesa 1"), zone("mesa 1")).status_code == 400             # nome repetido
    assert put(*[zone(f"M{i}") for i in range(51)]).status_code == 400        # limite
    assert c.get(f"/api/cameras/{cam}/zones").json()["zones"] == []           # nada foi salvo


def test_zones_are_isolated_between_users(new_client, container, video_file):
    alice, bob = new_client("alice"), new_client("bob")
    cam = make_camera(alice, video_file)
    zid = alice.put(f"/api/cameras/{cam}/zones", json={"zones": [zone("Mesa 1")]}).json()["zones"][0]["id"]

    assert bob.get(f"/api/cameras/{cam}/zones").status_code == 404
    assert bob.put(f"/api/cameras/{cam}/zones", json={"zones": []}).status_code == 404
    assert bob.post(f"/api/cameras/{cam}/zones/{zid}/clean").status_code == 404
    assert bob.post(f"/api/cameras/{cam}/flow/reset").status_code in (404, 405)
    assert len(alice.get(f"/api/cameras/{cam}/zones").json()["zones"]) == 1   # intacta


def test_cannot_hijack_zone_id_from_another_camera(new_client, video_file, container):
    alice, bob = new_client("alice"), new_client("bob")
    cam_a = make_camera(alice, video_file)
    zid = alice.put(f"/api/cameras/{cam_a}/zones", json={"zones": [zone("A")]}).json()["zones"][0]["id"]
    cam_b = bob.post("/api/cameras/rtsp", json={"host": "192.168.1.9", "username": "u", "password": "p"}).json()["camera"]["id"]
    # Bob manda o id da zona da Alice na câmera dele: vira zona NOVA, a da Alice não é tocada
    out = bob.put(f"/api/cameras/{cam_b}/zones", json={"zones": [zone("Roubada", id=zid)]}).json()["zones"]
    assert out[0]["id"] != zid
    assert alice.get(f"/api/cameras/{cam_a}/zones").json()["zones"][0]["name"] == "A"


def test_deleting_camera_deletes_its_zones(new_client, container, video_file):
    c = new_client("ana")
    cam = make_camera(c, video_file)
    c.put(f"/api/cameras/{cam}/zones", json={"zones": [zone("Mesa 1")]})
    assert c.delete(f"/api/cameras/{cam}").status_code == 200
    assert container.zones._zones.list_for_camera(cam) == []


def test_live_hub_reports_table_status_and_applies_edits(new_client, container, video_file):
    c = new_client("ana")
    cam = make_camera(c, video_file)
    c.put(f"/api/cameras/{cam}/zones", json={"zones": [zone("Mesa 1")]})
    user_id = container.auth.user_for_token(c.cookies.get("atendeio_session"))["id"]
    owned = container.cameras.get_owned(cam, user_id)
    hub = container.registry.acquire(cam, user_id, lambda: container.cameras.source_for(owned),
                                     container.zones.load(cam))
    try:
        assert hub.ready.wait(10)
        deadline = time.time() + 5
        while time.time() < deadline:                      # fake detector põe 1 pessoa no centro
            area = c.get("/api/states").json()["states"][str(cam)]["areas"]
            if area and area[0]["status"] == "ocupada":
                break
            time.sleep(0.05)
        st = c.get("/api/states").json()["states"][str(cam)]
        assert st["areas"][0]["name"] == "Mesa 1" and st["areas"][0]["status"] == "ocupada"
        assert st["areas"][0]["people"] == 1 and st["size"] == [320, 240]
        assert st["people"] == 1 and "flow" not in st               # pessoas na área da câmera

        c.put(f"/api/cameras/{cam}/zones", json={"zones": []})        # editar aplica sem reiniciar
        time.sleep(0.3)
        assert c.get("/api/states").json()["states"][str(cam)]["areas"] == []
    finally:
        container.registry.release(hub)
        container.registry.stop_all()


def test_shape_and_angle_persist_and_are_validated(new_client, video_file):
    c = new_client("ana")
    cam = make_camera(c, video_file)
    tri = [[0.2, 0.2], [0.4, 0.6], [0.0, 0.6]]
    ok = c.put(f"/api/cameras/{cam}/zones", json={"zones": [
        zone("Canto", points=tri, shape="triangle", angle=30), zone("Livre")]})
    assert ok.status_code == 200
    saved = {z["name"]: z for z in c.get(f"/api/cameras/{cam}/zones").json()["zones"]}
    assert saved["Canto"]["shape"] == "triangle" and saved["Canto"]["angle"] == 30
    assert saved["Livre"]["shape"] == "poly" and saved["Livre"]["angle"] == 0   # padrão p/ clientes antigos
    sq = [[0.2, 0.2], [0.4, 0.2], [0.4, 0.4], [0.2, 0.4]]
    assert c.put(f"/api/cameras/{cam}/zones", json={"zones": [zone("Q", points=sq, shape="square")]}).status_code == 200

    bad = lambda **kw: c.put(f"/api/cameras/{cam}/zones", json={"zones": [zone("X", **kw)]}).status_code
    assert bad(shape="estrela") == 400
    assert bad(angle=99999) == 400
    last = c.get(f"/api/cameras/{cam}/zones").json()["zones"][0]
    assert last["name"] == "Q" and last["shape"] == "square"                          # as inválidas não mudaram nada


def test_old_database_is_migrated_without_losing_zones(tmp_path):
    import json, sqlite3
    from atendeio.db import Database
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, pw_hash TEXT, created REAL);
        CREATE TABLE cameras (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, kind TEXT, ref TEXT, secret BLOB, created REAL);
        CREATE TABLE zones (id INTEGER PRIMARY KEY, camera_id INTEGER, name TEXT, kind TEXT, points TEXT, created REAL);
        INSERT INTO zones VALUES (1, 1, 'Mesa 1', 'mesa', '[[0.1,0.1],[0.5,0.1],[0.5,0.5]]', 0);
    """)
    old.commit(); old.close()
    db = Database(path)
    db.init()
    from atendeio.repositories.zones import ZoneRepository
    z = ZoneRepository(db).list_for_camera(1)[0]
    assert z["name"] == "Mesa 1" and z["shape"] == "poly" and z["angle"] == 0


def test_table_seat_margin_has_a_default_persists_and_is_validated(new_client, video_file):
    c = new_client("ana")
    cam = make_camera(c, video_file)
    put = lambda *zs: c.put(f"/api/cameras/{cam}/zones", json={"zones": list(zs)})
    r = put(zone("Mesa 1"), zone("Porta", "entrada"), zone("Mesa 2", margin=0.15)).json()["zones"]
    by = {z["name"]: z for z in r}
    assert by["Mesa 1"]["margin"] == 0.06            # mesa sem margem informada: padrão
    assert by["Porta"]["margin"] == 0.0              # só mesa tem sombra de assentos
    assert by["Mesa 2"]["margin"] == 0.15
    assert c.get(f"/api/cameras/{cam}/zones").json()["zones"][2]["margin"] == 0.15
    assert put(zone("M", margin=-0.1)).status_code == 400
    assert put(zone("M", margin=0.9)).status_code == 400
    assert put(zone("M", margin=0.0)).status_code == 200   # zero = sem sombra, válido


def test_old_zones_get_the_default_seat_margin_on_migration(tmp_path):
    import sqlite3
    from atendeio.db import Database
    from atendeio.repositories.zones import ZoneRepository
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, pw_hash TEXT, created REAL);
        CREATE TABLE cameras (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, kind TEXT, ref TEXT, secret BLOB, created REAL);
        CREATE TABLE zones (id INTEGER PRIMARY KEY, camera_id INTEGER, name TEXT, kind TEXT, points TEXT,
                            shape TEXT NOT NULL DEFAULT 'poly', angle REAL NOT NULL DEFAULT 0, created REAL);
        INSERT INTO zones (id, camera_id, name, kind, points, created) VALUES (1, 1, 'Mesa 1', 'mesa', '[[0.1,0.1],[0.5,0.1],[0.5,0.5]]', 0);
    """)
    old.commit(); old.close()
    db = Database(path); db.init()
    assert ZoneRepository(db).list_for_camera(1)[0]["margin"] == 0.06
