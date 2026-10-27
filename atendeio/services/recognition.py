"""Quais objetos o YOLO reconhece em cada câmera (chave geral + classes habilitadas).

Padrão de uma câmera nova: chave LIGADA e NENHUMA classe marcada — o utilizador escolhe só o que quer.
Sempre por dono: a configuração de câmera alheia é 404."""

import json
from typing import List

from ..config import Settings
from ..errors import ValidationError
from ..repositories.cameras import CameraRepository
from ..vision import classes as coco
from .cameras import CameraService


def parse(cam: dict) -> tuple:
    """(enabled, frozenset de ids) a partir da linha da câmera."""
    try:
        ids = frozenset(int(i) for i in json.loads(cam.get("classes") or "[]"))
    except (ValueError, TypeError):
        ids = frozenset()
    return bool(cam.get("recognition", 1)), ids


class RecognitionService:
    def __init__(self, cameras: CameraRepository, camera_service: CameraService, settings: Settings):
        self._repo, self._cameras, self._cfg = cameras, camera_service, settings

    def catalog(self) -> dict:
        """Todas as classes do YOLO + atalhos (presets) — não depende de câmera."""
        return {
            "classes": coco.catalog(),
            "presets": [{
                "id": "restaurante", "label": "Restaurante",
                "description": "Pessoas e itens de mesa (copo, taça, garrafa, tigela e talheres)",
                "classes": coco.ids_for(("person",) + tuple(self._cfg.table_item_classes)),
            }],
        }

    def get(self, cam_id: int, user_id: int) -> dict:
        enabled, ids = parse(self._cameras.get_owned(cam_id, user_id))
        return {"enabled": enabled, "classes": sorted(ids)}

    def update(self, cam_id: int, user_id: int, enabled: bool, classes: List[int]) -> dict:
        self._cameras.get_owned(cam_id, user_id)
        if len(classes) > coco.NUM_CLASSES:
            raise ValidationError("Lista de objetos inválida.")
        for i in classes:
            if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < coco.NUM_CLASSES:
                raise ValidationError("Objeto desconhecido na lista.")
        unique = sorted(set(classes))
        self._repo.update_recognition(cam_id, user_id, bool(enabled), unique)
        return {"enabled": bool(enabled), "classes": unique}
