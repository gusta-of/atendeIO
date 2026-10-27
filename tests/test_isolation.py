"""O requisito central: cada utilizador só enxerga e usa as PRÓPRIAS câmeras."""

RTSP = {"name": "Recepção", "host": "192.168.1.50", "port": 554,
        "username": "admin", "password": "p@ss:w/rd#1", "path": "stream1"}


def test_other_user_cannot_see_or_touch_my_camera(new_client, container):
    alice, bob = new_client("alice"), new_client("bob")
    cam_id = alice.post("/api/cameras/rtsp", json=RTSP).json()["camera"]["id"]

    assert [c["id"] for c in alice.get("/api/cameras").json()["cameras"]] == [cam_id]
    assert bob.get("/api/cameras").json()["cameras"] == []

    # câmera de outro é indistinguível de uma que não existe (404, não 403)
    assert bob.get(f"/stream?camera={cam_id}").status_code == 404
    assert bob.get("/stream?camera=999999").status_code == 404
    assert bob.delete(f"/api/cameras/{cam_id}").status_code == 404
    assert container.registry.get(cam_id) is None  # a tentativa não abriu pipeline

    # e o dono continua com a câmera
    assert len(alice.get("/api/cameras").json()["cameras"]) == 1


def test_credentials_never_leave_the_server(new_client, container):
    alice = new_client("alice")
    res = alice.post("/api/cameras/rtsp", json=RTSP)
    listing = alice.get("/api/cameras")
    for body in (res.text, listing.text):
        assert "p@ss" not in body and "admin" not in body
    assert "@" not in listing.json()["cameras"][0]["ref"]
    # em repouso: criptografado, nunca em claro no banco
    raw = container.db.path.read_bytes()
    assert b"p@ss:w/rd#1" not in raw


def test_local_camera_has_a_single_owner(new_client, video_file):
    alice, bob = new_client("alice"), new_client("bob")
    ref = str(video_file)
    assert [d["ref"] for d in bob.get("/api/local-devices").json()["devices"]] == [ref]

    assert alice.post("/api/cameras/local", json={"ref": ref, "name": "Sala"}).status_code == 200

    # depois de reivindicada, some pro outro e não pode ser reivindicada de novo
    assert bob.get("/api/local-devices").json()["devices"] == []
    assert bob.post("/api/cameras/local", json={"ref": ref}).status_code == 409
    mine = alice.get("/api/local-devices").json()["devices"]
    assert mine and mine[0]["mine"] is True


def test_cannot_claim_arbitrary_device_path(new_client):
    alice = new_client("alice")
    r = alice.post("/api/cameras/local", json={"ref": "/etc/passwd"})
    assert r.status_code == 404


def test_states_only_include_own_cameras(new_client, container, video_file):
    alice, bob = new_client("alice"), new_client("bob")
    cam = alice.post("/api/cameras/local", json={"ref": str(video_file)}).json()["camera"]
    owner = container.cameras.get_owned(cam["id"], container.auth.user_for_token(
        alice.cookies.get("atendeio_session"))["id"])
    hub = container.registry.acquire(cam["id"], owner["user_id"],
                                     lambda: container.cameras.source_for(owner))
    try:
        assert hub.ready.wait(10)
        assert str(cam["id"]) in alice.get("/api/states").json()["states"]
        assert bob.get("/api/states").json()["states"] == {}
    finally:
        container.registry.release(hub)
        container.registry.stop_all()
