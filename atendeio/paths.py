"""Caminhos da aplicação: recursos (só leitura) separados dos dados do utilizador (escrita).

Em desenvolvimento (código-fonte) tudo continua dentro do repositório. No executável
PyInstaller (`sys.frozen`), os recursos ficam em `sys._MEIPASS` e os dados vão para
%APPDATA%\\atendeIO, porque a pasta de instalação não deve ser escrita pelo utilizador.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def resource_dir() -> Path:
    """Onde estão os ficheiros só de leitura: frontend compilado, static/, pesos YOLO."""
    if is_frozen():
        return Path(sys._MEIPASS)
    return ROOT


def data_dir() -> Path:
    """Onde ficam banco, chave Fernet e logs. `ATENDEIO_DATA` tem sempre prioridade."""
    override = os.environ.get("ATENDEIO_DATA")
    if override:
        return Path(override)
    if is_frozen():
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "atendeIO"
    return ROOT / "data"
