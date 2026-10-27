from fastapi import APIRouter, Depends, Request

from ...analytics.zones import KINDS
from ...services.zones import to_zone
from ..deps import current_user, get_container
from ..schemas import ZonesRequest

router = APIRouter(prefix="/api/cameras/{cam_id}", tags=["zones"])


@router.get("/zones")
def list_zones(cam_id: int, request: Request, user: dict = Depends(current_user)):
    return {"zones": get_container(request).zones.list(cam_id, user["id"]), "kinds": KINDS}


@router.put("/zones")
def replace_zones(cam_id: int, body: ZonesRequest, request: Request, user: dict = Depends(current_user)):
    """O editor salva todas as áreas de uma vez. Se a câmera está ao vivo, aplica na hora."""
    c = get_container(request)
    saved = c.zones.replace(cam_id, user["id"], [z.model_dump() for z in body.zones])
    c.registry.set_zones(cam_id, [to_zone(r) for r in saved])
    return {"zones": saved}


@router.post("/zones/{zone_id}/clean")
def mark_clean(cam_id: int, zone_id: int, request: Request, user: dict = Depends(current_user)):
    """Confirmação manual: a equipe limpou a mesa."""
    c = get_container(request)
    c.zones.ensure_exists(cam_id, zone_id, user["id"])
    c.registry.mark_clean(cam_id, zone_id)
    return {"ok": True}
