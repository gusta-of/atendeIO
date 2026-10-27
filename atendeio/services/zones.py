"""Áreas do salão por câmera. Sempre passa por `CameraService.get_owned` primeiro:
área de câmera alheia é 404, igual a uma inexistente."""

import math
from typing import List

from ..analytics.geometry import polygon_area
from ..analytics.zones import KINDS, Zone
from ..config import Settings
from ..errors import NotFoundError, ValidationError
from ..repositories.zones import ZoneRepository
from .cameras import CameraService

SHAPES = ("poly", "rect", "square", "ellipse", "triangle")
DEFAULT_SEAT_MARGIN = 0.06   # sombra de assentos da mesa: 6% da altura da imagem
MAX_SEAT_MARGIN = 0.30
MIN_AREA = 0.0005  # ~2% x 2% da imagem: menor que isso é clique perdido, não uma mesa


def to_zone(row: dict) -> Zone:
    return Zone(row["id"], row["name"], row["kind"], tuple((float(x), float(y)) for x, y in row["points"]),
                float(row.get("margin") or 0.0))


def _clean(raw: dict) -> dict:
    name = " ".join(str(raw.get("name", "")).split())
    if not 1 <= len(name) <= 40:
        raise ValidationError("O nome da área deve ter de 1 a 40 caracteres.")
    if raw.get("kind") not in KINDS:
        raise ValidationError(f"Tipo de área inválido (use: {', '.join(KINDS)}).")
    shape = raw.get("shape") or "poly"
    if shape not in SHAPES:
        raise ValidationError(f"Forma inválida (use: {', '.join(SHAPES)}).")
    try:
        angle = float(raw.get("angle") or 0)
    except (TypeError, ValueError):
        raise ValidationError(f"Ângulo inválido na área '{name}'.")
    if not (math.isfinite(angle) and -720 <= angle <= 720):
        raise ValidationError(f"Ângulo inválido na área '{name}'.")
    angle = round(((angle + 180) % 360) - 180, 2)  # normaliza pra [-180, 180)
    pts = raw.get("points")
    if not isinstance(pts, (list, tuple)) or not 3 <= len(pts) <= 32:
        raise ValidationError(f"A área '{name}' precisa de 3 a 32 pontos.")
    clean = []
    for p in pts:
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            raise ValidationError(f"Ponto inválido na área '{name}'.")
        if not (math.isfinite(x) and math.isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1):
            raise ValidationError(f"Ponto fora da imagem na área '{name}'.")
        clean.append([round(x, 5), round(y, 5)])
    if polygon_area(clean) < MIN_AREA:
        raise ValidationError(f"A área '{name}' é pequena demais.")
    margin = raw.get("margin")
    if raw["kind"] != "mesa":
        margin = 0.0                                   # só mesa tem área de assentos
    elif margin is None:
        margin = DEFAULT_SEAT_MARGIN                   # clientes antigos / mesa nova
    else:
        try:
            margin = float(margin)
        except (TypeError, ValueError):
            raise ValidationError(f"Área de assentos inválida em '{name}'.")
        if not (math.isfinite(margin) and 0 <= margin <= MAX_SEAT_MARGIN):
            raise ValidationError(f"A área de assentos de '{name}' deve ficar entre 0% e {int(MAX_SEAT_MARGIN * 100)}%.")
    zid = raw.get("id")
    return {"id": zid if isinstance(zid, int) else None, "name": name, "kind": raw["kind"],
            "shape": shape, "angle": angle, "margin": round(margin, 4), "points": clean}


class ZoneService:
    def __init__(self, zones: ZoneRepository, cameras: CameraService, settings: Settings):
        self._zones, self._cameras, self._cfg = zones, cameras, settings

    def list(self, cam_id: int, user_id: int) -> List[dict]:
        self._cameras.get_owned(cam_id, user_id)
        return self._zones.list_for_camera(cam_id)

    def load(self, cam_id: int) -> List[Zone]:
        """Para o pipeline (já autorizado): zonas como objetos de domínio."""
        return [to_zone(r) for r in self._zones.list_for_camera(cam_id)]

    def replace(self, cam_id: int, user_id: int, zones: List[dict]) -> List[dict]:
        self._cameras.get_owned(cam_id, user_id)
        if len(zones) > self._cfg.max_zones_per_camera:
            raise ValidationError(f"Máximo de {self._cfg.max_zones_per_camera} áreas por câmera.")
        cleaned = [_clean(z) for z in zones]
        names = [z["name"].lower() for z in cleaned]
        if len(set(names)) != len(names):
            raise ValidationError("Há áreas com o mesmo nome. Use nomes diferentes (ex.: Mesa 1, Mesa 2).")
        return self._zones.replace_all(cam_id, cleaned)

    def ensure_exists(self, cam_id: int, zone_id: int, user_id: int) -> None:
        self._cameras.get_owned(cam_id, user_id)
        if not self._zones.exists(cam_id, zone_id):
            raise NotFoundError("Área não encontrada.")
