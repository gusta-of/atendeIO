"""HubRegistry: ciclo de vida dos hubs (abre no 1º espectador ou pelo monitoramento; libera quando ocioso)."""

import threading
import time
from typing import Callable, Iterable, Optional

from ..analytics.zones import Zone
from ..config import Settings
from ..errors import RateLimitError
from ..vision.detector import Detector
from .hub import CameraHub


class HubRegistry:
    def __init__(self, settings: Settings, detector: Detector, flow_sink: Optional[Callable[[dict], object]] = None,
                 cloud_sink: Optional[Callable[[str, int, int, object], None]] = None):
        self._cfg, self._detector, self._flow_sink = settings, detector, flow_sink
        self._cloud_sink = cloud_sink
        self._hubs: dict = {}  # cam_id -> CameraHub
        self._zombies: list = []
        self._lock = threading.Lock()

    def _new_hub(self, cam_id, owner_id, get_source, zones, enabled, classes) -> CameraHub:
        hub = CameraHub(cam_id, owner_id, get_source, self._detector, self._cfg, zones, enabled, classes,
                        self._flow_sink, self._cloud_sink)
        self._hubs[cam_id] = hub
        hub.start()
        return hub

    def _live(self, cam_id: int):
        """O hub da câmera se estiver de pé. Um hub cujas threads morreram é um zumbi: sai do registro (o chamador
        o para fora do lock) e quem pediu recebe um novo."""
        hub = self._hubs.get(cam_id)
        if hub is not None and not hub.alive:
            del self._hubs[cam_id]
            self._zombies.append(hub)
            return None
        return hub

    def _reap_zombies(self) -> None:
        zs, self._zombies = self._zombies, []
        for z in zs:
            z.stop()
            print(f"[!] câmera {z.cam_id}: pipeline parado inesperadamente, reiniciando")

    def acquire(self, cam_id: int, owner_id: int, get_source: Callable,
                zones: Iterable[Zone] = (), enabled: bool = True,
                classes: Optional[frozenset] = None) -> CameraHub:
        with self._lock:
            hub = self._live(cam_id)
            if hub is None:
                mine = sum(1 for h in self._hubs.values() if h.owner_id == owner_id and h.viewers > 0)
                if len(self._hubs) >= self._cfg.max_cameras or mine >= self._cfg.max_cameras_per_user:
                    self._reap_zombies()
                    raise RateLimitError("Limite de câmeras simultâneas atingido.")
                hub = self._new_hub(cam_id, owner_id, get_source, zones, enabled, classes)
                print(f"[*] câmera {cam_id} iniciada")
            hub.viewers += 1
        self._reap_zombies()
        return hub

    # -- monitoramento contínuo: o hub fica de pé SEM contar como espectador -----------------------
    def hold(self, cam_id: int, owner_id: int, get_source: Callable, zones: Iterable[Zone] = (),
             enabled: bool = True, classes: Optional[frozenset] = None) -> CameraHub:
        """Garante o hub de uma câmera monitorada (cria, ou recria se morreu). Respeita o teto global."""
        with self._lock:
            hub = self._live(cam_id)
            if hub is None:
                if len(self._hubs) >= self._cfg.max_cameras:
                    self._reap_zombies()
                    raise RateLimitError("Limite de câmeras simultâneas atingido.")
                hub = self._new_hub(cam_id, owner_id, get_source, zones, enabled, classes)
                print(f"[*] câmera {cam_id} em monitoramento contínuo")
            hub.monitor = True
        self._reap_zombies()
        return hub

    def unhold(self, cam_id: int) -> None:
        """Fim do monitoramento (desligado ou fora do horário): o hub segue o ciclo normal e some se ficar ocioso."""
        with self._lock:
            hub = self._hubs.get(cam_id)
            if hub is not None and hub.monitor:
                hub.monitor = False
                hub.idle_since = time.monotonic()

    def release(self, hub: CameraHub) -> None:
        with self._lock:
            hub.viewers = max(0, hub.viewers - 1)
            if hub.viewers == 0:
                hub.idle_since = time.monotonic()

    def count(self) -> int:
        with self._lock:
            return len(self._hubs)

    def get(self, cam_id: int) -> Optional[CameraHub]:
        with self._lock:
            return self._hubs.get(cam_id)

    def states_for(self, owner_id: int) -> dict:
        """Estado das câmeras ATIVAS do dono — só as dele."""
        with self._lock:
            hubs = [h for h in self._hubs.values() if h.owner_id == owner_id]
        return {h.cam_id: h.snapshot_state() for h in hubs}

    def all_states(self) -> list:
        """[(câmera, dono, estado)] de todos os hubs de pé. Uso interno do envio à cloud (nunca exposto por HTTP)."""
        with self._lock:
            hubs = list(self._hubs.values())
        return [(h.cam_id, h.owner_id, h.snapshot_state()) for h in hubs]

    def set_zones(self, cam_id: int, zones: Iterable[Zone]) -> None:
        """Aplica as áreas editadas à câmera ao vivo (se não estiver ao vivo, o próximo acquire carrega)."""
        hub = self.get(cam_id)
        if hub:
            hub.set_zones(zones)

    def set_recognition(self, cam_id: int, enabled: bool, classes: frozenset) -> None:
        hub = self.get(cam_id)
        if hub:
            hub.set_recognition(enabled, classes)

    def mark_clean(self, cam_id: int, zone_id: int) -> None:
        hub = self.get(cam_id)
        if hub:
            hub.mark_clean(zone_id)

    def stop_camera(self, cam_id: int) -> None:
        """Câmera removida: derruba espectadores e libera o dispositivo."""
        with self._lock:
            hub = self._hubs.pop(cam_id, None)
        if hub:
            hub.stop()

    def reap_idle(self) -> None:
        now = time.monotonic()
        with self._lock:
            dead = [k for k, h in self._hubs.items()
                    if h.viewers == 0 and not h.monitor and now - h.idle_since > self._cfg.idle_ttl_s]
            hubs = [self._hubs.pop(k) for k in dead]
        for h in hubs:
            h.stop()
            print(f"[*] câmera {h.cam_id} parada (ociosa)")

    def stop_all(self) -> None:
        with self._lock:
            hubs = list(self._hubs.values())
            self._hubs.clear()
        for h in hubs:
            h.stop()
