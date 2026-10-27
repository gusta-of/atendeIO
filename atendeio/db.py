"""SQLite: conexão por operação (barata) e criação do esquema."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    pw_hash TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('local', 'rtsp')),
    ref TEXT NOT NULL,
    secret BLOB,
    monitor INTEGER NOT NULL DEFAULT 0,      -- 1 = monitoramento contínuo (alimenta a análise de fluxo)
    monitor_from TEXT,                       -- 'HH:MM' no fuso do restaurante; vazio = o dia todo
    monitor_to TEXT,
    recognition INTEGER NOT NULL DEFAULT 1,  -- chave geral: 0 desliga o reconhecimento da câmera
    classes TEXT NOT NULL DEFAULT '[]',      -- JSON com os ids das classes habilitadas (vazio = nenhuma)
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS zones (
    id INTEGER PRIMARY KEY,
    camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    points TEXT NOT NULL,      -- JSON [[x,y],...] normalizado 0..1 (é o que a análise usa)
    shape TEXT NOT NULL DEFAULT 'poly',   -- poly | rect | square | ellipse | triangle (só pro editor)
    angle REAL NOT NULL DEFAULT 0,        -- rotação em graus (só pro editor)
    margin REAL NOT NULL DEFAULT 0.06,    -- mesa: largura da "sombra" de assentos, em fração da altura da imagem
    created REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS zones_camera_name ON zones(camera_id, name);
-- Histórico de fluxo: SÓ números agregados (nunca imagens). Chaves em UTC; o fuso entra na consulta.
CREATE TABLE IF NOT EXISTS flow_minute (
    camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    minute INTEGER NOT NULL,                 -- epoch // 60
    samples INTEGER NOT NULL, people_sum INTEGER NOT NULL, people_max INTEGER NOT NULL, people_min INTEGER NOT NULL,
    PRIMARY KEY (camera_id, minute)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS flow_hour (
    camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    hour INTEGER NOT NULL,                   -- epoch // 3600
    samples INTEGER NOT NULL, people_sum INTEGER NOT NULL, people_max INTEGER NOT NULL, people_min INTEGER NOT NULL,
    PRIMARY KEY (camera_id, hour)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS flow_area_hour (
    camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    zone_id INTEGER NOT NULL,
    hour INTEGER NOT NULL,
    zone_name TEXT NOT NULL, kind TEXT NOT NULL,
    samples INTEGER NOT NULL, people_sum INTEGER NOT NULL, people_max INTEGER NOT NULL,
    PRIMARY KEY (camera_id, zone_id, hour)
) WITHOUT ROWID;
-- uma câmera física só pode ter um dono
CREATE UNIQUE INDEX IF NOT EXISTS cameras_local_ref ON cameras(ref) WHERE kind = 'local';
CREATE UNIQUE INDEX IF NOT EXISTS cameras_rtsp_ref ON cameras(user_id, ref) WHERE kind = 'rtsp';
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Bancos criados antes das formas rotacionáveis ganham as colunas novas (sem perder áreas)."""
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(zones)")}
        if "shape" not in cols:
            conn.execute("ALTER TABLE zones ADD COLUMN shape TEXT NOT NULL DEFAULT 'poly'")
        if "angle" not in cols:
            conn.execute("ALTER TABLE zones ADD COLUMN angle REAL NOT NULL DEFAULT 0")
        if "margin" not in cols:
            conn.execute("ALTER TABLE zones ADD COLUMN margin REAL NOT NULL DEFAULT 0.06")
        cam_cols = {r["name"] for r in conn.execute("PRAGMA table_info(cameras)")}
        for col, ddl in (("monitor", "INTEGER NOT NULL DEFAULT 0"), ("monitor_from", "TEXT"), ("monitor_to", "TEXT")):
            if col not in cam_cols:
                conn.execute(f"ALTER TABLE cameras ADD COLUMN {col} {ddl}")
        if "recognition" not in cam_cols:
            conn.execute("ALTER TABLE cameras ADD COLUMN recognition INTEGER NOT NULL DEFAULT 1")
        if "classes" not in cam_cols:
            conn.execute("ALTER TABLE cameras ADD COLUMN classes TEXT NOT NULL DEFAULT '[]'")

    def init(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(self.connect()) as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            self._migrate(conn)
        os.chmod(self.path, 0o600)
