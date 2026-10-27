import sqlite3
import time
from contextlib import closing
from typing import Optional

from ..db import Database
from ..errors import ConflictError


class UserRepository:
    def __init__(self, db: Database):
        self._db = db

    def create(self, username: str, pw_hash: str) -> int:
        try:
            with closing(self._db.connect()) as c, c:
                return c.execute(
                    "INSERT INTO users(username, pw_hash, created) VALUES (?,?,?)",
                    (username, pw_hash, time.time())).lastrowid
        except sqlite3.IntegrityError:
            raise ConflictError("Esse usuário já existe.")

    def get_by_username(self, username: str) -> Optional[dict]:
        with closing(self._db.connect()) as c:
            row = c.execute("SELECT id, username, pw_hash FROM users WHERE username=?",
                            (username,)).fetchone()
        return dict(row) if row else None

    def count(self) -> int:
        with closing(self._db.connect()) as c:
            return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
