import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from atendeio.api.app import create_app
from atendeio.config import Settings
from atendeio.container import build_container


class FakeDetector:
    """Sem YOLO: os testes não dependem do modelo nem de CPU pesada. Imita o filtro de classes
    (None = todas; lista vazia = nem roda) e conta as chamadas pra provar quando o modelo NÃO roda."""
    def __init__(self):
        self.calls = 0
        self.mask_calls = 0
        self.last_classes = "nunca chamado"

    def detect(self, frame, classes=None, masks=False):
        if classes is not None and not len(classes):
            return []
        self.calls += 1
        self.last_classes = classes
        self.mask_calls += bool(masks)
        person = {"name": "person", "cls": 0, "conf": 0.9, "cx": 0.5, "cy": 0.5, "box": (0.4, 0.3, 0.6, 0.7)}
        if masks:  # silhueta: um polígono em volta da caixa, como o modelo de segmentação devolveria
            person["poly"] = [(0.42, 0.3), (0.58, 0.3), (0.6, 0.7), (0.4, 0.7)]
        return [person] if classes is None or 0 in classes else []

    def load(self):
        return None


@pytest.fixture
def video_file(tmp_path):
    path = tmp_path / "cam.avi"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30, (320, 240))
    for i in range(300):
        w.write(np.full((240, 320, 3), i % 255, np.uint8))
    w.release()
    return path


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", static_dir=Settings().static_dir,
                    max_fps=30.0, monitor_fps=30.0, flow_flush_s=0.4, idle_ttl_s=0.1, max_cameras=3, max_cameras_per_user=2,
                    occupy_after_s=0.0, free_after_s=0.0)


@pytest.fixture
def container(settings, video_file):
    devices = [{"ref": str(video_file), "name": "Câmera de teste"}]
    return build_container(settings, device_lister=lambda: devices, detector=FakeDetector())


@pytest.fixture
def new_client(container):
    """Fábrica de clientes HTTP com cookie jar próprio: cada um é um utilizador/navegador."""
    app = create_app(container=container)
    clients = []

    def make(username=None, password="senha-segura-123"):
        c = TestClient(app, base_url="http://testserver")
        if username:
            r = c.post("/api/auth/register", json={"username": username, "password": password})
            assert r.status_code == 200, r.text
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.close()
