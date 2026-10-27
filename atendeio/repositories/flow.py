"""Histórico de fluxo no SQLite: gravação em lote (UPSERT que soma) e leitura por período."""

from contextlib import closing
from typing import List

from ..db import Database

_UPSERT = {
    "minute": """INSERT INTO flow_minute(camera_id, minute, samples, people_sum, people_max, people_min)
                 VALUES (?,?,?,?,?,?)
                 ON CONFLICT(camera_id, minute) DO UPDATE SET samples = samples + excluded.samples,
                   people_sum = people_sum + excluded.people_sum, people_max = MAX(people_max, excluded.people_max),
                   people_min = MIN(people_min, excluded.people_min)""",
    "hour": """INSERT INTO flow_hour(camera_id, hour, samples, people_sum, people_max, people_min)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(camera_id, hour) DO UPDATE SET samples = samples + excluded.samples,
                 people_sum = people_sum + excluded.people_sum, people_max = MAX(people_max, excluded.people_max),
                 people_min = MIN(people_min, excluded.people_min)""",
    "area": """INSERT INTO flow_area_hour(camera_id, zone_id, hour, zone_name, kind, samples, people_sum, people_max)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(camera_id, zone_id, hour) DO UPDATE SET samples = samples + excluded.samples,
                 people_sum = people_sum + excluded.people_sum, people_max = MAX(people_max, excluded.people_max),
                 zone_name = excluded.zone_name, kind = excluded.kind""",
}


class FlowRepository:
    def __init__(self, db: Database):
        self._db = db

    def apply(self, batches: List[dict]) -> None:
        """Grava vários lotes numa transação só. Chamado APENAS pela thread escritora."""
        with closing(self._db.connect()) as c, c:
            for b in batches:
                cam = b["camera_id"]
                c.executemany(_UPSERT["minute"], [(cam, m, *v) for m, v in b["minute"].items()])
                c.executemany(_UPSERT["hour"], [(cam, h, *v) for h, v in b["hour"].items()])
                c.executemany(_UPSERT["area"], [(cam, z, h, v[3], v[4], v[0], v[1], v[2])
                                                for (z, h), v in b["area"].items()])

    # -- leitura (pedidos da análise) -------------------------------------------------------
    def hours(self, camera_id: int, from_hour: int, to_hour: int) -> list:
        with closing(self._db.connect()) as c:
            return [tuple(r) for r in c.execute(
                "SELECT hour, samples, people_sum, people_max, people_min FROM flow_hour "
                "WHERE camera_id=? AND hour>=? AND hour<? ORDER BY hour", (camera_id, from_hour, to_hour))]

    def minutes(self, camera_id: int, from_minute: int, to_minute: int) -> list:
        with closing(self._db.connect()) as c:
            return [tuple(r) for r in c.execute(
                "SELECT minute, samples, people_sum, people_max, people_min FROM flow_minute "
                "WHERE camera_id=? AND minute>=? AND minute<? ORDER BY minute", (camera_id, from_minute, to_minute))]

    def areas(self, camera_id: int, from_hour: int, to_hour: int) -> list:
        with closing(self._db.connect()) as c:
            return [tuple(r) for r in c.execute(
                "SELECT zone_id, hour, zone_name, kind, samples, people_sum, people_max FROM flow_area_hour "
                "WHERE camera_id=? AND hour>=? AND hour<?", (camera_id, from_hour, to_hour))]

    def purge(self, minute_before: int, hour_before: int) -> int:
        """Apaga o que passou da retenção. Devolve quantas linhas saíram."""
        with closing(self._db.connect()) as c, c:
            n = c.execute("DELETE FROM flow_minute WHERE minute < ?", (minute_before,)).rowcount
            n += c.execute("DELETE FROM flow_hour WHERE hour < ?", (hour_before,)).rowcount
            n += c.execute("DELETE FROM flow_area_hour WHERE hour < ?", (hour_before,)).rowcount
        return n
