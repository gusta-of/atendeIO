import time
from contextlib import closing
from typing import Optional

from ..db import Database


class SessionRepository:
    def __init__(self, db: Database):
        self._db = db

    def create(self, token_hash: str, user_id: int, ttl_s: int) -> None:
        now = time.time()
        with closing(self._db.connect()) as c, c:
            c.execute("DELETE FROM sessions WHERE expires < ?", (now,))
            c.execute("INSERT INTO sessions(token_hash, user_id, expires) VALUES (?,?,?)",
                      (token_hash, user_id, now + ttl_s))

    def get_user(self, token_hash: str) -> Optional[dict]:
        with closing(self._db.connect()) as c:
            row = c.execute(
                "SELECT u.id, u.username FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash=? AND s.expires > ?", (token_hash, time.time())).fetchone()
        return dict(row) if row else None

    def delete(self, token_hash: str) -> None:
        with closing(self._db.connect()) as c, c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
