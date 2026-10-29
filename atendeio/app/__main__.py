"""`python -m atendeio.app` — abre o app desktop."""

import os
import sys


def _clean_environment() -> None:
    """Terminais de apps em snap (ex.: o VS Code) exportam GSETTINGS_SCHEMA_DIR, GTK_PATH, XDG_DATA_DIRS... apontando para as
    bibliotecas do snap, o que quebra bibliotecas gráficas. O VS Code guarda os originais em <VAR>_VSCODE_SNAP_ORIG."""
    for key in [k for k in os.environ if k.endswith("_VSCODE_SNAP_ORIG")]:
        base, orig = key[: -len("_VSCODE_SNAP_ORIG")], os.environ.pop(key)
        if orig:
            os.environ[base] = orig
        else:
            os.environ.pop(base, None)


if __name__ == "__main__":
    _clean_environment()
    from .main import main
    sys.exit(main())
