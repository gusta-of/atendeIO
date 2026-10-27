#!/usr/bin/env python3
"""Cria um utilizador (útil com ATENDEIO_ALLOW_SIGNUP=0).

    python scripts/add_user.py maria            # pergunta a senha sem ecoar
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atendeio.config import Settings  # noqa: E402
from atendeio.container import build_container  # noqa: E402
from atendeio.errors import DomainError  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    password = getpass.getpass("Senha (mín. 8): ")
    if password != getpass.getpass("Repita a senha: "):
        raise SystemExit("As senhas não conferem.")
    try:
        build_container(Settings.from_env()).auth.create_user(sys.argv[1], password)
    except DomainError as e:
        raise SystemExit(str(e))
    print(f"Utilizador '{sys.argv[1].strip().lower()}' criado.")


if __name__ == "__main__":
    main()
