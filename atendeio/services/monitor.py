"""Monitoramento contínuo: a câmera é analisada o dia todo (ou no horário de funcionamento), mesmo sem ninguém
assistindo, para alimentar o histórico de fluxo. Em ritmo baixo e sem gerar vídeo (ver CameraHub)."""

import re
import threading
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from ..config import Settings
from ..errors import ValidationError
from ..repositories.cameras import CameraRepository
from ..streaming.registry import HubRegistry
from .cameras import CameraService
from .recognition import parse as parse_recognition
from .zones import ZoneService

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def person_ready(cam: dict) -> bool:
    """Dá pra medir pessoas? Reconhecimento ligado e a classe "Pessoa" habilitada."""
    enabled, classes = parse_recognition(cam)
    return bool(enabled and 0 in classes)


def in_window(now_hhmm: str, from_: Optional[str], to: Optional[str]) -> bool:
    """Está dentro do horário de funcionamento? Sem horário = o dia todo; vira a meia-noite (22:00–02:00) também vale."""
    if not from_ or not to:
        return True
    if from_ <= to:
        return from_ <= now_hhmm < to
    return now_hhmm >= from_ or now_hhmm < to


class MonitorService:
    def __init__(self, repo: CameraRepository, cameras: CameraService):
        self._repo, self._cameras = repo, cameras

    def get(self, cam_id: int, user_id: int) -> dict:
        cam = self._cameras.get_owned(cam_id, user_id)
        return {"enabled": bool(cam["monitor"]), "from": cam["monitor_from"] or "", "to": cam["monitor_to"] or "",
                "person_ready": person_ready(cam)}

    def update(self, cam_id: int, user_id: int, enabled: bool, from_: str = "", to: str = "") -> dict:
        cam = self._cameras.get_owned(cam_id, user_id)
        from_, to = (from_ or "").strip(), (to or "").strip()
        if bool(from_) != bool(to):
            raise ValidationError("Informe o início e o fim do horário (ou deixe os dois vazios para o dia todo).")
        for v in (from_, to):
            if v and not HHMM.match(v):
                raise ValidationError("Horário inválido. Use o formato HH:MM, por exemplo 11:00.")
        if from_ and from_ == to:
            raise ValidationError("O início e o fim do horário não podem ser iguais.")
        if enabled and not person_ready(cam):
            raise ValidationError("Para monitorar, ligue o reconhecimento e marque “Pessoa” em Objetos: "
                                  "sem isso não há o que medir.")
        self._repo.update_monitor(cam_id, user_id, enabled, from_, to)
        return self.get(cam_id, user_id)


class MonitorScheduler:
    """Mantém de pé os hubs das câmeras monitoradas. `tick` é a regra (testável com relógio injetado); a thread só chama."""

    def __init__(self, repo: CameraRepository, cameras: CameraService, zones: ZoneService, registry: HubRegistry,
                 settings: Settings):
        self._repo, self._cameras, self._zones, self._registry, self._cfg = repo, cameras, zones, registry, settings
        self._tz = _zone(settings.timezone)
        self._held: set = set()
        self._tick_lock = threading.Lock()   # `tick` também é chamado ao receber credenciais, fora da thread do agendador
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="monitor", daemon=True)
        self.last_errors: list = []

    def tick(self, now: Optional[datetime] = None) -> dict:
        with self._tick_lock:
            return self._tick(now)

    def _tick(self, now: Optional[datetime]) -> dict:
        """Uma passada: segura (ou recria) os hubs que devem estar ligados agora e solta o resto."""
        now = now or datetime.now(self._tz)
        hhmm = now.astimezone(self._tz).strftime("%H:%M")
        want, errors = {}, []
        for cam in self._repo.list_monitored():
            if not person_ready(cam):
                errors.append((cam["id"], "sem_pessoa"))     # reconhecimento mudou: sem "Pessoa" não há medida
                continue
            if self._cameras.needs_credentials(cam):
                errors.append((cam["id"], "aguardando_credenciais"))   # não insiste: evita bloquear a conta na câmera
                continue
            if in_window(hhmm, cam["monitor_from"], cam["monitor_to"]):
                want[cam["id"]] = cam
        for cam_id, cam in want.items():
            try:
                enabled, classes = parse_recognition(cam)
                self._registry.hold(cam_id, cam["user_id"], lambda c=cam: self._cameras.source_for(c),
                                    self._zones.load(cam_id), enabled, classes)
                self._held.add(cam_id)
            except Exception as e:  # uma câmera com problema não impede as outras
                errors.append((cam_id, type(e).__name__))
        released = [cid for cid in self._held if cid not in want]
        for cid in released:
            self._registry.unhold(cid)
            self._held.discard(cid)
        self.last_errors = errors
        return {"held": sorted(c for c in want if c in self._held), "released": sorted(released), "errors": errors}

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(5.0)
        for cid in list(self._held):
            self._registry.unhold(cid)
        self._held.clear()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                print(f"[-] monitor: {type(e).__name__}: {e}")
            self._stop.wait(self._cfg.monitor_tick_s)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        print(f"[!] Fuso '{name}' inválido: usando UTC. Defina ATENDEIO_TIMEZONE (ex.: America/Sao_Paulo).")
        return ZoneInfo("UTC")
