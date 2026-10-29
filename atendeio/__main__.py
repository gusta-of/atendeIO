"""`python -m atendeio` — sobe o servidor."""

from .api.app import create_app
from .config import Settings


def _exit_with_parent(server, parent_pid: int, interval_s: float = 2.0) -> None:
    """Encerramento limpo se o app pai (Electron) sumir, inclusive por crash ou kill: sem isso o motor ficaria órfão,
    segurando a câmera e a porta."""
    import threading
    import time

    from .resources import pid_alive

    def watch():
        while not server.should_exit:
            if not pid_alive(parent_pid):
                print("[!] o app pai encerrou: parando o motor")
                server.should_exit = True
                return
            time.sleep(interval_s)

    threading.Thread(target=watch, name="parent-watch", daemon=True).start()


def main() -> None:
    import uvicorn

    settings = Settings.from_env()
    app = create_app(settings)
    app.state.container.detector.load()  # pré-carrega e aquece o YOLO
    from .resources import low_resource_defaults, total_ram_mb
    if low_resource_defaults(total_ram_mb()):
        print(f"[*] pouca RAM ({total_ram_mb()} MB): perfil econômico (sem segmentação, até {settings.max_cameras} câmeras)")
    print(f"[*] atendeIO em http://{settings.host}:{settings.port}"
          f"  (cadastro: {'on' if settings.allow_signup else 'off'})")
    # access_log off: o painel faz polling a cada segundo e encheria o log por horas.
    # UM processo só: câmeras e pipelines vivem em memória.
    server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port, access_log=False))
    app.state.server = server   # o Electron pede o encerramento limpo por /api/desktop/quit (grava o histórico, apaga o cofre)
    if settings.parent_pid:
        _exit_with_parent(server, settings.parent_pid)
    server.run()


if __name__ == "__main__":
    main()
