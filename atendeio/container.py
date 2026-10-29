"""Composition root: o único lugar que sabe como montar as peças.

Nenhum módulo mantém singleton em variável global — tudo vive aqui e é injetado.
Os testes montam um Container próprio (banco temporário, dispositivos falsos)."""

from dataclasses import dataclass
from typing import Callable, Optional

from .config import Settings
from .db import Database
from .repositories.cameras import CameraRepository
from .repositories.flow import FlowRepository
from .repositories.sessions import SessionRepository
from .repositories.zones import ZoneRepository
from .repositories.users import UserRepository
from .security import SecretBox
from .services.auth import AuthService
from .services.credentials import SessionCredentials
from .services.cameras import CameraService
from .services.flow import FlowService
from .services.monitor import MonitorScheduler, MonitorService
from .services.recognition import RecognitionService
from .services.tickets import TicketService
from .services.zones import ZoneService
from .services.throttle import LoginThrottle
from .streaming.flow_writer import FlowWriter
from .streaming.registry import HubRegistry
from .vision.detector import Detector
from .vision.sources import list_v4l2_devices


@dataclass
class Container:
    settings: Settings
    db: Database
    auth: AuthService
    cameras: CameraService
    zones: ZoneService
    recognition: RecognitionService
    flow: FlowService
    tickets: TicketService
    flow_writer: FlowWriter
    monitor: MonitorService
    scheduler: MonitorScheduler
    detector: Detector
    registry: HubRegistry
    credentials: Optional[SessionCredentials] = None   # só no modo desktop


def build_container(settings: Settings, *, device_lister: Optional[Callable] = None,
                    detector: Optional[Detector] = None) -> Container:
    db = Database(settings.db_path)
    db.init()
    box = SecretBox(settings.secret_key, settings.key_path)
    users, sessions, cameras = UserRepository(db), SessionRepository(db), CameraRepository(db)
    credentials = None
    if settings.desktop:
        cameras.wipe_secrets()   # nada de usuário/senha em disco, nem de versões antigas
        credentials = SessionCredentials(settings.run_dir / "creds.bin", settings.run_key)
    camera_service = CameraService(cameras, box, device_lister or list_v4l2_devices, credentials)
    detector = detector or Detector(settings.model_path, settings.conf_threshold, settings.seg_model_path)
    flow_repo = FlowRepository(db)
    flow_writer = FlowWriter(flow_repo, settings)
    registry = HubRegistry(settings, detector, flow_sink=flow_writer.submit)   # hubs só enfileiram; quem grava é o escritor
    zones = ZoneService(ZoneRepository(db), camera_service, settings)
    return Container(
        settings=settings,
        db=db,
        auth=AuthService(users, sessions,
                         LoginThrottle(settings.login_fail_limit, settings.login_fail_window_s), settings),
        cameras=camera_service,
        zones=zones,
        recognition=RecognitionService(cameras, camera_service, settings),
        detector=detector,
        registry=registry,
        credentials=credentials,
        flow=FlowService(flow_repo, camera_service, settings),
        tickets=TicketService(box.derive("media-tickets"), settings.ticket_ttl_s),
        flow_writer=flow_writer,
        monitor=MonitorService(cameras, camera_service),
        scheduler=MonitorScheduler(cameras, camera_service, zones, registry, settings),
    )
