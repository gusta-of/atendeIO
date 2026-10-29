"""Modo desktop: só o Electron fala com o motor (segredo por execução + Host local) e o dono local entra sem senha."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from atendeio.api.app import create_app
from atendeio.container import build_container
from tests.conftest import FakeDetector

SECRET = "segredo-de-execucao-123"
H = {"X-Atendeio-Launch": SECRET}


@pytest.fixture
def desktop_client(settings):
    container = build_container(replace(settings, mode="desktop", launch_secret=SECRET), device_lister=lambda: [],
                                detector=FakeDetector())
    with TestClient(create_app(container=container), base_url="http://127.0.0.1:8123") as c:
        yield c


def test_requests_without_the_launch_secret_are_refused(desktop_client):
    assert desktop_client.get("/api/auth/config").status_code == 403
    assert desktop_client.get("/api/auth/config", headers={"X-Atendeio-Launch": "errado"}).status_code == 403
    assert desktop_client.get("/app/").status_code == 403                                # nem a casca estática
    assert desktop_client.get("/api/auth/config", headers=H).status_code == 200


def test_foreign_host_header_is_refused_even_with_the_secret(desktop_client):
    r = desktop_client.get("/api/auth/config", headers={**H, "Host": "atacante.example:8123"})   # DNS rebinding
    assert r.status_code == 403
    assert desktop_client.get("/api/auth/config", headers={**H, "Host": "localhost:8123"}).status_code == 200


def test_local_session_opens_without_a_password(desktop_client):
    r = desktop_client.post("/api/auth/local", headers=H)
    assert r.status_code == 200
    token = r.json()["token"]
    me = desktop_client.get("/api/auth/me", headers={**H, "Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json() == {"username": "local"}
    again = desktop_client.post("/api/auth/local", headers=H).json()["token"]
    assert again != token                                                                  # sessão nova, mesmo dono
    assert desktop_client.post("/api/auth/login", headers=H,
                               json={"username": "local", "password": "qualquer-coisa"}).status_code == 401


def test_local_route_does_not_exist_without_the_secret_or_outside_desktop(settings, new_client):
    assert new_client().post("/api/auth/local").status_code == 404                        # modo servidor
    no_secret = build_container(replace(settings, mode="desktop"), device_lister=lambda: [], detector=FakeDetector())
    with TestClient(create_app(container=no_secret), base_url="http://127.0.0.1:8123") as c:
        assert c.post("/api/auth/local").status_code == 404                               # desktop sem segredo: nada exposto


def test_server_mode_ignores_the_launch_header(new_client):
    assert new_client().get("/api/auth/config").status_code == 200


def test_quit_asks_the_server_to_stop_cleanly(desktop_client):
    class FakeServer:
        should_exit = False
    desktop_client.app.state.server = FakeServer()
    assert desktop_client.post("/api/desktop/quit").status_code == 403                    # sem segredo: recusado
    assert desktop_client.post("/api/desktop/quit", headers=H).json() == {"stopping": True}
    assert desktop_client.app.state.server.should_exit is True


def test_quit_does_not_exist_in_server_mode(new_client):
    assert new_client().post("/api/desktop/quit").status_code == 404
