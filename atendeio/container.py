"""Composition root: o único lugar que sabe como montar as peças.

Nenhum módulo mantém singleton em variável global — tudo vive aqui e é injetado.
Os testes montam um Container próprio (banco temporário, dispositivos falsos)."""

from dataclasses import dataclass
from typing import Callable, Optional

from .config import Settings
from .db import Database
from .repositories.cameras import CameraRepository
from .repositories.cloud import CloudConfigRepository, OutboxRepository
from .repositories.flow import FlowRepository
from .repositories.sessions import SessionRepository
from .repositories.zones import ZoneRepository
from .repositories.users import UserRepository
from .security import SecretBox
from .services.auth import AuthService
from .services.cameras import CameraService
from .services.cloud import CloudService
from .services.flow import FlowService
from .services.monitor import MonitorScheduler, MonitorService
from .services.recognition import RecognitionService
from .services.tickets import TicketService
from .services.zones import ZoneService
from .services.throttle import LoginThrottle
from .streaming.flow_writer import FlowWriter
from .streaming.registry import HubRegistry
from .streaming.uploader import CloudExporter
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
    cloud: CloudService
    exporter: CloudExporter
    monitor: MonitorService
    scheduler: MonitorScheduler
    detector: Detector
    registry: HubRegistry


def build_container(settings: Settings, *, device_lister: Optional[Callable] = None,
                    detector: Optional[Detector] = None, cloud_post: Optional[Callable] = None) -> Container:
    db = Database(settings.db_path)
    db.init()
    box = SecretBox(settings.secret_key, settings.key_path)
    users, sessions, cameras = UserRepository(db), SessionRepository(db), CameraRepository(db)
    camera_service = CameraService(cameras, box, device_lister or list_v4l2_devices)
    detector = detector or Detector(settings.model_path, settings.conf_threshold, settings.seg_model_path)
    flow_repo = FlowRepository(db)
    flow_writer = FlowWriter(flow_repo, settings)
    cloud = CloudService(CloudConfigRepository(db), box)
    exporter_kwargs = {"post": cloud_post} if cloud_post else {}
    exporter = CloudExporter(cloud, OutboxRepository(db), cameras.get_for_user,
                             lambda: registry.all_states(), settings, **exporter_kwargs)
    # hubs só enfileiram (fluxo no escritor, eventos no exportador); quem grava e envia são as threads deles
    registry = HubRegistry(settings, detector, flow_sink=flow_writer.submit, cloud_sink=exporter.submit)
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
        flow=FlowService(flow_repo, camera_service, settings),
        tickets=TicketService(box.derive("media-tickets"), settings.ticket_ttl_s),
        flow_writer=flow_writer,
        cloud=cloud,
        exporter=exporter,
        monitor=MonitorService(cameras, camera_service),
        scheduler=MonitorScheduler(cameras, camera_service, zones, registry, settings),
    )
