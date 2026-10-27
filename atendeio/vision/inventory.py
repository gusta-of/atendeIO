"""Inventário do ambiente a partir das detecções (puro: sem OpenCV, fácil de testar)."""


def summarize(dets: list) -> dict:
    """Total e contagem por classe (maior primeiro)."""
    counts = {}
    for d in dets:
        counts[d["name"]] = counts.get(d["name"], 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"total": len(dets), "counts": [{"name": n, "count": c} for n, c in ordered]}
