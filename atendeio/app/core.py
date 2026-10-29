"""AppCore: o motor inteiro do app desktop, dentro do mesmo processo da interface e SEM HTTP.

Monta o mesmo `Container` do servidor (serviços, repositórios, hubs) e expõe o que a interface precisa. O dono é fixo (um
utilizador local, sem login por senha). Usuário e senha RTSP vivem só na memória (SessionCredentials)."""

import threading
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Callable, Optional

from ..analytics.zones import KINDS
from ..config import Settings
from ..container import Container, build_container
from ..errors import ValidationError
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
        self._stop_evt = threading.Event()
        self._reaper: Optional[threading.Thread] = None

    # -- ciclo de vida -----------------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._stop_evt.clear()
        self.c.flow_writer.start()
        self.c.scheduler.start()
        self._reaper = threading.Thread(target=self._reap_loop, name="reaper", daemon=True)
        self._reaper.start()

    def _reap_loop(self) -> None:
        """Libera a câmera que ninguém assiste nem monitora (fecha o dispositivo e para a análise). No servidor isso rodava no
        ciclo de vida do FastAPI; no app nativo precisa existir aqui, senão a webcam fica aberta para sempre."""
        interval = min(10.0, max(0.05, self.settings.idle_ttl_s / 3))
        while not self._stop_evt.wait(interval):
            try:
                self.c.registry.reap_idle()
            except Exception as e:
                print(f"[-] coletor de câmeras ociosas: {type(e).__name__}: {e}")

    def stop(self) -> None:
        """Saída limpa: o monitor solta os hubs, cada hub entrega o histórico, o escritor grava e o cofre é esquecido."""
        with self._lock:
            if not self._started:
                return
            self._started = False
        self._stop_evt.set()
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

    # -- FPS por câmera ----------------------------------------------------------------------------
    def fps(self, cam_id: int) -> dict:
        """FPS salvo (None = padrão) e os padrões do sistema, para a tela de configuração."""
        view, monitor = self.c.cameras.get_fps(cam_id, self.user_id)
        return {"view": view, "monitor": monitor, "default_view": self.settings.max_fps,
                "default_monitor": self.settings.monitor_fps}

    def set_fps(self, cam_id: int, fps_view: Optional[float], fps_monitor: Optional[float]) -> dict:
        view, monitor = self.c.cameras.set_fps(cam_id, self.user_id, fps_view, fps_monitor)
        self.c.registry.set_fps(cam_id, view, monitor)             # vale na hora, com a câmera ligada
        return self.fps(cam_id)

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

    def event_bus(self, cam_id: int):
        """O barramento de eventos da câmera (None se ela não está ligada agora)."""
        hub = self.c.registry.get(cam_id)
        return hub.events if hub else None

    def events_since(self, cam_id: int, seq: int, frames: bool = False) -> list:
        bus = self.event_bus(cam_id)
        return bus.recent_since(seq, frames) if bus else []

    # -- análise de fluxo (dados locais) ---------------------------------------------------------------------
    def _span(self, days: Optional[int], d_from, d_to) -> tuple:
        """`days=N`: os últimos N dias terminando HOJE no fuso do restaurante (o computador pode estar em outro fuso)."""
        if days is not None and not (d_from or d_to):
            if not 1 <= days <= 731:
                raise ValidationError("Número de dias inválido (de 1 a 731).")
            end = self.c.flow.today()
            return end - timedelta(days=days - 1), end
        return _as_date(d_from), _as_date(d_to)

    def flow_report(self, cam_id: int, days: Optional[int] = None, d_from=None, d_to=None,
                    hour_from: int = 0, hour_to: int = 24) -> dict:
        a, b = self._span(days, d_from, d_to)
        return self.c.flow.report(cam_id, self.user_id, a, b, hour_from, hour_to)

    def flow_day(self, cam_id: int, day=None) -> dict:
        return self.c.flow.day(cam_id, self.user_id, _as_date(day))

    def flow_csv(self, cam_id: int, days: Optional[int] = None, d_from=None, d_to=None,
                 hour_from: int = 0, hour_to: int = 24) -> str:
        a, b = self._span(days, d_from, d_to)
        return self.c.flow.csv(cam_id, self.user_id, a, b, hour_from, hour_to)


def _as_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValidationError("Data inválida. Use o formato AAAA-MM-DD.")
