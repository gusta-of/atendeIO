"""Aplicação de desktop: servidor + janela própria + ícone na bandeja.

`python -m atendeio.desktop` (também é o alvo do PyInstaller). Fechar a janela só a esconde na bandeja: o servidor
e o monitoramento continuam a correr. "Sair" no menu da bandeja encerra tudo.
"""

import argparse
import dataclasses
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from . import paths
from .config import Settings

NAME = "atendeIO"
WINDOWS = sys.platform == "win32"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
ERROR_ALREADY_EXISTS = 183

_mutex = None  # guardado num global para o handle do mutex não ser libertado


# -- ambiente -------------------------------------------------------------

def _redirect_logs(data: Path) -> None:
    """O executável é janela (sem consola): stdout/stderr vão para ficheiros de sessão, mantendo os 10 últimos."""
    if not paths.is_frozen():
        return
    log_dir = data / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    for old in sorted(log_dir.glob("atendeio-*.log"))[:-9]:
        old.unlink(missing_ok=True)
    log = open(log_dir / f"atendeio-{datetime.now():%Y%m%d-%H%M%S}.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log


def _claim_single_instance() -> bool:
    """Mutex nomeado do Windows. False se já há uma instância a correr."""
    global _mutex
    if not WINDOWS:
        return True
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _mutex = kernel32.CreateMutexW(None, False, f"Local\\{NAME}-instancia-unica")
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def _bring_existing_to_front() -> None:
    import ctypes
    user32 = ctypes.WinDLL("user32")
    hwnd = user32.FindWindowW(None, NAME)
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE: mostra também se estiver escondida na bandeja
        user32.SetForegroundWindow(hwnd)


def _pick_port(preferred: int) -> int:
    """Porta fixa (8000) para o service worker e o localStorage manterem a mesma origem entre aberturas.
    Se estiver ocupada, usa uma porta livre."""
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# -- arranque com o Windows ----------------------------------------------

def _autostart_command() -> str:
    if paths.is_frozen():
        return f'"{sys.executable}" --oculto'
    return f'"{sys.executable}" -m atendeio.desktop --oculto'


def autostart_enabled() -> bool:
    if not WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, NAME)
        return True
    except FileNotFoundError:
        return False


def set_autostart(on: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, _autostart_command())
            return
        try:
            winreg.DeleteValue(key, NAME)
        except FileNotFoundError:
            pass


# -- servidor ------------------------------------------------------------

class LocalServer:
    """uvicorn numa thread, só em loopback. O YOLO aquece em paralelo: a janela já abre."""

    def __init__(self, settings: Settings):
        import uvicorn
        from .api.app import create_app
        self.app = create_app(settings)
        self.server = uvicorn.Server(uvicorn.Config(self.app, host=settings.host, port=settings.port,
                                                    access_log=False))
        self.thread = threading.Thread(target=self.server.run, name="uvicorn")
        self.url = f"http://{settings.host}:{settings.port}/app/"

    def start(self, timeout_s: float = 30.0) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout_s
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError("O servidor não arrancou.")
            time.sleep(0.1)
        threading.Thread(target=self.app.state.container.detector.load, name="yolo", daemon=True).start()

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=20)


# -- bandeja ---------------------------------------------------------------

class Tray:
    def __init__(self, on_open, on_quit):
        import pystray
        from PIL import Image, ImageDraw
        icon_image = Image.new("RGB", (64, 64), (16, 110, 90))
        ImageDraw.Draw(icon_image).ellipse((18, 18, 46, 46), fill=(255, 255, 255))
        menu = pystray.Menu(
            pystray.MenuItem("Abrir atendeIO", lambda icon, item: on_open(), default=True),
            pystray.MenuItem("Iniciar com o Windows",
                             lambda icon, item: set_autostart(not autostart_enabled()),
                             checked=lambda item: autostart_enabled()),
            pystray.MenuItem("Sair", lambda icon, item: on_quit()),
        )
        self._icon = pystray.Icon(NAME, icon_image, NAME, menu)

    def start(self) -> "Tray":
        self._icon.run_detached()
        return self

    def stop(self) -> None:
        self._icon.stop()


def _start_tray(on_open, on_quit):
    try:
        return Tray(on_open, on_quit).start()
    except Exception as exc:  # sem bandeja, fechar a janela encerra a aplicação (dito no log)
        print(f"[!] Sem ícone na bandeja ({exc}). Fechar a janela vai encerrar o atendeIO.")
        return None


# -- ponto de entrada -----------------------------------------------------

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog=NAME)
    ap.add_argument("--oculto", action="store_true",
                    help="arranca só na bandeja (usado pelo arranque com o Windows)")
    args = ap.parse_args(argv)

    if not _claim_single_instance():
        _bring_existing_to_front()
        return

    settings = Settings.from_env()
    _redirect_logs(settings.data_dir)
    marker = settings.data_dir / "arranque-definido"
    if WINDOWS and not marker.exists():  # primeira abertura: fica ligado ao arranque do Windows
        set_autostart(True)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1", encoding="utf-8")

    settings = dataclasses.replace(settings, port=_pick_port(settings.port))
    server = LocalServer(settings)
    server.start()
    print(f"[*] atendeIO em {server.url}")

    quitting = threading.Event()
    tray = None
    window = None

    def quit_app() -> None:
        quitting.set()
        if tray:
            tray.stop()
        if window:
            window.destroy()

    try:
        import webview
        window = webview.create_window(NAME, server.url, width=1280, height=820, min_size=(960, 640),
                                       hidden=args.oculto)
        tray = _start_tray(lambda: window.show(), quit_app)
        if tray is None:
            window.show()

        def on_closing():
            if quitting.is_set() or tray is None:
                return True   # sem bandeja, fechar a janela encerra
            window.hide()     # com bandeja, o servidor e o monitoramento continuam
            return False

        window.events.closing += on_closing
        webview.start()
    except Exception as exc:
        print(f"[!] Janela própria indisponível ({exc}). A abrir no navegador.")
        webbrowser.open(server.url)
        tray = _start_tray(lambda: webbrowser.open(server.url), quit_app)
        while not quitting.wait(1):
            pass
    finally:
        if tray:
            tray.stop()
        server.stop()
        print("[*] atendeIO encerrado.")


if __name__ == "__main__":
    main()
