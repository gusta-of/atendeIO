"""Geometria dos gráficos da Análise de fluxo (porta de `chart-models.ts`). Funções puras: devolvem o que o widget desenha
(posições, retângulos, textos de dica), sem tocar em Qt. Espaço lógico de 680 px de largura (o widget escala)."""

from datetime import date, timedelta
from typing import Callable, List, Optional

from ..format import br_date, compact, hh, nice_max, num

WD_SHORT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
SERIES_1, SERIES_2 = "#3987e5", "#d95926"
SEQ = ["#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5", "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4"]


def _tip(title: str, rows: List[dict]) -> dict:
    return {"title": title, "rows": rows}


def column_model(data: List[dict], label: Callable, x_label: Callable, peak: bool = True, height: int = 230) -> dict:
    """Colunas de média com ponto de pico. Cada item: {avg, max, ...}. Lacuna (avg None) não vira coluna nem zero."""
    W, H, m = 680, height, {"l": 36, "r": 8, "t": 14, "b": 24}
    iw, ih = W - m["l"] - m["r"], H - m["t"] - m["b"]
    vals = [d["avg"] for d in data if d["avg"] is not None]
    y_max = nice_max(max([0] + vals + ([d["max"] or 0 for d in data] if peak else [])))

    def y(v):
        return m["t"] + ih - (v / y_max) * ih

    slot = iw / max(1, len(data))
    bw = min(24, slot * 0.62)
    ticks = [{"y": y(y_max / 4 * i), "label": compact(y_max / 4 * i), "base": i == 0} for i in range(5)]
    ranked = {"hi": max(vals), "lo": min(vals)} if vals else None
    labelled: set = set()
    cols = []
    for i, d in enumerate(data):
        cx = m["l"] + slot * i + slot / 2
        if d["avg"] is None:
            rows = [{"text": "sem dados neste período"}]
        else:
            rows = [{"key": SERIES_1, "text": f"Média: {num(d['avg'])} pessoas"}]
            if peak and d["max"] is not None:
                rows.append({"key": SERIES_2, "text": f"Pico: {d['max']} pessoas"})
        rect = peak_y = lbl = None
        if d["avg"] is not None:
            top, base = y(d["avg"]), y(0)
            rect = {"x0": cx - bw / 2, "x1": cx + bw / 2, "top": top, "base": base, "r": min(4, (base - top) / 2)}
            if peak and d["max"] is not None and d["max"] > d["avg"]:
                peak_y = y(d["max"])
            if ranked and len(vals) > 2 and d["avg"] in (ranked["hi"], ranked["lo"]) and len(labelled) < 2 \
                    and d["avg"] not in labelled:
                labelled.add(d["avg"])                  # rótulo direto só no mais cheio e no mais vazio
                lbl = {"y": min(top, y(d["max"]) if peak and d["max"] else top) - 9, "text": num(d["avg"])}
        cols.append({
            "cx": cx, "x": x_label(d, i, len(data)), "rect": rect, "peak_y": peak_y, "lbl": lbl,
            "hit": (m["l"] + slot * i, m["t"], slot, ih + 2),
            "aria": f"{label(d)}: " + ("sem dados" if d["avg"] is None else f"média {num(d['avg'])}, pico {d['max']}"),
            "tip": _tip(label(d), rows),
        })
    return {"W": W, "H": H, "m": m, "ticks": ticks, "cols": cols}


def heat_model(matrix: List[list], hfrom: int, hto: int) -> dict:
    """Mapa de calor: dia da semana × hora (uma matiz; valor baixo escuro → alto claro). `fill` é o índice 0..10 da paleta."""
    W, m = 680, {"l": 34, "r": 6, "t": 20, "b": 6}
    hours = list(range(hfrom, hto))
    cw = (W - m["l"] - m["r"]) / max(1, len(hours))
    ch = 26
    H = m["t"] + ch * 7 + m["b"]
    flat = [v for row in matrix for v in row if v is not None]
    mx = max(flat + [0.0001])
    hour_labels = [{"x": m["l"] + cw * i + cw / 2, "text": str(x)} for i, x in enumerate(hours)
                   if len(hours) <= 12 or i % 2 == 0]
    rows = []
    for r, row in enumerate(matrix):
        cells = []
        for i, x in enumerate(hours):
            v = row[x] if x < len(row) else None
            empty = v is None
            cells.append({
                "x": m["l"] + cw * i + 1, "y": m["t"] + ch * r + 1, "w": cw - 2, "h": ch - 2,   # 2 px de ar entre as células
                "fill": None if empty else min(10, round(v / mx * 10)),
                "hit": (m["l"] + cw * i, m["t"] + ch * r, cw, ch),
                "tip": _tip(f"{WD_SHORT[r]}, {hh(x)}", [{"text": "sem dados" if empty else f"Média: {num(v)} pessoas"}]),
            })
        rows.append({"label": WD_SHORT[r], "ly": m["t"] + ch * r + ch / 2 + 4, "cells": cells})
    return {"W": W, "H": H, "m": m, "hour_labels": hour_labels, "rows": rows, "max": max(flat) if flat else 0}


def _mins(t: str) -> int:
    return int(t[:2]) * 60 + int(t[3:])


def day_model(series: List[dict], hfrom: int, hto: int) -> dict:
    """Linha do dia: área de 10% + linha de 2 px; a linha quebra nas lacunas (> 15 min sem dado)."""
    W, H, m = 680, 230, {"l": 36, "r": 12, "t": 14, "b": 24}
    iw, ih = W - m["l"] - m["r"], H - m["t"] - m["b"]
    x0, x1 = hfrom * 60, hto * 60
    pts = [{**p, "m": _mins(p["t"])} for p in series if p["avg"] is not None and x0 <= _mins(p["t"]) < x1]
    y_max = nice_max(max([0] + [p["max"] or 0 for p in pts]))

    def X(mm):
        return m["l"] + ((mm - x0) / (x1 - x0)) * iw

    def Y(v):
        return m["t"] + ih - (v / y_max) * ih

    ticks = [{"y": Y(y_max / 4 * i), "label": compact(y_max / 4 * i), "base": i == 0} for i in range(5)]
    step = 3 if hto - hfrom > 14 else 2
    x_labels = [{"x": X(x * 60), "text": f"{x}h"} for x in range(hfrom, hto + 1, step)]
    runs: List[list] = []
    cur: list = []
    for i, p in enumerate(pts):
        if i and p["m"] - pts[i - 1]["m"] > 15:
            runs.append(cur)
            cur = []
        cur.append(p)
    if cur:
        runs.append(cur)
    paths = [{"pts": [(X(p["m"]), Y(p["avg"])) for p in run], "base": Y(0)} for run in runs]

    def nearest(vx: float) -> Optional[dict]:
        """Ponto mais próximo de uma posição X (em unidades do espaço lógico)."""
        if not pts:
            return None
        mm = x0 + ((vx - m["l"]) / iw) * (x1 - x0)
        p = min(pts, key=lambda q: abs(q["m"] - mm))
        return {"x": X(p["m"]), "y": Y(p["avg"]),
                "tip": _tip(p["t"], [{"key": SERIES_1, "text": f"Média: {num(p['avg'])} pessoas"},
                                     {"text": f"Pico: {p['max']} pessoas"}])}

    return {"W": W, "H": H, "m": m, "iw": iw, "ih": ih, "ticks": ticks, "x_labels": x_labels, "paths": paths,
            "empty": not pts, "nearest": nearest}


def bars_model(items: List[dict]) -> dict:
    """Barras horizontais (áreas mais cheias)."""
    row_h, m, W = 30, {"l": 112, "r": 54, "t": 4}, 680
    H = m["t"] + row_h * len(items) + 4
    mx = nice_max(max([a["avg"] or 0 for a in items] + [0]))
    rows = []
    for i, a in enumerate(items):
        yy = m["t"] + row_h * i
        ln = max(2, ((a["avg"] or 0) / mx) * (W - m["l"] - m["r"]))
        bh = 14
        by = yy + (row_h - bh) / 2
        name = a["name"] if len(a["name"]) <= 16 else a["name"][:15] + "…"
        rows.append({
            "name": name, "by": by, "len": ln, "lx": m["l"] + ln + 6, "value": num(a["avg"]),
            "rect": {"x0": m["l"], "x1": m["l"] + ln, "y0": by, "y1": by + bh, "r": min(4, ln / 2)},
            "hit": (yy, row_h), "aria": f"{a['name']}: média {num(a['avg'])}",
            "tip": _tip(a["name"], [{"key": SERIES_1, "text": f"Média: {num(a['avg'])} pessoas"},
                                    {"text": f"Pico: {a['max']} pessoas"}]),
        })
    return {"W": W, "H": H, "m": m, "rows": rows}


def weekly(daily: List[dict]) -> List[dict]:
    """Períodos longos: agrupa por semana (segunda-feira), média ponderada pelas amostras."""
    out: dict = {}
    for d in daily:
        dt = date.fromisoformat(d["date"])
        monday = dt - timedelta(days=dt.weekday())
        key = monday.isoformat()
        w = out.setdefault(key, {"date": key, "n": 0, "sum": 0.0, "max": 0})
        w["n"] += d["samples"]
        w["sum"] += (d["avg"] or 0) * d["samples"]
        w["max"] = max(w["max"], d["max"])
    return [{"date": w["date"], "avg": w["sum"] / w["n"] if w["n"] else None, "max": w["max"], "samples": w["n"]}
            for w in out.values()]


def day_label(d: dict) -> str:
    return br_date(d["date"])
