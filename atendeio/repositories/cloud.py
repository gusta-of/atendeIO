"""SQL do envio à cloud: configuração do dispositivo e fila de saída (outbox)."""

import time
import uuid
from contextlib import closing
from typing import Iterable, Optional

from ..db import Database


class CloudConfigRepository:
    def __init__(self, db: Database):
        self._db = db

    def get(self) -> dict:
        """A configuração; na primeira vez cria a linha com um `device_id` novo (desligado, sem URL)."""
        with closing(self._db.connect()) as c, c:
            c.execute("INSERT OR IGNORE INTO cloud_config(id, enabled, url, device_id) VALUES (1, 0, '', ?)",
                      (str(uuid.uuid4()),))
            return dict(c.execute("SELECT * FROM cloud_config WHERE id=1").fetchone())

    def update(self, enabled: bool, url: str, api_key: Optional[bytes] = None, keep_key: bool = True) -> None:
        """`keep_key`: mantém a chave já guardada (a API nunca devolve a chave, então o cliente só a reenvia se mudar)."""
        self.get()
        with closing(self._db.connect()) as c, c:
            if keep_key:
                c.execute("UPDATE cloud_config SET enabled=?, url=? WHERE id=1", (1 if enabled else 0, url))
            else:
                c.execute("UPDATE cloud_config SET enabled=?, url=?, api_key=? WHERE id=1",
                          (1 if enabled else 0, url, api_key))


class OutboxRepository:
    """Fila persistente: um evento só sai daqui depois de a cloud confirmar. Reiniciar o PC não perde nada."""

    def __init__(self, db: Database):
        self._db = db

    def add_many(self, items: Iterable[tuple]) -> int:
        """items: [(event_id, payload_json)]. Um event_id repetido é ignorado."""
        now = time.time()
        rows = [(eid, now, payload) for eid, payload in items]
        if not rows:
            return 0
        with closing(self._db.connect()) as c, c:
            before = c.total_changes
            c.executemany("INSERT OR IGNORE INTO outbox(event_id, created, payload) VALUES (?,?,?)", rows)
            return c.total_changes - before

    def pending(self, limit: int) -> list:
        with closing(self._db.connect()) as c:
            rows = c.execute("SELECT id, event_id, payload, attempts FROM outbox WHERE state='pending' "
                             "ORDER BY id LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def delete(self, ids: list) -> None:
        if ids:
            with closing(self._db.connect()) as c, c:
                c.executemany("DELETE FROM outbox WHERE id=?", [(i,) for i in ids])

    def mark_attempt(self, ids: list) -> None:
        if ids:
            with closing(self._db.connect()) as c, c:
                c.executemany("UPDATE outbox SET attempts = attempts + 1 WHERE id=?", [(i,) for i in ids])

    def reject(self, ids: list) -> None:
        """A cloud recusou o conteúdo (4xx): não adianta reenviar. Fica guardado uns dias para diagnóstico."""
        if ids:
            with closing(self._db.connect()) as c, c:
                c.executemany("UPDATE outbox SET state='rejected' WHERE id=?", [(i,) for i in ids])

    def counts(self) -> dict:
        with closing(self._db.connect()) as c:
            rows = c.execute("SELECT state, COUNT(*) AS n FROM outbox GROUP BY state").fetchall()
        out = {"pending": 0, "rejected": 0}
        out.update({r["state"]: r["n"] for r in rows})
        return out

    def trim(self, max_pending: int, rejected_older_than_s: float) -> int:
        """Limites: com a cloud fora do ar por muito tempo, descarta os eventos MAIS ANTIGOS (a lacuna é preferível
        a um disco cheio); rejeitados velhos saem."""
        with closing(self._db.connect()) as c, c:
            dropped = c.execute(
                "DELETE FROM outbox WHERE state='pending' AND id <= "
                "(SELECT COALESCE(MAX(id), 0) FROM (SELECT id FROM outbox WHERE state='pending' "
                "ORDER BY id DESC LIMIT -1 OFFSET ?))", (max_pending,)).rowcount
            c.execute("DELETE FROM outbox WHERE state='rejected' AND created < ?",
                      (time.time() - rejected_older_than_s,))
        return dropped
