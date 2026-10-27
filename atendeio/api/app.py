"""Fábrica da aplicação FastAPI."""

import asyncio
import contextlib
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..config import Settings
from ..container import Container, build_container
from . import errors, middleware
from .routes import auth, cameras, events, pages, recognition, stream, zones


def create_app(settings: Optional[Settings] = None, container: Optional[Container] = None) -> FastAPI:
    container = container or build_container(settings or Settings.from_env())

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async def reaper():
            loop = asyncio.get_running_loop()
            while True:
                await asyncio.sleep(10)
                await loop.run_in_executor(None, container.registry.reap_idle)

        task = asyncio.create_task(reaper())
        try:
            yield
        finally:
            task.cancel()
            container.registry.stop_all()

    # Sem /docs nem /openapi.json: o painel não precisa expor o esquema da API.
    app = FastAPI(title="atendeIO", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.container = container
    app.mount("/static", StaticFiles(directory=container.settings.static_dir), name="static")
    middleware.install(app)
    errors.install(app)
    for module in (pages, auth, cameras, zones, recognition, stream, events):
        app.include_router(module.router)
    return app
