import json
import sqlite3
import time
from contextlib import closing
from typing import Optional

from ..db import Database
from ..errors import ConflictError


class CameraRepository:
    """Toda consulta de câmera é filtrada por dono — não existe busca global por id."""

    def __init__(self, db: Database):
        self._db = db

    def add(self, user_id: int, name: str, kind: str, ref: str, secret: Optional[bytes] = None) -> int:
        try:
            with closing(self._db.connect()) as c, c:
                return c.execute(
                    "INSERT INTO cameras(user_id, name, kind, ref, secret, created) VALUES (?,?,?,?,?,?)",
                    (user_id, name, kind, ref, secret, time.time())).lastrowid
        except sqlite3.IntegrityError:
            raise ConflictError("Essa câmera já está cadastrada ou em uso.")

    def wipe_secrets(self) -> int:
        """Apaga qualquer credencial que tenha sobrado no banco (modo desktop não guarda usuário/senha)."""
        with closing(self._db.connect()) as c, c:
            return c.execute("UPDATE cameras SET secret=NULL WHERE secret IS NOT NULL").rowcount

    def list_for_user(self, user_id: int) -> list:
        with closing(self._db.connect()) as c:
            rows = c.execute("SELECT * FROM cameras WHERE user_id=? ORDER BY id", (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_for_user(self, cam_id: int, user_id: int) -> Optional[dict]:
        with closing(self._db.connect()) as c:
            row = c.execute("SELECT * FROM cameras WHERE id=? AND user_id=?",
                            (cam_id, user_id)).fetchone()
        return dict(row) if row else None

    def delete(self, cam_id: int, user_id: int) -> bool:
        with closing(self._db.connect()) as c, c:
            return c.execute("DELETE FROM cameras WHERE id=? AND user_id=?",
                             (cam_id, user_id)).rowcount > 0

    def update_recognition(self, cam_id: int, user_id: int, enabled: bool, classes: list) -> bool:
        with closing(self._db.connect()) as c, c:
            return c.execute("UPDATE cameras SET recognition=?, classes=? WHERE id=? AND user_id=?",
                             (1 if enabled else 0, json.dumps(classes), cam_id, user_id)).rowcount > 0

    def update_monitor(self, cam_id: int, user_id: int, enabled: bool, from_: Optional[str], to: Optional[str]) -> bool:
        with closing(self._db.connect()) as c, c:
            return c.execute("UPDATE cameras SET monitor=?, monitor_from=?, monitor_to=? WHERE id=? AND user_id=?",
                             (1 if enabled else 0, from_ or None, to or None, cam_id, user_id)).rowcount > 0

    def update_basic(self, cam_id: int, user_id: int, name: str, ref: str) -> bool:
        """Nome e endereço (`ref`, sem credenciais). Conflita com outra câmera do mesmo dono no mesmo endereço."""
        try:
            with closing(self._db.connect()) as c, c:
                return c.execute("UPDATE cameras SET name=?, ref=? WHERE id=? AND user_id=?",
                                 (name, ref, cam_id, user_id)).rowcount > 0
        except sqlite3.IntegrityError:
            raise ConflictError("Já existe uma câmera cadastrada nesse endereço.")

    def get_fps(self, cam_id: int) -> tuple:
        """(fps_view, fps_monitor) da câmera; None = usar o padrão do sistema. Sem filtro de dono: só o motor consulta."""
        with closing(self._db.connect()) as c:
            row = c.execute("SELECT fps_view, fps_monitor FROM cameras WHERE id=?", (cam_id,)).fetchone()
        return (row["fps_view"], row["fps_monitor"]) if row else (None, None)

    def update_fps(self, cam_id: int, user_id: int, fps_view: Optional[float], fps_monitor: Optional[float]) -> bool:
        with closing(self._db.connect()) as c, c:
            return c.execute("UPDATE cameras SET fps_view=?, fps_monitor=? WHERE id=? AND user_id=?",
                             (fps_view, fps_monitor, cam_id, user_id)).rowcount > 0

    def list_monitored(self) -> list:
        """Todas as câmeras com monitoramento ligado (de todos os utilizadores): é o agendador do servidor que usa."""
        with closing(self._db.connect()) as c:
            return [dict(r) for r in c.execute("SELECT * FROM cameras WHERE monitor=1 ORDER BY id")]

    def local_refs(self, *, owned_by: Optional[int] = None, not_owned_by: Optional[int] = None) -> set:
        sql, args = "SELECT ref FROM cameras WHERE kind='local'", []
        if owned_by is not None:
            sql, args = sql + " AND user_id=?", [owned_by]
        if not_owned_by is not None:
            sql, args = sql + " AND user_id<>?", [not_owned_by]
        with closing(self._db.connect()) as c:
            return {r["ref"] for r in c.execute(sql, args).fetchall()}
