from fastapi import APIRouter, Depends, Request

from ...services import rtsp
from ..deps import current_user, get_container
from fastapi.concurrency import run_in_threadpool

from ..schemas import CameraCredentials, LocalRequest, RtspRequest

router = APIRouter(prefix="/api", tags=["cameras"])


@router.get("/cameras")
def list_cameras(request: Request, user: dict = Depends(current_user)):
    return {"cameras": get_container(request).cameras.list(user["id"]), "presets": rtsp.PRESETS}


@router.post("/cameras/rtsp")
def add_rtsp(body: RtspRequest, request: Request, user: dict = Depends(current_user)):
    """Cliente informa IP + usuário + senha; o servidor monta a URL RTSP e cadastra."""
    svc = get_container(request).cameras
    cam = svc.add_rtsp(user["id"], body.name, body.host, body.port,
                       body.username, body.password, body.path)
    ok = svc.probe(svc.get_owned(cam["id"], user["id"]))  # avisa IP/senha errados, sem bloquear
    warning = None if ok else "Cadastrada, mas não consegui conectar agora. Confira IP, usuário e senha."
    return {"camera": cam, "warning": warning}


@router.put("/cameras/{cam_id}/credentials")
async def set_credentials(cam_id: int, body: CameraCredentials, request: Request, user: dict = Depends(current_user)):
    """Usuário e senha da câmera RTSP depois de ligar o computador. Só em memória: nunca vão para o disco."""
    c = get_container(request)
    cam = await run_in_threadpool(c.cameras.set_credentials, cam_id, user["id"], body.username, body.password)
    await run_in_threadpool(c.scheduler.tick)   # câmera monitorada volta a ser analisada já, sem esperar o próximo ciclo
    return {"camera": cam}


@router.get("/local-devices")
def local_devices(request: Request, user: dict = Depends(current_user)):
    return {"devices": get_container(request).cameras.local_devices(user["id"])}


@router.post("/cameras/local")
def add_local(body: LocalRequest, request: Request, user: dict = Depends(current_user)):
    return {"camera": get_container(request).cameras.add_local(user["id"], body.ref, body.name)}


@router.delete("/cameras/{cam_id}")
def delete_camera(cam_id: int, request: Request, user: dict = Depends(current_user)):
    c = get_container(request)
    c.cameras.delete(cam_id, user["id"])
    c.registry.stop_camera(cam_id)
    return {"deleted": cam_id}
