"""Layout do Mapa do ambiente: posição e escala da zona de cada câmera. Sempre por dono (via junção com `cameras`)."""

from contextlib import closing
from typing import Dict, Tuple

from ..db import Database


class MapRepository:
    def __init__(self, db: Database):
        self._db = db

    def all_for_user(self, user_id: int) -> Dict[int, Tuple[float, float, float]]:
        with closing(self._db.connect()) as c:
            rows = c.execute("SELECT m.camera_id, m.x, m.y, m.scale FROM map_layout m JOIN cameras c ON c.id = m.camera_id "
                             "WHERE c.user_id = ?", (user_id,)).fetchall()
        return {r["camera_id"]: (r["x"], r["y"], r["scale"]) for r in rows}

    def upsert(self, camera_id: int, x: float, y: float, scale: float) -> None:
        """Quem chama já conferiu o dono da câmera (CameraService.get_owned)."""
        with closing(self._db.connect()) as c, c:
            c.execute("INSERT INTO map_layout(camera_id, x, y, scale) VALUES (?,?,?,?) "
                      "ON CONFLICT(camera_id) DO UPDATE SET x=excluded.x, y=excluded.y, scale=excluded.scale",
                      (camera_id, x, y, scale))

    def clear_for_user(self, user_id: int) -> int:
        with closing(self._db.connect()) as c, c:
            return c.execute("DELETE FROM map_layout WHERE camera_id IN (SELECT id FROM cameras WHERE user_id = ?)",
                             (user_id,)).rowcount
