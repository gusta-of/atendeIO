"""Fluxo de pessoas ao longo do tempo: agregação das amostras e relatório (puro, sem I/O).

Guarda só NÚMEROS (pessoas por segundo → agregados por minuto/hora), nunca imagens.

    FlowAggregator   amostra de 1 s  →  lote por minuto/hora/área, pra gravar no banco em segundo plano
    build_report     linhas de hora do banco  →  médias, picos, mapa de calor, horas cheias/vazias, insights
    day_series       linhas de minuto  →  série do dia (5 em 5 min)

Chaves de tempo em UTC (`minute = epoch // 60`, `hour = epoch // 3600`); o FUSO do restaurante só entra na
hora de agrupar por dia e hora local, em `build_report`."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MIN_SAMPLES_TO_RANK = 300   # 5 min de dados: abaixo disso a média de uma hora/dia não é confiável pra "mais vazio"


# ── Agregação (lado do hub) ───────────────────────────────────────────────────────────────────

class FlowAggregator:
    """Acumula UMA amostra por segundo (a contagem de pessoas já estabilizada) em memória.

    Nada aqui toca o banco: `flush()` devolve um lote simples que o escritor em segundo plano grava.
    Segundo sem amostra (câmera offline, reconhecimento desligado, hub parado) simplesmente não existe:
    vira LACUNA na análise (cobertura), nunca "0 pessoas"."""

    def __init__(self, camera_id: int, flush_every_s: float = 15.0):
        self.camera_id = camera_id
        self._every = flush_every_s
        self._reset()
        self._last_flush: Optional[float] = None

    def _reset(self) -> None:
        self._minute: Dict[int, list] = {}   # minuto -> [n, soma, max, min]
        self._hour: Dict[int, list] = {}
        self._area: Dict[Tuple[int, int], list] = {}   # (zona, hora) -> [n, soma, max, nome, tipo]

    @staticmethod
    def _add(table: dict, key, people: int) -> None:
        row = table.get(key)
        if row is None:
            table[key] = [1, people, people, people]
        else:
            row[0] += 1
            row[1] += people
            row[2] = max(row[2], people)
            row[3] = min(row[3], people)

    def sample(self, ts: float, people: int, areas: Iterable[dict] = ()) -> None:
        people = max(0, int(people))
        self._add(self._minute, int(ts // 60), people)
        hour = int(ts // 3600)
        self._add(self._hour, hour, people)
        for a in areas:
            n = max(0, int(a.get("people", 0)))
            key = (int(a["id"]), hour)
            row = self._area.get(key)
            if row is None:
                self._area[key] = [1, n, n, a.get("name", ""), a.get("kind", "area")]
            else:
                row[0] += 1
                row[1] += n
                row[2] = max(row[2], n)
                row[3], row[4] = a.get("name", row[3]), a.get("kind", row[4])  # nome mais recente

    def due(self, ts: float) -> bool:
        if not (self._minute or self._hour):
            return False
        if self._last_flush is None:
            self._last_flush = ts
            return False
        return ts - self._last_flush >= self._every

    def flush(self, ts: Optional[float] = None) -> Optional[dict]:
        """Lote pronto pra gravar (e zera). None se não há nada."""
        if not (self._minute or self._hour):
            return None
        batch = {"camera_id": self.camera_id, "minute": self._minute, "hour": self._hour, "area": self._area}
        self._reset()
        if ts is not None:
            self._last_flush = ts
        return batch


# ── Relatório (lado da consulta) ──────────────────────────────────────────────────────────────

def _fmt(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _avg(total: int, n: int) -> Optional[float]:
    return round(total / n, 2) if n else None


def _slots(d_from: date, d_to: date, hour_from: int, hour_to: int, tz: ZoneInfo, now: datetime) -> int:
    """Quantas horas-calendário do período já terminaram (base da cobertura; a hora em curso não conta)."""
    count, d = 0, d_from
    while d <= d_to:
        for h in range(hour_from, hour_to):
            if datetime(d.year, d.month, d.day, h, tzinfo=tz) + timedelta(hours=1) <= now:   # só horas COMPLETAS
                count += 1
        d += timedelta(days=1)
    return count


def build_report(hour_rows: Iterable[tuple], area_rows: Iterable[tuple], tz: ZoneInfo, d_from: date, d_to: date,
                 hour_from: int = 0, hour_to: int = 24, now: Optional[datetime] = None) -> dict:
    """hour_rows: (hora_utc, amostras, soma, max, min). area_rows: (zona, hora_utc, nome, tipo, amostras, soma, max).
    Agrupa por dia e hora LOCAL (`tz`) e devolve tudo que a tela de análise precisa, numa resposta só."""
    now = now or datetime.now(tz)
    hourly = [[0, 0, 0] for _ in range(24)]            # [amostras, soma, max] por hora do dia
    by_day: Dict[date, list] = {}
    by_weekday = [[0, 0, 0] for _ in range(7)]
    heat = [[[0, 0, 0] for _ in range(24)] for _ in range(7)]
    peak = None
    total_n = total_sum = 0

    for hour, n, psum, pmax, _pmin in hour_rows:
        local = datetime.fromtimestamp(hour * 3600, tz)
        if not (d_from <= local.date() <= d_to and hour_from <= local.hour < hour_to):
            continue
        h, wd = local.hour, local.weekday()
        for cell in (hourly[h], by_weekday[wd], heat[wd][h], by_day.setdefault(local.date(), [0, 0, 0])):
            cell[0] += n
            cell[1] += psum
            cell[2] = max(cell[2], pmax)
        total_n += n
        total_sum += psum
        if peak is None or pmax > peak["value"]:
            peak = {"value": pmax, "at": local.replace(minute=0, second=0, microsecond=0).isoformat(),
                    "hour": h, "weekday": WEEKDAYS[wd]}

    slots = _slots(d_from, d_to, hour_from, hour_to, tz, now)
    coverage = round(min(1.0, total_n / (slots * 3600)), 3) if slots else 0.0

    hourly_out = [{"hour": h, "avg": _avg(c[1], c[0]), "max": c[2] if c[0] else None, "samples": c[0]}
                  for h, c in enumerate(hourly)]
    daily_out = [{"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "avg": _avg(c[1], c[0]), "max": c[2],
                  "samples": c[0]} for d, c in sorted(by_day.items())]
    weekday_out = [{"weekday": WEEKDAYS[i], "index": i, "avg": _avg(c[1], c[0]), "max": c[2] if c[0] else None,
                    "samples": c[0]} for i, c in enumerate(by_weekday)]
    heat_out = [[_avg(c[1], c[0]) for c in row] for row in heat]

    rankable_h = [x for x in hourly_out if x["samples"] >= MIN_SAMPLES_TO_RANK]
    rankable_w = [x for x in weekday_out if x["samples"] >= MIN_SAMPLES_TO_RANK]
    busiest_h = sorted(rankable_h, key=lambda x: -x["avg"])[:3]
    emptiest_h = sorted(rankable_h, key=lambda x: x["avg"])[:3]
    busiest_w = max(rankable_w, key=lambda x: x["avg"], default=None)
    emptiest_w = min(rankable_w, key=lambda x: x["avg"], default=None)

    areas: Dict[int, list] = {}
    for zid, _hour, name, kind, n, psum, pmax in area_rows:
        local = datetime.fromtimestamp(_hour * 3600, tz)
        if not (d_from <= local.date() <= d_to and hour_from <= local.hour < hour_to):
            continue
        a = areas.setdefault(zid, [name, kind, 0, 0, 0])
        a[0], a[1] = name, kind
        a[2] += n
        a[3] += psum
        a[4] = max(a[4], pmax)
    areas_out = sorted(({"zone_id": z, "name": a[0], "kind": a[1], "avg": _avg(a[3], a[2]), "max": a[4], "samples": a[2]}
                        for z, a in areas.items()), key=lambda x: -(x["avg"] or 0))

    summary = {
        "avg": _avg(total_sum, total_n), "samples": total_n, "coverage": coverage, "days_with_data": len(by_day),
        "peak": peak,
        "busiest_hours": busiest_h, "emptiest_hours": emptiest_h,
        "busiest_weekday": busiest_w, "emptiest_weekday": emptiest_w,
    }
    return {"summary": summary, "hourly": hourly_out, "daily": daily_out, "weekday": weekday_out,
            "heatmap": heat_out, "areas": areas_out,
            "insights": insights(summary, hourly_out, hour_from, hour_to),
            "range": {"from": d_from.isoformat(), "to": d_to.isoformat(), "hour_from": hour_from, "hour_to": hour_to,
                      "timezone": str(tz)}}


def insights(summary: dict, hourly: List[dict], hour_from: int = 0, hour_to: int = 24) -> List[str]:
    """Frases em português geradas por regras: o que o utilizador precisa saber sem olhar gráfico."""
    if not summary["samples"]:
        return ["Ainda não há dados neste período. Ligue “Monitorar” na câmera (com “Pessoa” marcada em Objetos) "
                "para o histórico começar a ser gravado."]
    out = []
    bh, eh = summary["busiest_hours"], summary["emptiest_hours"]
    if bh:
        out.append("Horários mais cheios: " + ", ".join(
            f"{x['hour']}h (média de {_fmt(x['avg'])} pessoas, pico {x['max']})" for x in bh) + ".")
    if eh and (not bh or eh[0]["hour"] != bh[0]["hour"]):
        out.append("Horários mais vazios: " + ", ".join(
            f"{x['hour']}h (média de {_fmt(x['avg'])})" for x in eh) + ".")
    if summary["busiest_weekday"] and summary["emptiest_weekday"] \
            and summary["busiest_weekday"]["index"] != summary["emptiest_weekday"]["index"]:
        b, e = summary["busiest_weekday"], summary["emptiest_weekday"]
        out.append(f"Dia da semana mais movimentado: {b['weekday']} (média de {_fmt(b['avg'])}); "
                   f"mais tranquilo: {e['weekday']} (média de {_fmt(e['avg'])}).")
    peak, avg = summary["peak"], summary["avg"] or 0
    if peak:
        when = datetime.fromisoformat(peak["at"])
        out.append(f"Maior movimento registrado: {peak['value']} pessoas ao mesmo tempo, em "
                   f"{when.strftime('%d/%m')} ({peak['weekday']}), por volta das {peak['hour']}h.")
        if avg and peak["value"] >= 2.5 * avg:
            out.append(f"O pico é {_fmt(peak['value'] / avg)}× a média do período: o movimento é concentrado em "
                       "poucos horários, o que pede reforço de equipe nesses momentos.")
    if summary["coverage"] < 0.8:
        hint = (" Se o restaurante fecha parte do dia, ajuste “Funcionamento” para excluir as horas fechadas."
                if hour_to - hour_from >= 24 else "")
        out.append(f"Atenção: os dados cobrem só {round(summary['coverage'] * 100)}% do período. Confira se o "
                   f"monitoramento ficou ligado; as lacunas não são contadas como “vazio”.{hint}")
    return out


def day_series(minute_rows: Iterable[tuple], tz: ZoneInfo, day: date, step_min: int = 5) -> List[dict]:
    """Série do dia local em passos de `step_min` minutos: média e máximo de pessoas (só onde há amostras)."""
    buckets: Dict[int, list] = defaultdict(lambda: [0, 0, 0])
    for minute, n, psum, pmax, _pmin in minute_rows:
        local = datetime.fromtimestamp(minute * 60, tz)
        if local.date() != day:
            continue
        b = buckets[(local.hour * 60 + local.minute) // step_min]
        b[0] += n
        b[1] += psum
        b[2] = max(b[2], pmax)
    return [{"t": f"{(i * step_min) // 60:02d}:{(i * step_min) % 60:02d}", "avg": _avg(b[1], b[0]), "max": b[2],
             "samples": b[0]} for i, b in sorted(buckets.items())]


def local_day_bounds(day: date, tz: ZoneInfo) -> Tuple[int, int]:
    """[início, fim) do dia local, em minutos desde a época (pra consultar `flow_minute`)."""
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    end = datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(days=1)
    return int(start.timestamp() // 60), int(end.timestamp() // 60)


def hourly_rows(hour_rows: Iterable[tuple], tz: ZoneInfo, d_from: date, d_to: date,
                hour_from: int = 0, hour_to: int = 24) -> List[dict]:
    """Uma linha por hora local do período (pro CSV): data, dia da semana, hora, média, máximo e amostras."""
    out = []
    for hour, n, psum, pmax, _pmin in hour_rows:
        local = datetime.fromtimestamp(hour * 3600, tz)
        if d_from <= local.date() <= d_to and hour_from <= local.hour < hour_to:
            out.append({"data": local.date().isoformat(), "dia_da_semana": WEEKDAYS[local.weekday()],
                        "hora": local.hour, "media_pessoas": _avg(psum, n), "maximo_pessoas": pmax, "amostras": n})
    return out
