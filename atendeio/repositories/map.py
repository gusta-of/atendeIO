"""Layout do Mapa do ambiente: posição e escala da zona de cada câmera. Sempre por dono (via junção com `cameras`)."""

import json
from contextlib import closing
from typing import Dict, Tuple

from ..db import Database


class MapRepository:
    def __init__(self, db: Database):
        self._db = db

    def all_for_user(self, user_id: int) -> Dict[int, Tuple[float, float, float, float]]:
        with closing(self._db.connect()) as c:
            rows = c.execute("SELECT m.camera_id, m.x, m.y, m.scale, m.rot FROM map_layout m JOIN cameras c ON c.id = m.camera_id "
                             "WHERE c.user_id = ?", (user_id,)).fetchall()
        return {r["camera_id"]: (r["x"], r["y"], r["scale"], r["rot"]) for r in rows}

    def upsert(self, camera_id: int, x: float, y: float, scale: float, rot: float = 0.0) -> None:
        """Quem chama já conferiu o dono da câmera (CameraService.get_owned)."""
        with closing(self._db.connect()) as c, c:
            c.execute("INSERT INTO map_layout(camera_id, x, y, scale, rot) VALUES (?,?,?,?,?) "
                      "ON CONFLICT(camera_id) DO UPDATE SET x=excluded.x, y=excluded.y, scale=excluded.scale, rot=excluded.rot",
                      (camera_id, x, y, scale, rot))

    def clear_for_user(self, user_id: int) -> int:
        with closing(self._db.connect()) as c, c:
            return c.execute("DELETE FROM map_layout WHERE camera_id IN (SELECT id FROM cameras WHERE user_id = ?)",
                             (user_id,)).rowcount

    def calibrations_for_user(self, user_id: int) -> Dict[int, dict]:
        with closing(self._db.connect()) as c:
            rows = c.execute("SELECT m.camera_id, m.data FROM map_calibration m JOIN cameras c ON c.id = m.camera_id "
                             "WHERE c.user_id = ?", (user_id,)).fetchall()
        return {r["camera_id"]: json.loads(r["data"]) for r in rows}

    def set_calibration(self, camera_id: int, data: dict) -> None:
        """Quem chama já conferiu o dono da câmera."""
        with closing(self._db.connect()) as c, c:
            c.execute("INSERT INTO map_calibration(camera_id, data) VALUES (?,?) "
                      "ON CONFLICT(camera_id) DO UPDATE SET data=excluded.data", (camera_id, json.dumps(data)))

    def clear_calibration(self, camera_id: int) -> None:
        with closing(self._db.connect()) as c, c:
            c.execute("DELETE FROM map_calibration WHERE camera_id = ?", (camera_id,))
