"""Rótulos, cores e formatação do Salão (porta de `shared/area-labels.ts` e `shared/format.ts`). Sem Qt."""

from typing import Optional

STATUS = {
    "livre": ("Livre", "#34d399"),
    "ocupada": ("Ocupada", "#f87171"),
    "a_limpar": ("A limpar", "#fbbf24"),
}
KIND_COLOR = {"mesa": "#22d3ee", "balcao": "#a78bfa", "entrada": "#34d399", "saida": "#fb923c", "fila": "#f472b6",
              "area": "#94a3b8"}
KIND_LABEL = {"mesa": "Mesa", "balcao": "Balcão", "entrada": "Entrada", "saida": "Saída", "fila": "Fila", "area": "Área"}
GRAY = "#94a3b8"


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def fmt_dur(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {(s % 3600) // 60:02d}"


def no_reading(state: Optional[dict]) -> bool:
    """Reconhecimento desligado, nenhum objeto marcado ou "Pessoa" desmarcada: o estado das mesas não é confiável."""
    r = (state or {}).get("recognition")
    return bool(r) and (not r.get("enabled") or r.get("classes") == 0 or r.get("person") is False)


def reading_hint(state: Optional[dict]) -> str:
    r = (state or {}).get("recognition")
    if not r:
        return ""
    if not r.get("enabled"):
        return "reconhecimento desligado"
    if r.get("classes") == 0:
        return "nenhum objeto selecionado"
    if not r.get("person"):
        return "marque “Pessoa” em Objetos"
    return ""


def area_color(kind: str, area: Optional[dict], blind: bool) -> str:
    if kind == "mesa":
        if blind:
            return GRAY
        return STATUS[area["status"]][1] if area and area.get("status") else KIND_COLOR["mesa"]
    return KIND_COLOR.get(kind, KIND_COLOR["area"])


def area_caption(kind: str, area: Optional[dict]) -> str:
    """Texto para a lista do Salão (tempo ocupada, espera da fila...)."""
    if not area:
        return ""
    people = area.get("people", 0)
    if kind == "mesa":
        status = area.get("status") or "livre"
        if status == "ocupada":
            return f"{plural(people, 'pessoa', 'pessoas')} · {fmt_dur(area.get('seconds') or 0)}"
        return f"{STATUS[status][0]} · {fmt_dur(area.get('seconds') or 0)}"
    if kind == "fila":
        return plural(people, "pessoa", "pessoas") + (f" · espera {fmt_dur(area.get('wait') or 0)}" if people else "")
    return plural(people, "pessoa", "pessoas")


def natural_key(name: str) -> list:
    """Ordem natural: "Mesa 2" antes de "Mesa 10"."""
    import re
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


_OBJECT_LABELS: dict = {}


def object_label(name: str) -> str:
    """Rótulo em português de uma classe do YOLO ("person" -> "Pessoa"); o que não estiver no catálogo volta como veio."""
    if not _OBJECT_LABELS:
        from ..vision.classes import catalog
        _OBJECT_LABELS.update({c["name"]: c["label"] for c in catalog()})
    return _OBJECT_LABELS.get(name, name)


def sorted_counts(counts: list) -> list:
    """Objetos reconhecidos: mais frequentes primeiro; empate em ordem alfabética (a ordem não pula à toa)."""
    return sorted(counts, key=lambda c: (-c["count"], object_label(c["name"]).lower()))
