"""AppCore: o motor inteiro do app desktop, dentro do mesmo processo da interface e SEM HTTP.

Monta o mesmo `Container` do servidor (serviços, repositórios, hubs) e expõe o que a interface precisa. O dono é fixo (um
utilizador local, sem login por senha). Usuário e senha RTSP vivem só na memória (SessionCredentials)."""

import threading
from dataclasses import dataclass, replace
from typing import Callable, Optional

from ..analytics.zones import KINDS
from ..config import Settings
from ..container import Container, build_container
from ..services import rtsp
from ..services.zones import to_zone


@dataclass
class Watch:
    """Uma câmera sendo assistida: solta o espectador (e o pipeline, se ninguém mais usa) em `stop()`."""
    core: "AppCore"
    cam_id: int
    hub: object
    token: object
    _stopped: bool = False

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.hub.unsubscribe_frames(self.token)
        self.core.c.registry.release(self.hub)


class AppCore:
    def __init__(self, settings: Optional[Settings] = None, *, detector=None, device_lister: Optional[Callable] = None):
        settings = settings or Settings.from_env()
        if not settings.desktop:
            settings = replace(settings, mode="desktop")
        self.settings = settings
        self.c: Container = build_container(settings, device_lister=device_lister, detector=detector)
        self.user_id = self.c.auth.ensure_local_user()
        self._started = False
        self._lock = threading.Lock()

    # -- ciclo de vida -----------------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self.c.flow_writer.start()
        self.c.scheduler.start()

    def stop(self) -> None:
        """Saída limpa: o monitor solta os hubs, cada hub entrega o histórico, o escritor grava e o cofre é esquecido."""
        with self._lock:
            if not self._started:
                return
            self._started = False
        self.c.scheduler.stop()
        self.c.registry.stop_all()
        self.c.flow_writer.stop()
        if self.c.credentials is not None:
            self.c.credentials.clear()

    def preload_model(self) -> None:
        """Carrega e aquece o YOLO (chamar numa thread: demora alguns segundos)."""
        self.c.detector.load()

    # -- câmeras ---------------------------------------------------------------------------------
    def cameras(self) -> list:
        return self.c.cameras.list(self.user_id)

    def camera(self, cam_id: int) -> dict:
        return self.c.cameras.get_owned(cam_id, self.user_id)

    def presets(self) -> dict:
        return rtsp.PRESETS

    def local_devices(self) -> list:
        return self.c.cameras.local_devices(self.user_id)

    def add_rtsp(self, name: str, host: str, port, username: str, password: str, path: str = "") -> dict:
        return self.c.cameras.add_rtsp(self.user_id, name, host, port, username, password, path)

    def add_local(self, ref: str, name: str = "") -> dict:
        return self.c.cameras.add_local(self.user_id, ref, name)

    def remove_camera(self, cam_id: int) -> None:
        self.c.cameras.delete(cam_id, self.user_id)
        self.c.registry.stop_camera(cam_id)

    def set_credentials(self, cam_id: int, username: str, password: str) -> dict:
        """Usuário e senha da câmera RTSP (só memória). Câmera monitorada volta a ser analisada já."""
        cam = self.c.cameras.set_credentials(cam_id, self.user_id, username, password)
        self.c.scheduler.tick()
        return cam

    def cameras_needing_credentials(self) -> list:
        return [c for c in self.cameras() if c.get("needs_credentials")]

    # -- reconhecimento --------------------------------------------------------------------------
    def class_catalog(self) -> dict:
        return self.c.recognition.catalog()

    def recognition(self, cam_id: int) -> dict:
        return self.c.recognition.get(cam_id, self.user_id)

    def set_recognition(self, cam_id: int, enabled: bool, classes: list) -> dict:
        saved = self.c.recognition.update(cam_id, self.user_id, enabled, classes)
        self.c.registry.set_recognition(cam_id, saved["enabled"], frozenset(saved["classes"]))
        return saved

    # -- áreas -------------------------------------------------------------------------------
    def zones(self, cam_id: int) -> list:
        return self.c.zones.list(cam_id, self.user_id)

    zone_kinds = KINDS

    def replace_zones(self, cam_id: int, zones: list) -> list:
        saved = self.c.zones.replace(cam_id, self.user_id, zones)
        self.c.registry.set_zones(cam_id, [to_zone(r) for r in saved])
        return saved

    def mark_clean(self, cam_id: int, zone_id: int) -> None:
        self.c.zones.ensure_exists(cam_id, zone_id, self.user_id)
        self.c.registry.mark_clean(cam_id, zone_id)

    # -- monitoramento ---------------------------------------------------------------------------
    def monitor(self, cam_id: int) -> dict:
        return self.c.monitor.get(cam_id, self.user_id)

    def set_monitor(self, cam_id: int, enabled: bool, from_: str = "", to: str = "") -> dict:
        out = self.c.monitor.update(cam_id, self.user_id, enabled, from_, to)
        self.c.scheduler.tick()
        return out

    # -- vídeo ao vivo ---------------------------------------------------------------------------
    def watch(self, cam_id: int, callback: Callable, boxes: bool = True, areas: bool = True) -> Watch:
        """Começa a assistir uma câmera: `callback(quadro_bgr, estado)` roda na thread de inferência (deve ser rápido).
        Levanta `CredentialsRequired` se a câmera RTSP ainda não recebeu usuário/senha."""
        cam = self.c.cameras.get_owned(cam_id, self.user_id)
        self.c.cameras.require_credentials(cam)
        from ..services.recognition import parse as parse_recognition
        zones = self.c.zones.load(cam_id)
        enabled, classes = parse_recognition(cam)
        hub = self.c.registry.acquire(cam_id, self.user_id, lambda: self.c.cameras.source_for(cam), zones, enabled, classes)
        token = hub.subscribe_frames(callback, boxes=boxes, areas=areas)
        return Watch(self, cam_id, hub, token)

    def states(self) -> dict:
        return self.c.registry.states_for(self.user_id)

    def events_since(self, cam_id: int, seq: int) -> list:
        hub = self.c.registry.get(cam_id)
        return hub.events.recent_since(seq) if hub else []

    # -- análise de fluxo (dados locais) ---------------------------------------------------------------
    def flow_report(self, cam_id: int, **kw) -> dict:
        return self.c.flow.report(cam_id, self.user_id, **kw)

    def flow_day(self, cam_id: int, day=None) -> dict:
        return self.c.flow.day(cam_id, self.user_id, day)
