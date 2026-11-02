"""FastAPI application factory: ``uvicorn --factory qcdb.api.app:create_app``."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from sqlalchemy import Engine

from qcdb import __version__
from qcdb.api.routes import admin, auth, people, results, runs
from qcdb.api.security import Settings
from qcdb.db.engine import make_engine, make_sessionmaker

PREFIX = "/api/v1"
log = logging.getLogger("qcdb.api")


def create_app(engine: Engine | None = None, settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="qcdb API",
        version=__version__,
        description="Per-sample bacterial WGS QC results. Session cookie authentication; "
        "send the CSRF token from /auth/me in the X-CSRF-Token header on POST/PUT/PATCH/DELETE.",
        openapi_url=f"{PREFIX}/openapi.json",
        docs_url=None,  # Swagger UI would load assets from a CDN
        redoc_url=None,
    )
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    app.state.engine = engine or make_engine()
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.state.settings = settings or Settings.from_env()
    for module in (auth, results, runs, people):
        app.include_router(module.router, prefix=PREFIX)
    app.include_router(admin.router, prefix=PREFIX)
    app.include_router(admin.health_router, prefix=PREFIX)

    @app.middleware("http")
    async def access_log(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Path only: query strings can hold searched names (no personal data in logs).
        start = time.perf_counter()
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        log.info(
            "%s %s %s %.0fms",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response

    return app
