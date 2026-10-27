"""Histórico de fluxo: agregação, fuso, picos e vales, cobertura e insights (tudo puro, relógio injetado)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from atendeio.analytics.flow import FlowAggregator, build_report, day_series, insights, local_day_bounds

TZ = ZoneInfo("America/Sao_Paulo")   # UTC-3 (sem horário de verão)
NOW = datetime(2026, 1, 20, 12, 0, tzinfo=TZ)


def hrow(local_dt: datetime, avg: float, peak: int, samples: int = 3600):
    """Linha de `flow_hour` pra uma hora LOCAL: (hora_utc, amostras, soma, max, min)."""
    return (int(local_dt.timestamp() // 3600), samples, int(avg * samples), peak, 0)


def pattern(days: int = 14, end: date = date(2026, 1, 19)):
    """Restaurante fictício: sexta e sábado às 20h lotado (avg 15), terça às 15h vazio (avg 1), resto médio (avg 5)."""
    rows = []
    for i in range(days):
        d = end - timedelta(days=i)
        for h in range(11, 24):
            at = datetime(d.year, d.month, d.day, h, tzinfo=TZ)
            avg = 5.0
            if d.weekday() in (4, 5) and h == 20:
                avg = 15.0
            if d.weekday() == 1 and h == 15:
                avg = 1.0
            rows.append(hrow(at, avg, int(avg) + 3))
    return rows


# ── agregador ─────────────────────────────────────────────────────────────────────────────────
def test_aggregator_buckets_by_minute_and_hour_and_flushes_once():
    agg = FlowAggregator(7, flush_every_s=15)
    base = 1_800_000_000 - 1_800_000_000 % 3600          # início de uma hora UTC
    for s in range(120):                                  # 2 minutos de amostras, 1 por segundo
        agg.sample(base + s, people=3 if s < 60 else 5)
    batch = agg.flush()
    assert batch["camera_id"] == 7
    m0, m1 = base // 60, base // 60 + 1
    assert batch["minute"][m0] == [60, 180, 3, 3] and batch["minute"][m1] == [60, 300, 5, 5]
    assert batch["hour"][base // 3600] == [120, 480, 5, 3]            # n, soma, max, min
    assert agg.flush() is None                                         # zerou: nada pra gravar de novo


def test_aggregator_gaps_are_missing_not_zero():
    agg = FlowAggregator(1)
    base = 1_800_000_000
    agg.sample(base, 4)
    agg.sample(base + 600, 4)                              # 10 min depois; nada no meio (câmera offline)
    minutes = agg.flush()["minute"]
    assert len(minutes) == 2                               # só os minutos amostrados existem; nenhum "0 pessoas" inventado


def test_aggregator_areas_and_latest_name():
    agg = FlowAggregator(1)
    base = 1_800_000_000
    agg.sample(base, 3, [{"id": 5, "name": "Mesa 1", "kind": "mesa", "people": 2}])
    agg.sample(base + 1, 3, [{"id": 5, "name": "Mesa A", "kind": "mesa", "people": 4}])   # foi renomeada
    row = agg.flush()["area"][(5, base // 3600)]
    assert row == [2, 6, 4, "Mesa A", "mesa"]


def test_aggregator_due_waits_for_the_flush_interval():
    agg = FlowAggregator(1, flush_every_s=15)
    assert agg.due(100) is False                           # nada acumulado
    agg.sample(100, 1)
    assert agg.due(100) is False                           # 1ª vez só marca o relógio
    assert agg.due(110) is False and agg.due(116) is True


def test_aggregator_clamps_negative_people():
    agg = FlowAggregator(1)
    agg.sample(1_800_000_000, -3)
    assert agg.flush()["hour"][1_800_000_000 // 3600] == [1, 0, 0, 0]


# ── relatório: fuso ───────────────────────────────────────────────────────────────────────────
def test_timezone_puts_23h_friday_local_on_friday_not_saturday_utc():
    at = datetime(2026, 1, 9, 23, tzinfo=TZ)               # sexta 23h em SP = sábado 02h UTC
    assert datetime.fromtimestamp(at.timestamp(), ZoneInfo("UTC")).weekday() == 5   # em UTC já é sábado
    rep = build_report([hrow(at, 8.0, 12)], [], TZ, date(2026, 1, 9), date(2026, 1, 10), now=NOW)
    assert rep["daily"][0]["date"] == "2026-01-09" and rep["daily"][0]["weekday"] == "sexta-feira"
    assert rep["hourly"][23]["avg"] == 8.0 and rep["hourly"][2]["avg"] is None     # a hora 2 (UTC) NÃO recebe nada
    assert rep["heatmap"][4][23] == 8.0                                             # sexta (índice 4), 23h


def test_rows_outside_the_date_range_are_ignored():
    rows = [hrow(datetime(2026, 1, 5, 20, tzinfo=TZ), 9.0, 9), hrow(datetime(2026, 1, 15, 20, tzinfo=TZ), 3.0, 3)]
    rep = build_report(rows, [], TZ, date(2026, 1, 10), date(2026, 1, 19), now=NOW)
    assert rep["summary"]["avg"] == 3.0 and rep["summary"]["days_with_data"] == 1


# ── relatório: picos, vales, filtros ──────────────────────────────────────────────────────────
def test_busiest_and_emptiest_hours_and_weekdays_follow_the_pattern():
    rep = build_report(pattern(), [], TZ, date(2026, 1, 6), date(2026, 1, 19), now=NOW)
    s = rep["summary"]
    assert s["busiest_hours"][0]["hour"] == 20                          # 20h: lotado nas sextas e sábados
    assert s["emptiest_hours"][0]["hour"] == 15                         # 15h: esvaziado pelas terças
    assert s["busiest_weekday"]["weekday"] in ("sexta-feira", "sábado")
    assert s["emptiest_weekday"]["weekday"] != s["busiest_weekday"]["weekday"]
    assert s["peak"]["value"] == 18 and s["peak"]["hour"] == 20
    assert rep["heatmap"][4][20] == 15.0 and rep["heatmap"][1][15] == 1.0   # sexta 20h / terça 15h


def test_hour_filter_excludes_closed_hours_from_the_ranking():
    rows = pattern() + [hrow(datetime(2026, 1, 19, 3, tzinfo=TZ), 0.0, 0, samples=3600)] * 3   # madrugada: ninguém
    open_all = build_report(rows, [], TZ, date(2026, 1, 6), date(2026, 1, 19), 0, 24, NOW)
    only_open = build_report(rows, [], TZ, date(2026, 1, 6), date(2026, 1, 19), 11, 24, NOW)
    assert open_all["summary"]["emptiest_hours"][0]["hour"] == 3        # sem o filtro, a madrugada vira a "mais vazia"
    assert only_open["summary"]["emptiest_hours"][0]["hour"] == 15      # com o filtro de funcionamento, não
    assert all(h["samples"] == 0 for h in only_open["hourly"][:11])


def test_hours_with_too_little_data_are_not_ranked():
    rows = [hrow(datetime(2026, 1, 19, 14, tzinfo=TZ), 0.0, 0, samples=20),      # 20 s de dados: não conta como "vazio"
            hrow(datetime(2026, 1, 19, 20, tzinfo=TZ), 9.0, 12)]
    s = build_report(rows, [], TZ, date(2026, 1, 19), date(2026, 1, 19), now=NOW)["summary"]
    assert [x["hour"] for x in s["emptiest_hours"]] == [20]


def test_coverage_is_the_share_of_the_period_with_data():
    rows = [hrow(datetime(2026, 1, 19, h, tzinfo=TZ), 4.0, 6) for h in range(10, 14)]       # 4 de 8 horas
    rep = build_report(rows, [], TZ, date(2026, 1, 19), date(2026, 1, 19), 10, 18, NOW)
    assert rep["summary"]["coverage"] == 0.5
    half = [hrow(datetime(2026, 1, 19, h, tzinfo=TZ), 4.0, 6, samples=1800) for h in range(10, 18)]
    assert build_report(half, [], TZ, date(2026, 1, 19), date(2026, 1, 19), 10, 18, NOW)["summary"]["coverage"] == 0.5


def test_future_hours_do_not_count_against_coverage():
    rows = [hrow(datetime(2026, 1, 20, h, tzinfo=TZ), 4.0, 6) for h in range(8, 12)]       # hoje até às 12h
    rep = build_report(rows, [], TZ, date(2026, 1, 20), date(2026, 1, 20), 8, 22, NOW)       # agora = 12:00
    assert rep["summary"]["coverage"] == 1.0                                                 # 8h–12h completas; 12h em diante ainda não


# ── áreas ─────────────────────────────────────────────────────────────────────────────────────
def test_areas_are_ranked_by_average_people():
    h = int(datetime(2026, 1, 19, 20, tzinfo=TZ).timestamp() // 3600)
    areas = [(1, h, "Mesa 1", "mesa", 3600, 3600 * 1, 3), (2, h, "Balcão", "balcao", 3600, 3600 * 4, 6),
             (1, h + 1, "Mesa 1", "mesa", 3600, 3600 * 3, 4)]
    out = build_report([hrow(datetime(2026, 1, 19, 20, tzinfo=TZ), 5.0, 6)], areas, TZ,
                       date(2026, 1, 19), date(2026, 1, 19), now=NOW)["areas"]
    assert [a["name"] for a in out] == ["Balcão", "Mesa 1"] and out[0]["avg"] == 4.0
    assert out[1]["avg"] == 2.0 and out[1]["max"] == 4                    # soma das duas horas / amostras


# ── insights ──────────────────────────────────────────────────────────────────────────────────
def test_insights_empty_period_explains_how_to_start():
    rep = build_report([], [], TZ, date(2026, 1, 19), date(2026, 1, 19), now=NOW)
    assert len(rep["insights"]) == 1 and "Monitorar" in rep["insights"][0]


def test_insights_name_the_busiest_hour_weekday_and_warn_about_coverage():
    rep = build_report(pattern(), [], TZ, date(2026, 1, 6), date(2026, 1, 19), now=NOW)
    text = " ".join(rep["insights"])
    assert "20h" in text and "15h" in text and "Maior movimento registrado: 18 pessoas" in text
    assert "pico é" in text                                                # 18 ≥ 2,5 × média → aponta a concentração
    sparse = build_report(pattern()[:6], [], TZ, date(2026, 1, 6), date(2026, 1, 19), now=NOW)
    assert any("cobrem só" in i for i in sparse["insights"])


def test_insights_use_decimal_comma():
    import re
    rep = build_report(pattern(), [], TZ, date(2026, 1, 6), date(2026, 1, 19), now=NOW)
    text = " ".join(rep["insights"])
    assert re.search(r"\d,\d", text) and not re.search(r"\d\.\d", text)


# ── série do dia ──────────────────────────────────────────────────────────────────────────────
def test_day_series_buckets_five_minutes_in_local_time():
    day = date(2026, 1, 19)
    start = int(datetime(2026, 1, 19, 20, 0, tzinfo=TZ).timestamp() // 60)
    rows = [(start + i, 60, 60 * (i + 1), i + 1, 0) for i in range(10)]            # 20:00..20:09, pessoas crescendo
    rows.append((start - 24 * 60, 60, 60, 1, 0))                                   # ontem: ignorado
    out = day_series(rows, TZ, day, step_min=5)
    assert [p["t"] for p in out] == ["20:00", "20:05"]
    assert out[0]["avg"] == 3.0 and out[0]["max"] == 5                              # média de 1..5, máx 5


def test_local_day_bounds_cover_exactly_24h():
    lo, hi = local_day_bounds(date(2026, 1, 19), TZ)
    assert hi - lo == 24 * 60 and datetime.fromtimestamp(lo * 60, TZ).hour == 0
