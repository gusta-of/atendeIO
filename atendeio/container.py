"""Composition root: o único lugar que sabe como montar as peças.

Nenhum módulo mantém singleton em variável global — tudo vive aqui e é injetado.
Os testes montam um Container próprio (banco temporário, dispositivos falsos)."""

from dataclasses import dataclass
from typing import Callable, Optional

from .config import Settings
from .db import Database
from .repositories.cameras import CameraRepository
from .repositories.sessions import SessionRepository
from .repositories.zones import ZoneRepository
from .repositories.users import UserRepository
from .security import SecretBox
from .services.auth import AuthService
from .services.cameras import CameraService
from .services.recognition import RecognitionService
from .services.zones import ZoneService
from .services.throttle import LoginThrottle
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
    detector: Detector
    registry: HubRegistry


def build_container(settings: Settings, *, device_lister: Optional[Callable] = None,
                    detector: Optional[Detector] = None) -> Container:
    db = Database(settings.db_path)
    db.init()
    box = SecretBox(settings.secret_key, settings.key_path)
    users, sessions, cameras = UserRepository(db), SessionRepository(db), CameraRepository(db)
    camera_service = CameraService(cameras, box, device_lister or list_v4l2_devices)
    detector = detector or Detector(settings.model_path, settings.conf_threshold, settings.seg_model_path)
    return Container(
        settings=settings,
        db=db,
        auth=AuthService(users, sessions,
                         LoginThrottle(settings.login_fail_limit, settings.login_fail_window_s), settings),
        cameras=camera_service,
        zones=ZoneService(ZoneRepository(db), camera_service, settings),
        recognition=RecognitionService(cameras, camera_service, settings),
        detector=detector,
        registry=HubRegistry(settings, detector),
    )
