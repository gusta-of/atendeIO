"""Serve o frontend novo (Ionic/Angular compilado) em /app/, com fallback de SPA.

- arquivo existente  -> o arquivo (com cache certo pro tipo);
- rota do app (sem extensão, ex.: /app/analise) -> index.html, pra o roteador do Angular resolver;
- arquivo com extensão que não existe -> 404 de verdade (nunca devolve HTML no lugar de um .js).
Público de propósito: é só a casca estática; todos os dados continuam atrás do login da API."""

import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

router = APIRouter(include_in_schema=False)

HASHED = re.compile(r"[-.][A-Za-z0-9_]{8,}\.(js|css|woff2?|svg|png|jpg|webp)$")   # main-ABCD1234.js, chunk-xxxx.js
NO_CACHE = {"index.html", "ngsw.json", "ngsw-worker.js", "safety-worker.js", "worker-basic.min.js",
            "manifest.webmanifest"}   # trocam a cada versão: o navegador sempre revalida


def _headers(name: str) -> dict:
    if name in NO_CACHE:
        return {"Cache-Control": "no-cache"}
    if HASHED.search(name):
        return {"Cache-Control": "public, max-age=31536000, immutable"}   # o nome muda com o conteúdo
    return {"Cache-Control": "public, max-age=3600"}


def _safe(base: Path, rel: str):
    """O arquivo dentro de `base` (ou None). Barra `..`, links e qualquer coisa fora da pasta compilada."""
    try:
        target = (base / rel).resolve()
        target.relative_to(base.resolve())
    except (ValueError, OSError):
        return None
    return target if target.is_file() else None


@router.get("/app")
def app_root():
    return RedirectResponse("/app/", status_code=308)


@router.get("/app/{path:path}")
def app_files(path: str, request: Request):
    base: Path = request.app.state.container.settings.frontend_dir
    if not (base / "index.html").is_file():
        return JSONResponse({"detail": "Frontend não compilado. Rode: cd frontend && npm run build:web"}, status_code=404)
    if path:
        f = _safe(base, path)
        if f is not None:
            return FileResponse(f, headers=_headers(f.name))
        if "." in path.rsplit("/", 1)[-1]:   # parece arquivo (tem extensão) e não existe
            return Response(status_code=404)
    return FileResponse(base / "index.html", headers=_headers("index.html"))   # rota do app: o Angular decide
