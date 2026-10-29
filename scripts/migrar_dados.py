"""Copia os dados de desenvolvimento (pasta data/) para a pasta do executável (%APPDATA%\\atendeIO).

Copia o banco e a chave Fernet JUNTOS: sem a chave, as credenciais RTSP guardadas ficam ilegíveis.
O banco é copiado com a API de backup do SQLite, por isso pode ser feito com o servidor a correr.

Uso (com o executável fechado):
    python scripts/migrar_dados.py
    python scripts/migrar_dados.py --origem data --destino "%APPDATA%\\atendeIO" --forcar
"""

import argparse
import contextlib
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _default_destino() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "atendeIO"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Migra banco e chave para a pasta do executável.")
    ap.add_argument("--origem", type=Path, default=ROOT / "data")
    ap.add_argument("--destino", type=Path, default=_default_destino())
    ap.add_argument("--forcar", action="store_true", help="substitui os ficheiros que já existem no destino")
    args = ap.parse_args(argv)

    db_src, key_src = args.origem / "atendeio.db", args.origem / "secret.key"
    if not db_src.exists() or not key_src.exists():
        print(f"[!] Faltam ficheiros em {args.origem}: preciso de atendeio.db E secret.key.")
        return 1

    args.destino.mkdir(parents=True, exist_ok=True)
    db_dst, key_dst = args.destino / "atendeio.db", args.destino / "secret.key"
    if (db_dst.exists() or key_dst.exists()) and not args.forcar:
        print(f"[!] Já existem dados em {args.destino}. Use --forcar para substituir.")
        return 1

    with contextlib.closing(sqlite3.connect(db_src)) as src, contextlib.closing(sqlite3.connect(db_dst)) as dst:
        src.backup(dst)  # cópia consistente, mesmo com WAL
    shutil.copy2(key_src, key_dst)
    print(f"[+] Migrado para {args.destino}: atendeio.db e secret.key.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
