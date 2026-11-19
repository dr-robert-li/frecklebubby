"""FastAPI app: API routers, MCP at /mcp, static SPA, reminder loop."""

import asyncio
import logging
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastmcp.server.auth.providers.clerk import ClerkProvider
from starlette.routing import Route

from .api import children, core, notify
from .config import get_settings
from .db import SessionLocal, init_db, utcnow
from .mcp_server import create_mcp
from .services import ServiceError
from .services.notifications import vapid
from .services.reminders import tick

log = logging.getLogger(__name__)

API = "/api/v1"
STATIC = Path(__file__).parent / "static"


async def _reminder_loop() -> None:
    # shortcut: in-process scheduler; move to a job runner if more than one worker is necessary.
    while True:
        try:
            await asyncio.to_thread(_tick_once)
        except Exception:
            log.exception("Reminder tick failed")
        await asyncio.sleep(60)


def _tick_once() -> None:
    with SessionLocal() as s:
        tick(s, utcnow())


def _validation_message(err: RequestValidationError) -> str:
    parts = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path"))
        parts.append(f"{loc}: {e['msg']}" if loc else e["msg"])
    return "; ".join(parts)


async def _spa(request: Request):
    """Serve built frontend files; unknown non-API paths get index.html (SPA routing)."""
    path = request.path_params["path"]
    index = STATIC / "index.html"
    if path.startswith(("api/", "mcp")) or not index.is_file():
        return JSONResponse({"detail": "Not found."}, 404)
    file = (STATIC / path).resolve()
    if path and file.is_file() and file.is_relative_to(STATIC.resolve()):
        return FileResponse(file)
    return FileResponse(index)


def create_app(scheduler: bool = True) -> FastAPI:
    settings = get_settings()
    settings.check()
    if settings.auth_mode == "dev":
        log.warning("AUTH_MODE=dev: anyone who can reach this server can sign in as any user. Use only for development.")
    init_db(settings.data_dir)
    vapid()  # make the VAPID keys on first start

    auth = None
    if settings.auth_mode == "clerk":
        auth = ClerkProvider(domain=settings.clerk_domain, client_id=settings.clerk_oauth_client_id,
                             client_secret=settings.clerk_oauth_client_secret,
                             base_url=settings.base_url.rstrip("/"))
    # Tools keep no per-session state; stateless survives restarts and idle expiry.
    mcp_app = create_mcp(auth=auth).http_app(path="/mcp", stateless_http=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp_app.lifespan(app):
            task = asyncio.create_task(_reminder_loop()) if scheduler else None
            try:
                yield
            finally:
                if task:
                    task.cancel()

    app = FastAPI(title="Frecklebubby", version=version("frecklebubby"), lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    @app.exception_handler(ServiceError)
    async def _service_error(_request: Request, err: ServiceError):
        return JSONResponse({"detail": str(err)}, err.status)

    @app.exception_handler(RequestValidationError)
    async def _request_invalid(_request: Request, err: RequestValidationError):
        return JSONResponse({"detail": _validation_message(err)}, 422)

    app.include_router(core.router, prefix=API)
    app.include_router(children.router, prefix=API)
    app.include_router(notify.router, prefix=API)
    # Later milestones add their routers here, one line each, for example:
    # app.include_router(nl.router, prefix=API)

    # MCP (and in clerk mode its OAuth routes) at the root; the SPA catch-all comes last.
    mcp_app.router.routes.append(Route("/{path:path}", _spa, methods=["GET", "HEAD"]))
    app.mount("/", mcp_app)
    return app


def run() -> None:
    """Console entry point: frecklebubby."""
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    uvicorn.run(create_app(), host=settings.host, port=settings.port, workers=1)
