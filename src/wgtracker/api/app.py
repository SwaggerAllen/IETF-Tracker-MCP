"""FastAPI application factory.

Single Web Service hosting: the debug-UI JSON API (Basic auth), MCP-over-HTTP
(bearer auth), an open ``/health`` endpoint, and the built React SPA served
same-origin from ``static/`` when present.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from wgtracker.api import routes_ui
from wgtracker.api.deps import require_ui_auth
from wgtracker.db.session import make_session_factory
from wgtracker.logging import configure_logging, get_logger
from wgtracker.settings import Settings, get_settings

log = get_logger(__name__)


def create_app(
    *, settings: Settings | None = None, session_factory: sessionmaker[Session] | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    factory = session_factory or make_session_factory(settings.database_url)

    mcp = None
    try:
        from wgtracker.mcp_server.server import build_mcp

        mcp = build_mcp(factory)
    except Exception as exc:  # MCP optional; never block the API/UI from booting
        log.warning("mcp_build_failed", error=str(exc))

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if mcp is not None:
            from wgtracker.mcp_server.server import mcp_lifespan

            async with mcp_lifespan(mcp):
                yield
        else:
            yield

    app = FastAPI(
        title="WG Activity Tracker",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.session_factory = factory

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(routes_ui.router, prefix="/api", dependencies=[Depends(require_ui_auth)])

    if mcp is not None:
        try:
            app.mount("/mcp", mcp.streamable_http_app())
        except Exception as exc:
            log.warning("mcp_mount_failed", error=str(exc))

    @app.middleware("http")
    async def mcp_bearer_auth(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path.startswith("/mcp") and settings.mcp_bearer_token:
            header = request.headers.get("authorization", "")
            token = header[7:] if header.lower().startswith("bearer ") else ""
            if not secrets.compare_digest(token, settings.mcp_bearer_token):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

    static_dir = Path(os.getenv("STATIC_DIR", "static"))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="spa")
    else:
        log.info("spa_static_dir_absent", path=str(static_dir))

    return app


app = create_app()
