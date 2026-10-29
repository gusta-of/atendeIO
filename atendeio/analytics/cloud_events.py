"""Contrato dos eventos enviados à cloud (v1). Puro: sem relógio, sem I/O.

Traduz o que o hub já produz (eventos `change` do barramento, lotes de fluxo, estado da câmera) para o envelope
descrito em `schemas/atendeio-event-1.json`. Só números e nomes de áreas: nunca imagens, URLs de câmera nem credenciais.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

SCHEMA_ID = "atendeio.event/1"

TABLE_STATUS_CHANGED = "table.status_changed"
TABLE_CLEANED = "table.cleaned"
AREA_PEOPLE_CHANGED = "area.people_changed"
CAMERA_STATUS_CHANGED = "camera.status_changed"
FLOW_BATCH = "flow.batch"
STATE_SNAPSHOT = "state.snapshot"


def iso_utc(ts_s: float) -> str:
    return datetime.fromtimestamp(ts_s, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def envelope(device_id: str, type_: str, data: dict, ts_s: float, camera: Optional[dict] = None,
             event_id: Optional[str] = None) -> dict:
    ev = {"schema": SCHEMA_ID, "event_id": event_id or str(uuid.uuid4()), "device_id": device_id,
          "occurred_at": iso_utc(ts_s), "type": type_, "data": data}
    if camera is not None:
        ev["camera"] = {"id": int(camera["id"]), "name": str(camera["name"])}
    return ev


def from_change(device_id: str, camera: dict, ev: dict) -> Optional[dict]:
    """Evento `change` do barramento da câmera → evento da cloud. None se não interessa à cloud."""
    name, d, ts = ev["event"], ev["data"], ev["ts"] / 1000
    if name == "area.status":
        data = {"zone_id": d["id"], "name": d["name"], "from": d.get("from"), "to": d["to"],
                "people": int(d.get("people") or 0)}
        return envelope(device_id, TABLE_STATUS_CHANGED, data, ts, camera)
    if name == "area.cleaned":
        return envelope(device_id, TABLE_CLEANED, {"zone_id": d["id"], "name": d.get("name")}, ts, camera)
    if name == "area.people":
        data = {"zone_id": d["id"], "name": d["name"], "kind": d["kind"], "from": d.get("from"), "to": d.get("to")}
        return envelope(device_id, AREA_PEOPLE_CHANGED, data, ts, camera)
    if name in ("camera.online", "camera.offline"):
        data = {"online": name == "camera.online", "reason": d.get("reason")}
        return envelope(device_id, CAMERA_STATUS_CHANGED, data, ts, camera)
    return None


def from_flow_batch(device_id: str, camera: dict, batch: dict, ts_s: float) -> dict:
    """Lote do `FlowAggregator.flush()`. É uma soma parcial: a cloud acumula por chave."""
    minutes = [{"minute": int(k), "samples": r[0], "people_sum": r[1], "people_max": r[2], "people_min": r[3]}
               for k, r in sorted(batch["minute"].items())]
    hours = [{"hour": int(k), "samples": r[0], "people_sum": r[1], "people_max": r[2], "people_min": r[3]}
             for k, r in sorted(batch["hour"].items())]
    areas = [{"zone_id": int(zone), "hour": int(hour), "name": r[3], "kind": r[4],
              "samples": r[0], "people_sum": r[1], "people_max": r[2]}
             for (zone, hour), r in sorted(batch["area"].items())]
    return envelope(device_id, FLOW_BATCH, {"minutes": minutes, "hours": hours, "areas": areas}, ts_s, camera)


def snapshot(device_id: str, camera: dict, state: dict, ts_s: float) -> dict:
    """Retrato da câmera (estado do hub). Deixa a cloud recuperar-se de eventos perdidos."""
    areas = []
    for a in state.get("areas", []):
        item = {"zone_id": a["id"], "name": a["name"], "kind": a["kind"], "people": int(a.get("people") or 0)}
        if a.get("status") is not None:
            item["status"] = a["status"]
        if a.get("seconds") is not None:
            item["seconds"] = a["seconds"]
        areas.append(item)
    data = {"online": bool(state.get("online")), "people": state.get("people"), "areas": areas}
    return envelope(device_id, STATE_SNAPSHOT, data, ts_s, camera)
