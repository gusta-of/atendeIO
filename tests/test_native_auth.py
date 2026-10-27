"""Apps nativos (Capacitor): login por token, Bearer, tíquetes de mídia e CORS — sem enfraquecer o web."""

import dataclasses
import time

import pytest
from fastapi.testclient import TestClient

from atendeio.api.app import create_app
from atendeio.container import build_container
from atendeio.services.tickets import TicketService
from tests.conftest import FakeDetector

NATIVE = "capacitor://localhost"
PW = "senha-segura-123"


@pytest.fixture
def native(settings, video_file):
    """Servidor com a origem do app nativo na lista de permissão."""
    cfg = dataclasses.replace(settings, cors_origins=(NATIVE, "http://localhost"))
    c = build_container(cfg, device_lister=lambda: [{"ref": str(video_file), "name": "Câmera de teste"}], detector=FakeDetector())
    return create_app(container=c), c


@pytest.fixture
def web(native):
    app, _ = native
    client = TestClient(app, base_url="http://testserver")
    yield client
    client.close()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def mk_user(web, name="ana"):
    assert web.post("/api/auth/register", json={"username": name, "password": PW}).status_code == 200
    web.cookies.clear()


def token_for(app, name="ana"):
    c = TestClient(app, base_url="http://testserver")   # cliente SEM cookie: como um app nativo
    r = c.post("/api/auth/token", json={"username": name, "password": PW}, headers={"Origin": NATIVE})
    assert r.status_code == 200, r.text
    return c, r.json()["token"]


# ── login por token + Bearer ──────────────────────────────────────────────────────────────────
def test_token_login_then_bearer_reaches_the_api(native, web):
    app, _ = native
    mk_user(web)
    native_client, token = token_for(app)
    assert native_client.get("/api/auth/me").status_code == 401                    # sem credencial
    assert native_client.get("/api/auth/me", headers=bearer(token)).json() == {"username": "ana"}
    assert native_client.get("/api/cameras", headers=bearer(token)).status_code == 200


def test_token_login_does_not_set_a_cookie(native, web):
    app, _ = native
    mk_user(web)
    c = TestClient(app, base_url="http://testserver")
    r = c.post("/api/auth/token", json={"username": "ana", "password": PW})
    assert "set-cookie" not in r.headers and r.json()["expires_in"] > 0


def test_wrong_password_is_401_and_shares_the_login_throttle(native, web):
    app, c = native
    mk_user(web)
    nc = TestClient(app, base_url="http://testserver")
    codes = [nc.post("/api/auth/token", json={"username": "ana", "password": "errada-errada"}).status_code
             for _ in range(c.settings.login_fail_limit + 1)]
    assert codes[0] == 401 and codes[-1] == 429
    # e o bloqueio vale para o login comum também (mesma chave)
    assert nc.post("/api/auth/login", json={"username": "ana", "password": PW}).status_code == 429


def test_bad_or_garbage_bearer_is_rejected(native, web):
    app, _ = native
    mk_user(web)
    nc, token = token_for(app)
    for header in ("Bearer nao-existe", "Bearer ", "Basic abc", token):
        assert nc.get("/api/auth/me", headers={"Authorization": header}).status_code == 401


def test_logout_revokes_the_bearer_token(native, web):
    app, _ = native
    mk_user(web)
    nc, token = token_for(app)
    assert nc.post("/api/auth/logout", headers=bearer(token)).status_code == 200
    assert nc.get("/api/auth/me", headers=bearer(token)).status_code == 401


# ── tíquetes de mídia ─────────────────────────────────────────────────────────────────────────
def own_camera(nc, token, video_file):
    r = nc.post("/api/cameras/local", json={"ref": str(video_file), "name": "Sala"}, headers={**bearer(token), "Origin": NATIVE})
    assert r.status_code == 200, r.text
    return r.json()["camera"]["id"]


def ticket(nc, token, cam, kind):
    r = nc.post(f"/api/cameras/{cam}/ticket", json={"kind": kind}, headers={**bearer(token), "Origin": NATIVE})
    return r


def test_ticket_opens_the_stream_without_any_header(native, web, video_file):
    app, c = native
    mk_user(web)
    nc, token = token_for(app)
    cam = own_camera(nc, token, video_file)
    t = ticket(nc, token, cam, "stream").json()["ticket"]
    bare = TestClient(app, base_url="http://testserver")                              # <img>: sem Authorization, sem cookie
    assert bare.get(f"/stream?camera={cam}").status_code == 401
    with bare.stream("GET", f"/stream?camera={cam}&ticket={t}") as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("multipart/x-mixed-replace")


def test_ticket_is_bound_to_camera_and_kind(native, web, video_file):
    app, _ = native
    mk_user(web)
    nc, token = token_for(app)
    cam = own_camera(nc, token, video_file)
    t = ticket(nc, token, cam, "stream").json()["ticket"]
    bare = TestClient(app, base_url="http://testserver")
    assert bare.get(f"/api/cameras/{cam}/events?ticket={t}").status_code == 401        # tipo errado
    assert bare.get(f"/stream?camera={cam + 1}&ticket={t}").status_code == 401         # outra câmera


def test_ticket_cannot_be_issued_for_someone_elses_camera(native, web, video_file):
    app, _ = native
    mk_user(web, "ana")
    mk_user(web, "bia")
    ana, ana_t = token_for(app, "ana")
    bia, bia_t = token_for(app, "bia")
    cam = own_camera(ana, ana_t, video_file)
    assert ticket(bia, bia_t, cam, "stream").status_code == 404                        # indistinguível de "não existe"
    assert ticket(ana, ana_t, cam, "nao-existe").status_code == 422
    bare = TestClient(app, base_url="http://testserver")
    assert bare.get(f"/stream?camera={cam}&ticket=lixo").status_code == 401
    assert ticket(bare, "", cam, "stream").status_code == 401                          # sem sessão não emite


def test_tampered_ticket_is_rejected(native, web, video_file):
    app, _ = native
    mk_user(web)
    nc, token = token_for(app)
    cam = own_camera(nc, token, video_file)
    t = ticket(nc, token, cam, "stream").json()["ticket"]
    body, sig = t.split(".")
    flipped = body[:-2] + ("AA" if not body.endswith("AA") else "BB")
    bare = TestClient(app, base_url="http://testserver")
    assert bare.get(f"/stream?camera={cam}&ticket={flipped}.{sig}").status_code == 401
    assert bare.get(f"/stream?camera={cam}&ticket={body}.{sig[:-2]}AA").status_code == 401


def test_ticket_dies_with_the_session(native, web, video_file):
    app, _ = native
    mk_user(web)
    nc, token = token_for(app)
    cam = own_camera(nc, token, video_file)
    t = ticket(nc, token, cam, "events").json()["ticket"]
    nc.post("/api/auth/logout", headers=bearer(token))
    bare = TestClient(app, base_url="http://testserver")
    assert bare.get(f"/api/cameras/{cam}/events?ticket={t}").status_code == 401


def test_expired_ticket_is_rejected():
    now = [1000.0]
    svc = TicketService(b"k" * 32, ttl_s=60, clock=lambda: now[0])
    t = svc.issue(1, 7, "stream", "digest")
    assert svc.verify(t, 7, "stream")["u"] == 1
    now[0] += 61
    assert svc.verify(t, 7, "stream") is None
    assert svc.verify("sem-ponto", 7, "stream") is None and svc.verify("", 7, "stream") is None


def test_tickets_from_another_server_key_do_not_verify():
    a, b = TicketService(b"a" * 32), TicketService(b"b" * 32)
    assert b.verify(a.issue(1, 7, "events", "d"), 7, "events") is None


# ── CORS e Origin ─────────────────────────────────────────────────────────────────────────────
def test_cors_only_for_listed_origins(native):
    app, _ = native
    c = TestClient(app, base_url="http://testserver")
    ok = c.options("/api/auth/token", headers={"Origin": NATIVE, "Access-Control-Request-Method": "POST",
                                                "Access-Control-Request-Headers": "authorization,content-type"})
    assert ok.headers["access-control-allow-origin"] == NATIVE
    assert "access-control-allow-credentials" not in ok.headers                      # sem credenciais de navegador
    bad = c.options("/api/auth/token", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_cors_is_off_by_default(new_client):
    c = new_client()
    r = c.options("/api/auth/token", headers={"Origin": NATIVE, "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


def test_foreign_origin_with_the_session_cookie_is_still_blocked_csrf(native, web):
    """O ponto crítico: mesmo uma origem LISTADA não pode agir com o cookie do navegador (CSRF)."""
    app, _ = native
    assert web.post("/api/auth/register", json={"username": "ana", "password": PW}).status_code == 200   # web tem o cookie
    assert web.cookies.get("atendeio_session")
    r = web.post("/api/cameras/rtsp", json={"host": "192.168.1.9"}, headers={"Origin": NATIVE})
    assert r.status_code == 403
    r = web.post("/api/cameras/rtsp", json={"host": "192.168.1.9"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert web.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403


def test_unlisted_origin_without_cookie_is_blocked(native):
    app, _ = native
    c = TestClient(app, base_url="http://testserver")
    r = c.post("/api/auth/token", json={"username": "x", "password": "y"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post("/api/auth/token", json={"username": "x", "password": "y"}, headers={"Origin": NATIVE})
    assert r.status_code == 401                                                       # listada: chega à autenticação


def test_same_origin_web_login_keeps_working_and_stays_cookie_only(web):
    r = web.post("/api/auth/register", json={"username": "ana", "password": PW}, headers={"Origin": "http://testserver"})
    assert r.status_code == 200 and "token" not in r.text and web.get("/api/auth/me").status_code == 200


# ── isolamento intacto no modo nativo ─────────────────────────────────────────────────────────
def test_bearer_users_stay_isolated(native, web, video_file):
    app, _ = native
    mk_user(web, "ana")
    mk_user(web, "bia")
    ana, ana_t = token_for(app, "ana")
    bia, bia_t = token_for(app, "bia")
    cam = own_camera(ana, ana_t, video_file)
    assert bia.get("/api/cameras", headers=bearer(bia_t)).json()["cameras"] == []
    assert bia.get(f"/stream?camera={cam}", headers=bearer(bia_t)).status_code == 404
    assert bia.delete(f"/api/cameras/{cam}", headers={**bearer(bia_t), "Origin": NATIVE}).status_code == 404
