"""Fábrica da aplicação FastAPI."""

import asyncio
import contextlib
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..config import Settings
from ..container import Container, build_container
from . import errors, middleware
from .routes import auth, cameras, cloud, events, flow, health, pages, recognition, spa, stream, tickets, zones


def create_app(settings: Optional[Settings] = None, container: Optional[Container] = None) -> FastAPI:
    container = container or build_container(settings or Settings.from_env())

    lag = {"max": 0.0, "recent": []}   # atraso do laço de eventos nos últimos ~60 s (sentinela)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        loop = asyncio.get_running_loop()

        async def reaper():
            while True:
                await asyncio.sleep(10)
                await loop.run_in_executor(None, container.registry.reap_idle)

        async def sentinel():
            """Se o laço de eventos demorar a acordar, algo está bloqueando a aplicação: mede e avisa."""
            while True:
                t0 = loop.time()
                await asyncio.sleep(0.1)
                delay = max(0.0, loop.time() - t0 - 0.1) * 1000
                lag["recent"] = [(t, d) for t, d in lag["recent"] if t0 - t < 60] + [(t0, delay)]
                if delay > 200:
                    print(f"[!] laço de eventos atrasou {delay:.0f} ms: algo está bloqueando a aplicação")

        container.flow_writer.start()
        container.exporter.start()
        container.scheduler.start()
        tasks = [asyncio.create_task(reaper()), asyncio.create_task(sentinel())]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            container.scheduler.stop()
            container.registry.stop_all()      # cada hub entrega o histórico que sobrou ao escritor...
            container.exporter.stop()          # ...e os eventos pendentes à outbox (sem esperar pela rede)...
            container.flow_writer.stop()       # ...que grava tudo antes de sair

    # Sem /docs nem /openapi.json: o painel não precisa expor o esquema da API.
    app = FastAPI(title="atendeIO", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.container = container
    app.state.loop_lag_ms = lambda: round(max((d for _, d in lag["recent"]), default=0.0), 1)
    app.mount("/static", StaticFiles(directory=container.settings.static_dir), name="static")
    middleware.install(app, container.settings.cors_origins)
    if container.settings.cors_origins:   # só apps nativos listados; sem credenciais de navegador (usam Bearer)
        app.add_middleware(CORSMiddleware, allow_origins=list(container.settings.cors_origins), allow_credentials=False,
                           allow_methods=["GET", "POST", "PUT", "DELETE"],
                           allow_headers=["Authorization", "Content-Type", "Last-Event-ID"])
    errors.install(app)
    for module in (pages, auth, cameras, zones, recognition, stream, events, tickets, flow, health, cloud, spa):
        app.include_router(module.router)
    return app
