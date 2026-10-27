from fastapi import APIRouter, Depends, Request

from ..deps import current_user, get_container
from ..schemas import RecognitionRequest

router = APIRouter(prefix="/api", tags=["recognition"])


@router.get("/recognition/classes")
def catalog(request: Request, user: dict = Depends(current_user)):
    """Todas as classes que o YOLO reconhece (para o modal de seleção) + atalhos."""
    return get_container(request).recognition.catalog()


@router.get("/cameras/{cam_id}/recognition")
def get_recognition(cam_id: int, request: Request, user: dict = Depends(current_user)):
    return get_container(request).recognition.get(cam_id, user["id"])


@router.put("/cameras/{cam_id}/recognition")
def set_recognition(cam_id: int, body: RecognitionRequest, request: Request, user: dict = Depends(current_user)):
    """Liga/desliga o reconhecimento e escolhe os objetos. Se a câmera está ao vivo, vale na hora."""
    c = get_container(request)
    saved = c.recognition.update(cam_id, user["id"], body.enabled, body.classes)
    c.registry.set_recognition(cam_id, saved["enabled"], frozenset(saved["classes"]))
    return saved
