"""Formatação em pt-BR (vírgula decimal, durações curtas) e escala de eixos. Porta de `shared/format.ts`."""

import math
from typing import Optional


def num(n: Optional[float], d: int = 1) -> str:
    return "–" if n is None else f"{n:.{d}f}".replace(".", ",")


def pct(x: float) -> str:
    return f"{round(x * 100)}%"


def hh(n: int) -> str:
    return f"{n:02d}h"


def br_date(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


def nice_max(v: float) -> float:
    """Teto "redondo" do eixo (1, 2, 2,5, 5, 10 × potência de 10)."""
    if not v > 0:
        return 1
    p = 10 ** math.floor(math.log10(v))
    f = v / p
    return (1 if f <= 1 else 2 if f <= 2 else 2.5 if f <= 2.5 else 5 if f <= 5 else 10) * p


def compact(v: float) -> str:
    """Rótulo curto de eixo: 1,5K a partir de mil."""
    if v >= 1000:
        return (f"{v / 1000:.1f}" if v % 1000 else f"{v / 1000:.0f}").replace(".", ",") + "K"
    r = round(v * 10) / 10
    return (str(int(r)) if r == int(r) else str(r)).replace(".", ",")
