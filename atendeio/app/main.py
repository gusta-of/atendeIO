"""Ponto de entrada do app desktop: UM processo, interface Qt, nenhuma porta aberta."""

import os
import signal
import sys
import threading
from pathlib import Path


def main() -> int:
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    from PySide6.QtCore import QLockFile, QStandardPaths, QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from ..config import Settings
    from .bridge import Bridge
    from .core import AppCore
    from .theme import QSS
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("atendeIO")
    app.setOrganizationName("atendeIO")
    app.setStyleSheet(QSS)
    icon = QIcon(str(Path(__file__).parent / "assets" / "icon.png"))
    app.setWindowIcon(icon)

    data_root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    data_root.mkdir(parents=True, exist_ok=True)
    # Uma instância por computador (as câmeras são exclusivas). Arquivo de trava, sem abrir porta nem socket.
    lock = QLockFile(str(data_root / "atendeio.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        QMessageBox.information(None, "atendeIO", "O atendeIO já está aberto neste computador.")
        return 0

    overrides = {} if os.environ.get("ATENDEIO_DATA") else {"data_dir": data_root / "data"}
    core = AppCore(Settings.from_env(mode="desktop", **overrides))
    core.start()
    threading.Thread(target=core.preload_model, name="model-warmup", daemon=True).start()

    bridge = Bridge()
    window = MainWindow(core, bridge, icon)
    # Ctrl+C / kill: encerra COM limpeza (grava o histórico). O Qt só devolve o controle ao Python de tempos em tempos.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: window.quit_app())
    wake = QTimer()
    wake.start(300)
    wake.timeout.connect(lambda: None)
    if "--hidden" not in sys.argv:
        window.showMaximized()              # abre ocupando a tela toda
    try:
        return app.exec()
    finally:
        core.stop()        # hubs entregam o histórico, o escritor grava, o cofre de credenciais é esquecido
        lock.unlock()


if __name__ == "__main__":
    sys.exit(main())
