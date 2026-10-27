from fastapi import APIRouter, Depends, Request

from ..deps import current_user, get_container

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health(request: Request, user: dict = Depends(current_user)):
    """Saúde do servidor: atraso do laço de eventos (se > ~200 ms, algo está bloqueando) e do escritor de histórico."""
    c = get_container(request)
    w = c.flow_writer
    return {"loop_lag_ms": request.app.state.loop_lag_ms(), "cameras_active": c.registry.count(),
            "flow_writer": {"submitted": w.submitted, "written": w.written, "dropped": w.dropped, "errors": w.errors}}
