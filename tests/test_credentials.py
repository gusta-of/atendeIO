"""Credenciais RTSP no modo desktop: usuário e senha só na memória desta execução (nunca em disco nem na nuvem);
IP, porta e caminho persistem. Depois de "reiniciar o computador" a câmera pede usuário e senha de novo."""

from dataclasses import replace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from atendeio.api.app import create_app
from atendeio.container import build_container
from atendeio.services.credentials import SessionCredentials
from tests.conftest import FakeDetector

PASSWORD = "S3nh@-Unica-ZZ-9137"
USER = "operador-cam-77"
RTSP = {"name": "Salão", "host": "192.168.1.50", "port": 554, "username": USER, "password": PASSWORD, "path": "stream1"}


def key() -> str:
    return Fernet.generate_key().decode()


# ── o cofre em si ─────────────────────────────────────────────────────────────────────────────
def test_store_keeps_values_only_in_memory_without_a_key(tmp_path):
    s = SessionCredentials(tmp_path / "run" / "creds.bin", "")          # sem chave: nenhum arquivo, jamais
    s.put(1, USER, PASSWORD)
    assert s.get(1) == (USER, PASSWORD) and s.has(1) and not s.has(2)
    assert not (tmp_path / "run").exists()
    s.forget(1)
    assert s.get(1) is None


def test_mirror_file_is_encrypted_and_dies_with_the_key(tmp_path):
    path, k = tmp_path / "run" / "creds.bin", key()
    s = SessionCredentials(path, k)
    s.put(1, USER, PASSWORD)
    raw = path.read_bytes()
    assert PASSWORD.encode() not in raw and USER.encode() not in raw       # cifrado de verdade

    again = SessionCredentials(path, k)                                    # o motor caiu e voltou: mesma chave
    assert again.get(1) == (USER, PASSWORD)

    rebooted = SessionCredentials(path, key())                             # computador reiniciou: chave nova
    assert rebooted.get(1) is None
    assert not path.exists()                                               # e o arquivo inútil foi apagado


def test_clear_removes_the_mirror(tmp_path):
    path = tmp_path / "creds.bin"
    s = SessionCredentials(path, key())
    s.put(1, USER, PASSWORD)
    assert path.exists()
    s.clear()
    assert not path.exists() and s.get(1) is None


def test_corrupt_mirror_is_discarded(tmp_path):
    path = tmp_path / "creds.bin"
    path.write_bytes(b"lixo")
    assert SessionCredentials(path, key()).get(1) is None
    assert not path.exists()


# ── ponta a ponta (HTTP) ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def desktop(settings, video_file):
    cfg = replace(settings, mode="desktop", run_key=key())
    devices = [{"ref": str(video_file), "name": "Câmera de teste"}]

    def boot(cfg=cfg):
        container = build_container(cfg, device_lister=lambda: devices, detector=FakeDetector())
        return container, TestClient(create_app(container=container), base_url="http://testserver")

    clients = []

    def make(cfg=cfg):
        container, client = boot(cfg)
        clients.append(client)
        return container, client

    make.cfg = cfg
    yield make
    for c in clients:
        c.close()


def all_disk_bytes(root):
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


def test_password_never_touches_the_disk(desktop, settings):
    container, c = desktop()
    assert c.post("/api/auth/register", json={"username": "ana", "password": "senha-segura-123"}).status_code == 200
    cam = c.post("/api/cameras/rtsp", json=RTSP).json()["camera"]
    assert cam["needs_credentials"] is False                                # acabou de digitar
    assert container.cameras.source_for(container.cameras.get_owned(cam["id"], 1)).startswith("rtsp://")

    blob = all_disk_bytes(settings.data_dir)
    assert PASSWORD.encode() not in blob and USER.encode() not in blob
    row = container.db.connect().execute("SELECT ref, secret FROM cameras").fetchone()
    assert row["secret"] is None                                            # nada no banco
    assert row["ref"] == "rtsp://192.168.1.50:554/stream1"                  # mas IP, porta e caminho persistem


def test_after_reboot_credentials_are_asked_again_but_ip_and_port_remain(desktop, settings):
    _, c = desktop()
    c.post("/api/auth/register", json={"username": "ana", "password": "senha-segura-123"})
    cam = c.post("/api/cameras/rtsp", json=RTSP).json()["camera"]["id"]

    rebooted_cfg = replace(desktop.cfg, run_key=key())                      # computador reiniciou: chave por execução nova
    container2, c2 = desktop(rebooted_cfg)
    c2.cookies.update(c.cookies)                                            # a sessão do app continua válida

    listed = c2.get("/api/cameras").json()["cameras"][0]
    assert listed["ref"] == "rtsp://192.168.1.50:554/stream1" and listed["needs_credentials"] is True

    r = c2.get(f"/stream?camera={cam}")                                     # vídeo recusa e diz o que falta
    assert r.status_code == 423 and r.json()["code"] == "credentials_required"

    ok = c2.put(f"/api/cameras/{cam}/credentials", json={"username": USER, "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["camera"]["needs_credentials"] is False
    assert c2.get("/api/cameras").json()["cameras"][0]["needs_credentials"] is False
    assert PASSWORD.encode() not in all_disk_bytes(settings.data_dir)


def test_old_databases_lose_stored_secrets_in_desktop_mode(desktop, settings, video_file):
    server = build_container(settings, device_lister=lambda: [], detector=FakeDetector())   # modo servidor: cifrado no banco
    uid = server.auth.register("ana", "senha-segura-123")
    assert uid
    server.cameras.add_rtsp(1, "Velha", "192.168.1.60", 554, USER, PASSWORD, "")
    assert server.db.connect().execute("SELECT secret FROM cameras").fetchone()["secret"] is not None

    container, _ = desktop()                                                # sobe em modo desktop sobre o mesmo banco
    assert container.db.connect().execute("SELECT secret FROM cameras").fetchone()["secret"] is None
    assert container.cameras.list(1)[0]["needs_credentials"] is True


def test_monitor_does_not_hammer_a_camera_without_credentials(desktop, settings):
    container, c = desktop()
    c.post("/api/auth/register", json={"username": "ana", "password": "senha-segura-123"})
    cam = c.post("/api/cameras/rtsp", json=RTSP).json()["camera"]["id"]
    c.put(f"/api/cameras/{cam}/recognition", json={"enabled": True, "classes": [0]})
    assert c.put(f"/api/cameras/{cam}/monitor", json={"enabled": True}).status_code == 200

    container2, _ = desktop(replace(desktop.cfg, run_key=key()))            # reiniciou: sem credenciais
    result = container2.scheduler.tick()
    assert result["held"] == [] and (cam, "aguardando_credenciais") in result["errors"]


def test_unlock_is_isolated_and_only_for_rtsp(desktop, video_file):
    container, alice = desktop()
    alice.post("/api/auth/register", json={"username": "alice", "password": "senha-segura-123"})
    rtsp_cam = alice.post("/api/cameras/rtsp", json=RTSP).json()["camera"]["id"]
    local_cam = alice.post("/api/cameras/local", json={"ref": str(video_file)}).json()["camera"]["id"]

    bob = TestClient(alice.app, base_url="http://testserver")
    bob.post("/api/auth/register", json={"username": "bob", "password": "senha-segura-123"})
    body = {"username": "x", "password": "y"}
    assert bob.put(f"/api/cameras/{rtsp_cam}/credentials", json=body).status_code == 404      # câmera de outro: 404
    assert alice.put(f"/api/cameras/{local_cam}/credentials", json=body).status_code == 400   # USB não tem senha
    assert alice.put("/api/cameras/9999/credentials", json=body).status_code == 404
    bob.close()


def test_deleting_a_camera_forgets_its_credentials(desktop):
    container, c = desktop()
    c.post("/api/auth/register", json={"username": "ana", "password": "senha-segura-123"})
    cam = c.post("/api/cameras/rtsp", json=RTSP).json()["camera"]["id"]
    assert container.credentials.has(cam)
    assert c.delete(f"/api/cameras/{cam}").status_code == 200
    assert not container.credentials.has(cam)


def test_clean_shutdown_leaves_no_credentials_behind(desktop, settings):
    container, _ = desktop()
    container.credentials.put(1, USER, PASSWORD)
    spill = settings.run_dir / "creds.bin"
    assert spill.exists()
    with TestClient(create_app(container=container)):                       # sobe e desce o app (lifespan)
        pass
    assert not spill.exists() and container.credentials.get(1) is None


def test_server_mode_is_unchanged(new_client, container):
    c = new_client("ana")
    cam = c.post("/api/cameras/rtsp", json=RTSP).json()["camera"]
    assert "needs_credentials" not in cam                                   # formato antigo
    assert container.db.connect().execute("SELECT secret FROM cameras").fetchone()["secret"] is not None
    assert PASSWORD not in c.get("/api/cameras").text
