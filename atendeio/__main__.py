"""`python -m atendeio` — sobe o servidor."""

from .api.app import create_app
from .config import Settings


def main() -> None:
    import uvicorn

    settings = Settings.from_env()
    app = create_app(settings)
    app.state.container.detector.load()  # pré-carrega e aquece o YOLO
    print(f"[*] atendeIO em http://{settings.host}:{settings.port}"
          f"  (cadastro: {'on' if settings.allow_signup else 'off'})")
    # access_log off: o painel faz polling a cada segundo e encheria o log por horas.
    # UM processo só: câmeras e pipelines vivem em memória.
    uvicorn.run(app, host=settings.host, port=settings.port, access_log=False)


if __name__ == "__main__":
    main()
