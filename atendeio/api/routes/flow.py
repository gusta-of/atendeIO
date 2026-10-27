from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from ...errors import ValidationError
from ..deps import current_user, get_container

router = APIRouter(prefix="/api/cameras/{cam_id}", tags=["flow"])


def _span(c, from_: Optional[str], to: Optional[str], days: Optional[int]):
    """`days=N`: os últimos N dias terminando HOJE no fuso do restaurante (o navegador pode estar em outro fuso)."""
    if days is not None and not (from_ or to):
        if not 1 <= days <= 731:
            raise ValidationError("Número de dias inválido (de 1 a 731).")
        end = c.flow.today()
        return end - timedelta(days=days - 1), end
    return _date(from_), _date(to)


def _date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError("Data inválida. Use o formato AAAA-MM-DD.")


@router.get("/flow")
def flow(cam_id: int, request: Request, from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
         days: Optional[int] = None, hour_from: int = 0, hour_to: int = 24, user: dict = Depends(current_user)):
    """Análise de fluxo do período (por hora, dia, dia da semana, mapa de calor, áreas e insights)."""
    c = get_container(request)
    d_from, d_to = _span(c, from_, to, days)
    return c.flow.report(cam_id, user["id"], d_from, d_to, hour_from, hour_to)


@router.get("/flow/day")
def flow_day(cam_id: int, request: Request, date_: Optional[str] = Query(None, alias="date"),
             user: dict = Depends(current_user)):
    """Série de um dia (de 5 em 5 minutos)."""
    return get_container(request).flow.day(cam_id, user["id"], _date(date_))


@router.get("/flow.csv")
def flow_csv(cam_id: int, request: Request, from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
             days: Optional[int] = None, hour_from: int = 0, hour_to: int = 24, user: dict = Depends(current_user)):
    c = get_container(request)
    d_from, d_to = _span(c, from_, to, days)
    text = c.flow.csv(cam_id, user["id"], d_from, d_to, hour_from, hour_to)
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="fluxo-camera-{cam_id}.csv"'})


@router.get("/monitor")
def get_monitor(cam_id: int, request: Request, user: dict = Depends(current_user)):
    return get_container(request).monitor.get(cam_id, user["id"])


@router.put("/monitor")
def set_monitor(cam_id: int, body: dict, request: Request, user: dict = Depends(current_user)):
    """Liga/desliga o monitoramento contínuo (e o horário de funcionamento: HH:MM, no fuso do restaurante)."""
    c = get_container(request)
    out = c.monitor.update(cam_id, user["id"], bool(body.get("enabled")), str(body.get("from") or ""),
                           str(body.get("to") or ""))
    c.scheduler.tick()   # vale na hora, sem esperar a próxima passada
    return out
