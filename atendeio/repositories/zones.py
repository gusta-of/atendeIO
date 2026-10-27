import json
import sqlite3
import time
from contextlib import closing

from ..db import Database
from ..errors import ConflictError


def _row(r) -> dict:
    return {"id": r["id"], "name": r["name"], "kind": r["kind"], "shape": r["shape"],
            "angle": r["angle"], "margin": r["margin"], "points": json.loads(r["points"])}


class ZoneRepository:
    """Só chamado com `camera_id` já validado como pertencente ao utilizador."""

    def __init__(self, db: Database):
        self._db = db

    def list_for_camera(self, camera_id: int) -> list:
        with closing(self._db.connect()) as c:
            rows = c.execute("SELECT * FROM zones WHERE camera_id=? ORDER BY id", (camera_id,)).fetchall()
        return [_row(r) for r in rows]

    def exists(self, camera_id: int, zone_id: int) -> bool:
        with closing(self._db.connect()) as c:
            return c.execute("SELECT 1 FROM zones WHERE id=? AND camera_id=?",
                             (zone_id, camera_id)).fetchone() is not None

    def replace_all(self, camera_id: int, zones: list) -> list:
        """Substitui as zonas da câmera numa transação. Zona com `id` desta câmera é atualizada
        (ids se preservam); sem id — ou com id de OUTRA câmera — vira zona nova; as ausentes somem."""
        try:
            with closing(self._db.connect()) as c, c:
                mine = {r["id"] for r in c.execute("SELECT id FROM zones WHERE camera_id=?", (camera_id,))}
                keep = {z["id"] for z in zones if z.get("id") in mine}
                for zid in mine - keep:
                    c.execute("DELETE FROM zones WHERE id=?", (zid,))
                for zid in keep:  # nomes provisórios: trocar nomes entre zonas não bate no índice único
                    c.execute("UPDATE zones SET name=? WHERE id=?", (f"\x00{zid}", zid))
                for z in zones:
                    pts = json.dumps(z["points"])
                    if z.get("id") in keep:
                        c.execute("UPDATE zones SET name=?, kind=?, points=?, shape=?, angle=?, margin=? WHERE id=?",
                                  (z["name"], z["kind"], pts, z["shape"], z["angle"], z["margin"], z["id"]))
                    else:
                        c.execute("INSERT INTO zones(camera_id, name, kind, points, shape, angle, margin, created) "
                                  "VALUES (?,?,?,?,?,?,?,?)",
                                  (camera_id, z["name"], z["kind"], pts, z["shape"], z["angle"], z["margin"],
                                   time.time()))
        except sqlite3.IntegrityError:
            raise ConflictError("Já existe uma área com esse nome nesta câmera.")
        return self.list_for_camera(camera_id)
