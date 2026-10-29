#!/usr/bin/env python3
"""Empacota o motor Python (FastAPI + YOLO + OpenCV) numa pasta autônoma com PyInstaller.

Roda no sistema de destino (PyInstaller não faz cross-compile): Windows gera .exe, Linux e macOS o binário deles.
Saída: desktop/engine-dist/atendeio-engine/  (o electron-builder copia essa pasta para dentro do instalador).

    python desktop/engine/build_engine.py            # precisa de: pip install pyinstaller  e  pnpm --dir web run build:desktop
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "desktop" / "engine-dist"
WORK = ROOT / "desktop" / "engine-build"


def data(src: Path, dest: str) -> list:
    return ["--add-data", f"{src}{os.pathsep}{dest}"]


def main() -> int:
    web = next((ROOT / n for n in ("web", "frontend") if (ROOT / n / "angular.json").exists()), None)
    www = (web or ROOT / "web") / "www-desktop"
    if not (www / "index.html").exists():
        print(f"[-] Falta a interface: rode  pnpm --dir {web.name if web else 'web'} run build:desktop", file=sys.stderr)
        return 1
    for name in ("yolov8n.pt",):
        if not (ROOT / name).exists():
            print(f"[-] Falta {name} na raiz do projeto (o instalador leva os pesos; não baixa no 1º uso).", file=sys.stderr)
            return 1
    shutil.rmtree(OUT, ignore_errors=True)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "atendeio-engine",
           "--distpath", str(OUT), "--workpath", str(WORK), "--specpath", str(WORK),
           "--collect-all", "ultralytics",
           "--collect-all", "torchvision",                   # registra os operadores nativos (nms etc.); sem isso o motor quebra
           *data(ROOT / "static", "static"),                 # painel antigo ainda é montado em /static pelo app
           *data(www, "frontend/www"),                       # interface (Ionic/Angular) servida em /app/
           *data(ROOT / "yolov8n.pt", ".")]
    seg = ROOT / "yolov8n-seg.pt"
    if seg.exists():
        cmd += data(seg, ".")
    cmd.append(str(ROOT / "app.py"))
    print("[*]", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
