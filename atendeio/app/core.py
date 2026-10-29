"""AppCore: o motor inteiro do app desktop, dentro do mesmo processo da interface e SEM HTTP.

Monta o mesmo `Container` do servidor (serviços, repositórios, hubs) e expõe o que a interface precisa. O dono é fixo (um
utilizador local, sem login por senha). Usuário e senha RTSP vivem só na memória (SessionCredentials)."""

import threading
import time
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Callable, Optional

from ..analytics.zones import KINDS
from ..config import Settings
from ..container import Container, build_container
from ..errors import DomainError, RateLimitError, ValidationError
from ..repositories.map import MapRepository
from ..analytics.camera_geometry import CameraGeometry
from ..services import rtsp
from ..vision import view_signature as VS
from ..services.zones import to_zone
from .floor_calib import FloorCalib


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
        self._map_repo = MapRepository(self.c.db)
        self._map_pinned: set = set()
        self._map_selected: Optional[set] = None
        self._map_limited: set = set()
        self._zone_cache: dict = {}
        self._started = False
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._reaper: Optional[threading.Thread] = None
        self.c.registry.geometry_lookup = self._geometry_provider
        self._view_win: dict = {}            # camera_id -> ViewWindow (quadros pequenos, só memória)
        self._view_bad: dict = {}            # camera_id -> ciclos seguidos com a cena diferente
        self._view_changed: dict = {}        # camera_id -> distância (cena mudou: remapear)
        self._view_at = 0.0

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
            try:
                self.watch_views()
            except Exception as e:
                print(f"[-] vigia da cena das câmeras: {type(e).__name__}: {e}")

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

    def set_camera_room(self, cam_id: int, room: Optional[str]) -> str:
        """Define a sala da câmera (opcional). Devolve o texto já limpo."""
        return self.c.cameras.set_room(cam_id, self.user_id, room)

    def rooms(self) -> list:
        """Salas já usadas (para sugerir ao editar)."""
        return sorted({c["room"] for c in self.cameras() if c.get("room")}, key=str.lower)

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
        self._zone_cache.pop(cam_id, None)
        self._map_pinned.discard(cam_id)
        self.c.registry.stop_camera(cam_id)

    def update_camera(self, cam_id: int, name: Optional[str] = None, host: Optional[str] = None, port=None,
                      path: Optional[str] = None, username: Optional[str] = None, password: Optional[str] = None) -> dict:
        """Edita a câmera: nome, endereço (rede) e, se informados, usuário/senha (só memória). Se o endereço ou as credenciais
        mudaram, o pipeline é reiniciado para reabrir a fonte com os dados novos."""
        before = self.c.cameras.get_owned(cam_id, self.user_id)["ref"]
        cam = self.c.cameras.update(cam_id, self.user_id, name, host, port, path)
        changed = cam["ref"] != before
        if cam["kind"] == "rtsp" and (username or password):
            self.c.cameras.set_credentials(cam_id, self.user_id, username or "", password or "")
            changed = True
            cam = self.c.cameras.update(cam_id, self.user_id)            # visão atualizada (needs_credentials)
        if changed:
            self.c.registry.stop_camera(cam_id)                         # a fonte antiga ainda estava aberta: reabre com a nova
            self.c.scheduler.tick()                                     # câmera monitorada volta sozinha
        return cam

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
        self._zone_cache.pop(cam_id, None)
        self.c.registry.set_zones(cam_id, [to_zone(r) for r in saved])
        self.accept_view(cam_id)                      # áreas remapeadas: a cena de agora é a nova referência
        return saved

    # -- a cena mudou? (câmera ou mobília movida: é preciso remapear) ---------------------------------------------------------
    VIEW_EVERY_S = 20.0           # um quadro pequeno a cada tanto; a mediana de 5 dá a assinatura
    VIEW_CONFIRM = 2              # ciclos seguidos com a cena diferente antes de avisar (evita alarme por uma mudança passageira)

    def watch_views(self, force: bool = False) -> None:
        """Compara a assinatura estável da cena de cada câmera lida com a guardada (64 bytes, sem imagem). Sem assinatura guardada, a
        primeira vira a referência. Se a cena mudar de forma sustentada, a câmera entra em `view_changed_ids()`."""
        now = time.monotonic()
        if not force and now - self._view_at < self.VIEW_EVERY_S:
            return
        self._view_at = now
        for hub in self.c.registry.hubs():
            if hub.owner_id != self.user_id or not hub.online:
                continue
            frame = hub.last_frame()
            if frame is None:
                continue
            cid = hub.cam_id
            win = self._view_win.setdefault(cid, VS.ViewWindow())
            win.add(frame)
            sig = win.signature()
            if sig is None:
                continue
            saved = self.c.cameras._cameras.get_view_sig(cid)
            if saved is None:
                self.c.cameras._cameras.set_view_sig(cid, sig)            # primeira vez: é a referência
                continue
            d = VS.distance(saved, sig)
            if d >= VS.CHANGED_AT:
                self._view_bad[cid] = self._view_bad.get(cid, 0) + 1
                if self._view_bad[cid] >= self.VIEW_CONFIRM:
                    self._view_changed[cid] = d
            else:
                self._view_bad.pop(cid, None)
                self._view_changed.pop(cid, None)

    def view_changed_ids(self) -> dict:
        """{camera_id: distância} das câmeras cuja cena mudou desde a última vez que as áreas/chão foram confirmados."""
        return dict(self._view_changed)

    def accept_view(self, cam_id: int) -> None:
        """A cena atual passa a ser a referência (o utilizador remapeou ou disse que está tudo certo)."""
        self.c.cameras.get_owned(cam_id, self.user_id)
        win = self._view_win.get(cam_id)
        sig = win.signature() if win is not None else None
        self.c.cameras._cameras.set_view_sig(cam_id, sig)                 # sem janela pronta: None, e a próxima vira a referência
        self._view_bad.pop(cam_id, None)
        self._view_changed.pop(cam_id, None)

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

    # -- Mapa do ambiente ---------------------------------------------------------------------------------------
    def map_enter(self, camera_ids=None) -> None:
        """O mapa abriu: lê as câmeras SELECIONADAS (`camera_ids`; None = todas) em FPS de monitoramento, sem gerar vídeo.
        Câmera que pede senha fica de fora; se o teto de câmeras simultâneas for atingido, ela aparece como "limite"."""
        self._map_limited.clear()
        self.map_select(camera_ids)

    def map_select(self, camera_ids=None) -> None:
        """Sincroniza as câmeras lidas pelo mapa com a seleção: prende as recém-selecionadas e SOLTA as desmarcadas
        (as monitoradas ou assistidas continuam; as outras são liberadas pelo coletor)."""
        from ..services.recognition import parse as parse_recognition
        self._map_selected = None if camera_ids is None else set(camera_ids)
        for cid in list(self._map_pinned):
            if self._map_selected is not None and cid not in self._map_selected:
                self.c.registry.unpin_for_map(cid)
                self._map_pinned.discard(cid)
        self._map_limited &= (self._map_selected if self._map_selected is not None else self._map_limited)
        for cam in self.c.cameras.list(self.user_id):
            cid = cam["id"]
            if self._map_selected is not None and cid not in self._map_selected:
                continue
            if cid in self._map_pinned or cam.get("needs_credentials"):
                continue
            row = self.c.cameras.get_owned(cid, self.user_id)
            enabled, classes = parse_recognition(row)
            try:
                self.c.registry.pin_for_map(cid, self.user_id, lambda r=row: self.c.cameras.source_for(r),
                                            self.c.zones.load(cid), enabled, classes)
                self._map_pinned.add(cid)
                self._map_limited.discard(cid)
            except RateLimitError:
                self._map_limited.add(cid)
            except DomainError:
                pass

    def map_leave(self) -> None:
        """O mapa fechou: solta as câmeras que ele prendeu (as monitoradas ou assistidas continuam)."""
        for cid in list(self._map_pinned):
            self.c.registry.unpin_for_map(cid)
        self._map_pinned.clear()
        self._map_limited.clear()
        self._map_selected = None

    def map_snapshot(self, camera_ids=None) -> dict:
        """Tudo que o mapa precisa num instante, SÓ das câmeras pedidas (None = todas): câmeras, áreas (em cache), estados e
        as que bateram no limite."""
        wanted = None if camera_ids is None else set(camera_ids)
        changed = self._view_changed
        cams = [{**c, "view_changed": c["id"] in changed} for c in self.c.cameras.list(self.user_id) if wanted is None or c["id"] in wanted]
        zones = {}
        for cam in cams:
            if cam["id"] not in self._zone_cache:
                self._zone_cache[cam["id"]] = self.c.zones.list(cam["id"], self.user_id)
            zones[cam["id"]] = self._zone_cache[cam["id"]]
        live = self.c.registry.states_for(self.user_id)
        return {"cameras": cams, "zones": zones, "states": {c["id"]: live.get(c["id"]) for c in cams},
                "limited": sorted(c for c in self._map_limited if wanted is None or c in wanted)}

    def map_frames(self, camera_ids) -> dict:
        """{camera_id: quadro BGR atual} das câmeras pedidas que estão sendo lidas (para montar o piso do Mapa; só memória)."""
        out = {}
        for cid in camera_ids:
            hub = self.c.registry.get(cid)
            if hub is not None and hub.owner_id == self.user_id:
                f = hub.last_frame()
                if f is not None:
                    out[cid] = f
        return out

    def map_layouts(self) -> dict:
        """{camera_id: (x, y, scale, rot°)} salvos (o que faltar vem do layout automático)."""
        return self._map_repo.all_for_user(self.user_id)

    def set_map_layout(self, cam_id: int, x: float, y: float, scale: float, rot: float = 0.0) -> None:
        self.c.cameras.get_owned(cam_id, self.user_id)
        for v in (x, y, scale, rot):
            if not isinstance(v, (int, float)) or v != v or abs(v) > 1e6:
                raise ValidationError("Posição inválida no mapa.")
        self._map_repo.upsert(cam_id, float(x), float(y), max(0.4, min(3.0, float(scale))), float(rot) % 360.0)

    @staticmethod
    def _provider_of(calib: FloorCalib):
        """aspecto da imagem -> geometria da câmera (posição e inclinação recuperadas do chão calibrado)."""
        return lambda aspect: CameraGeometry.from_calibration(calib._h(), calib.width, calib.depth, aspect)

    def _geometry_provider(self, cam_id: int):
        """Para o registro: a geometria do chão calibrado da câmera (ou None = regra por imagem)."""
        calib = self.map_calibrations().get(cam_id)
        return self._provider_of(calib) if calib is not None else None

    def map_calibrations(self) -> dict:
        """{camera_id: FloorCalib} das câmeras que têm o chão calibrado."""
        out = {}
        for cid, d in self._map_repo.calibrations_for_user(self.user_id).items():
            try:
                out[cid] = FloorCalib.from_dict(d)
            except (ValueError, KeyError, TypeError):
                continue                                  # dado ilegível: volta ao mapeamento aproximado
        return out

    def set_map_calibration(self, cam_id: int, pts, width: float, depth: float) -> None:
        self.c.cameras.get_owned(cam_id, self.user_id)
        try:
            calib = FloorCalib(tuple((float(x), float(y)) for x, y in pts), float(width), float(depth))
        except (ValueError, TypeError) as e:
            raise ValidationError(str(e) or "Calibração inválida.")
        self._map_repo.set_calibration(cam_id, calib.to_dict())
        self.c.registry.set_geometry(cam_id, self._provider_of(calib))      # as mesas desta câmera já passam a ser decididas em metros
        self.accept_view(cam_id)

    def clear_map_calibration(self, cam_id: int) -> None:
        self.c.cameras.get_owned(cam_id, self.user_id)
        self._map_repo.clear_calibration(cam_id)
        self.c.registry.set_geometry(cam_id, None)

    def reset_map_layout(self) -> None:
        self._map_repo.clear_for_user(self.user_id)

    def area_profile(self, cam_id: int, zone_id: int, days: int = 7) -> dict:
        a, b = self._span(days, None, None)
        return self.c.flow.area_profile(cam_id, self.user_id, zone_id, a, b)

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
