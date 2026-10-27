"""Histórico de fluxo de ponta a ponta: hub → agregador → escritor → SQLite → API, mais isolamento e validação."""

import csv
import io
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from atendeio.db import Database
from atendeio.repositories.flow import FlowRepository

TZ = ZoneInfo("America/Sao_Paulo")


def wait(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def make_cam(client, video_file, classes=(0,)):
    cam = client.post("/api/cameras/local", json={"ref": str(video_file)}).json()["camera"]["id"]
    client.put(f"/api/cameras/{cam}/recognition", json={"enabled": True, "classes": list(classes)})
    return cam


def seed(container, cam, local_dt, avg, peak, samples=3600, zone=None):
    """Grava uma hora de histórico (como o escritor faria), numa hora LOCAL conhecida."""
    hour = int(local_dt.timestamp() // 3600)
    batch = {"camera_id": cam, "minute": {hour * 60: [samples, int(avg * samples), peak, 0]},
             "hour": {hour: [samples, int(avg * samples), peak, 0]}, "area": {}}
    if zone:
        batch["area"][(zone[0], hour)] = [samples, int(zone[2] * samples), zone[3], zone[1], "mesa"]
    FlowRepository(container.db).apply([batch])


# ── ciclo completo ────────────────────────────────────────────────────────────────────────────
def test_monitored_camera_fills_the_history_and_the_api_reports_it(new_client, container, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file)
    container.flow_writer.start()
    c.put(f"/api/cameras/{cam}/monitor", json={"enabled": True})            # liga o monitoramento: ninguém assiste o vídeo
    repo = FlowRepository(container.db)
    now_h = int(time.time() // 3600)
    try:
        assert wait(lambda: repo.hours(cam, now_h - 2, now_h + 2))            # o histórico começou a ser gravado sozinho
        rep = c.get(f"/api/cameras/{cam}/flow").json()
        assert rep["summary"]["samples"] >= 1 and rep["summary"]["avg"] == 1.0   # o detector falso vê 1 pessoa
        local_hour = datetime.now(TZ).hour
        assert rep["hourly"][local_hour]["avg"] == 1.0 and rep["hourly"][local_hour]["samples"] >= 1
        assert rep["range"]["timezone"] == "America/Sao_Paulo"
        assert rep["insights"]
        day = c.get(f"/api/cameras/{cam}/flow/day").json()
        assert day["series"] and day["series"][0]["avg"] == 1.0
    finally:
        container.scheduler.stop()
        container.registry.stop_all()      # entrega o que sobrou ao escritor...
        container.flow_writer.stop()       # ...que grava antes de sair
    assert repo.hours(cam, now_h - 2, now_h + 2)


# ── relatório determinístico via API ──────────────────────────────────────────────────────────
def test_report_endpoint_groups_by_local_day_and_hour(new_client, container, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file)
    yday = datetime.now(TZ).date() - timedelta(days=1)
    seed(container, cam, datetime(yday.year, yday.month, yday.day, 20, tzinfo=TZ), avg=12.0, peak=18)
    seed(container, cam, datetime(yday.year, yday.month, yday.day, 15, tzinfo=TZ), avg=2.0, peak=4)
    rep = c.get(f"/api/cameras/{cam}/flow?from={yday}&to={yday}").json()
    assert rep["hourly"][20]["avg"] == 12.0 and rep["hourly"][15]["avg"] == 2.0 and rep["hourly"][3]["avg"] is None
    assert rep["summary"]["peak"]["value"] == 18 and rep["summary"]["peak"]["hour"] == 20
    assert [d["date"] for d in rep["daily"]] == [yday.isoformat()]
    wd = (yday.weekday())
    assert rep["heatmap"][wd][20] == 12.0
    only_afternoon = c.get(f"/api/cameras/{cam}/flow?from={yday}&to={yday}&hour_from=14&hour_to=18").json()
    assert only_afternoon["hourly"][20]["avg"] is None and only_afternoon["hourly"][15]["avg"] == 2.0   # filtro de funcionamento


def test_areas_ranking_in_the_report(new_client, container, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file)
    yday = datetime.now(TZ).date() - timedelta(days=1)
    seed(container, cam, datetime(yday.year, yday.month, yday.day, 20, tzinfo=TZ), 6.0, 9, zone=(1, "Mesa 1", 3.0, 5))
    rep = c.get(f"/api/cameras/{cam}/flow?from={yday}&to={yday}").json()
    assert rep["areas"][0]["name"] == "Mesa 1" and rep["areas"][0]["avg"] == 3.0 and rep["areas"][0]["max"] == 5


def test_csv_export(new_client, container, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file)
    yday = datetime.now(TZ).date() - timedelta(days=1)
    seed(container, cam, datetime(yday.year, yday.month, yday.day, 20, tzinfo=TZ), avg=12.0, peak=18)
    r = c.get(f"/api/cameras/{cam}/flow.csv?from={yday}&to={yday}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert f"fluxo-camera-{cam}.csv" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows == [{"data": yday.isoformat(), "dia_da_semana": rows[0]["dia_da_semana"], "hora": "20",
                     "media_pessoas": "12.0", "maximo_pessoas": "18", "amostras": "3600"}]


def test_empty_history_explains_what_to_do(new_client, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file)
    rep = c.get(f"/api/cameras/{cam}/flow").json()
    assert rep["summary"]["samples"] == 0 and rep["summary"]["avg"] is None
    assert "Monitorar" in rep["insights"][0]


# ── validação ─────────────────────────────────────────────────────────────────────────────────
def test_query_validation(new_client, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file)
    base = f"/api/cameras/{cam}/flow"
    assert c.get(f"{base}?from=ontem").status_code == 400                         # data inválida
    assert c.get(f"{base}?from=2026-01-10&to=2026-01-01").status_code == 400      # fim antes do início
    assert c.get(f"{base}?hour_from=20&hour_to=10").status_code == 400
    assert c.get(f"{base}?hour_from=0&hour_to=25").status_code == 400
    assert c.get(f"{base}?from=2020-01-01&to=2026-01-01").status_code == 400      # mais de 2 anos
    assert c.get(f"{base}/day?date=xx").status_code == 400
    assert c.get(base).status_code == 200


# ── isolamento ────────────────────────────────────────────────────────────────────────────────
def test_flow_endpoints_are_isolated_between_users(new_client, container, video_file):
    alice, bob, anon = new_client("alice"), new_client("bob"), new_client()
    cam = make_cam(alice, video_file)
    yday = datetime.now(TZ).date() - timedelta(days=1)
    seed(container, cam, datetime(yday.year, yday.month, yday.day, 20, tzinfo=TZ), 12.0, 18)
    for path in (f"/api/cameras/{cam}/flow", f"/api/cameras/{cam}/flow/day", f"/api/cameras/{cam}/flow.csv",
                 f"/api/cameras/{cam}/monitor"):
        assert bob.get(path).status_code == 404, path                              # câmera alheia = inexistente
        assert anon.get(path).status_code == 401, path
        assert alice.get(path).status_code == 200, path


def test_deleting_a_camera_deletes_its_history(new_client, container, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file)
    yday = datetime.now(TZ).date() - timedelta(days=1)
    seed(container, cam, datetime(yday.year, yday.month, yday.day, 20, tzinfo=TZ), 12.0, 18)
    assert FlowRepository(container.db).hours(cam, 0, 10 ** 9)
    c.delete(f"/api/cameras/{cam}")
    assert FlowRepository(container.db).hours(cam, 0, 10 ** 9) == []             # ON DELETE CASCADE


# ── banco: upsert que soma, retenção, migração ────────────────────────────────────────────────
def test_upsert_adds_samples_and_keeps_max_min(container, new_client, video_file):
    cam = make_cam(new_client("ana"), video_file)
    repo = FlowRepository(container.db)
    mk = lambda n, s, mx, mn: {"camera_id": cam, "minute": {100: [n, s, mx, mn]}, "hour": {1: [n, s, mx, mn]}, "area": {}}
    repo.apply([mk(10, 20, 4, 1), mk(5, 30, 9, 0)])
    assert repo.hours(cam, 0, 10) == [(1, 15, 50, 9, 0)]                          # amostras e soma somam; max/min se preservam
    assert repo.minutes(cam, 0, 200) == [(100, 15, 50, 9, 0)]


def test_purge_removes_only_what_is_past_retention(container, new_client, video_file):
    cam = make_cam(new_client("ana"), video_file)
    repo = FlowRepository(container.db)
    old, new = 1000, 5_000_000
    repo.apply([{"camera_id": cam, "minute": {old * 60: [1, 1, 1, 1], new * 60: [1, 1, 1, 1]},
                 "hour": {old: [1, 1, 1, 1], new: [1, 1, 1, 1]}, "area": {(1, old): [1, 1, 1, "M", "mesa"]}}])
    removed = repo.purge(minute_before=new * 60, hour_before=new)
    assert removed == 3
    assert [r[0] for r in repo.hours(cam, 0, 10 ** 9)] == [new] and [r[0] for r in repo.minutes(cam, 0, 10 ** 12)] == [new * 60]


def test_old_database_gets_monitor_columns_and_flow_tables(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, pw_hash TEXT, created REAL);
        CREATE TABLE cameras (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, kind TEXT, ref TEXT, secret BLOB, created REAL);
        INSERT INTO cameras VALUES (1, 1, 'Sala', 'local', '/dev/x', NULL, 0);
    """)
    old.commit(); old.close()
    Database(path).init()
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT monitor, monitor_from, monitor_to FROM cameras").fetchone() == (0, None, None)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"flow_minute", "flow_hour", "flow_area_hour"} <= tables


def test_health_endpoint_reports_loop_lag_and_writer(new_client):
    c = new_client("ana")
    h = c.get("/api/health").json()
    assert set(h) == {"loop_lag_ms", "cameras_active", "flow_writer"}
    assert set(h["flow_writer"]) == {"submitted", "written", "dropped", "errors"}
    assert new_client().get("/api/health").status_code == 401


def test_days_shortcut_uses_the_restaurant_today(new_client, container, video_file):
    c = new_client("ana")
    cam = make_cam(c, video_file)
    today = datetime.now(TZ).date()
    for days in (1, 7, 90):
        r = c.get(f"/api/cameras/{cam}/flow?days={days}").json()["range"]
        assert r["to"] == today.isoformat() and r["from"] == (today - timedelta(days=days - 1)).isoformat()
    assert c.get(f"/api/cameras/{cam}/flow?days=0").status_code == 400
    assert c.get(f"/api/cameras/{cam}/flow?days=9999").status_code == 400
    assert c.get(f"/api/cameras/{cam}/flow.csv?days=7").status_code == 200
