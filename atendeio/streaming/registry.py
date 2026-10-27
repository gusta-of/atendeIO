"""HubRegistry: ciclo de vida dos hubs (abre no 1º espectador, libera quando ocioso)."""

import threading
import time
from typing import Callable, Iterable, Optional

from ..analytics.zones import Zone
from ..config import Settings
from ..errors import RateLimitError
from ..vision.detector import Detector
from .hub import CameraHub


class HubRegistry:
    def __init__(self, settings: Settings, detector: Detector):
        self._cfg, self._detector = settings, detector
        self._hubs: dict = {}  # cam_id -> CameraHub
        self._lock = threading.Lock()

    def acquire(self, cam_id: int, owner_id: int, get_source: Callable,
                zones: Iterable[Zone] = (), enabled: bool = True,
                classes: Optional[frozenset] = None) -> CameraHub:
        with self._lock:
            hub = self._hubs.get(cam_id)
            if hub is None:
                mine = sum(1 for h in self._hubs.values() if h.owner_id == owner_id and h.viewers > 0)
                if len(self._hubs) >= self._cfg.max_cameras or mine >= self._cfg.max_cameras_per_user:
                    raise RateLimitError("Limite de câmeras simultâneas atingido.")
                hub = CameraHub(cam_id, owner_id, get_source, self._detector, self._cfg, zones, enabled, classes)
                self._hubs[cam_id] = hub
                hub.start()
                print(f"[*] câmera {cam_id} iniciada")
            hub.viewers += 1
            return hub

    def release(self, hub: CameraHub) -> None:
        with self._lock:
            hub.viewers = max(0, hub.viewers - 1)
            if hub.viewers == 0:
                hub.idle_since = time.monotonic()

    def get(self, cam_id: int) -> Optional[CameraHub]:
        with self._lock:
            return self._hubs.get(cam_id)

    def states_for(self, owner_id: int) -> dict:
        """Estado das câmeras ATIVAS do dono — só as dele."""
        with self._lock:
            hubs = [h for h in self._hubs.values() if h.owner_id == owner_id]
        return {h.cam_id: h.snapshot_state() for h in hubs}

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
                    if h.viewers == 0 and now - h.idle_since > self._cfg.idle_ttl_s]
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
