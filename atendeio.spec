# PyInstaller: executável Windows em modo pasta (onedir). Gerar com scripts/build_windows.ps1.
# Modo pasta, e não onefile: cada arranque extrairia tudo para uma pasta temporária e há menos falsos positivos.
# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "frontend" / "www"), "frontend/www"),   # interface Ionic/Angular (build:web)
    (str(ROOT / "static"), "static"),                    # painel antigo: o FastAPI monta-o no arranque
    (str(ROOT / "yolov8n.pt"), "."),                    # pesos incluídos: nada a descarregar na instalação
    (str(ROOT / "yolov8n-seg.pt"), "."),
]
binaries = []
hiddenimports = collect_submodules("atendeio") + collect_submodules("uvicorn")

for package in ("ultralytics", "pystray", "webview", "pygrabber"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "IPython", "pytest", "matplotlib.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="atendeIO",
    console=False,          # janela própria: sem consola; os logs vão para %APPDATA%\atendeIO\logs
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="atendeIO",
)
