"""The ASGI app: every REST endpoint of contracts/openapi.yaml, WS /api/events, WS /vnc and the SPA.

    app = create_app(build_services(load_config()))

Every request first passes `web.guard.RequestGuard`: the Host check, and the Origin check on
requests that change something. The routes, in matching order:
1. one router per area (spotivault.api.routers.ROUTERS), each with the contract's operationIds;
2. the WebSockets, `/api/events` and `/vnc` (openapi.yaml `x-websockets`);
3. the SPA's catch-all, last: files from the web root, else index.html; /api/* is a 404 envelope.

FastAPI's own /docs, /redoc and /openapi.json are off: contracts/openapi.yaml is the API's
description, and tests/test_contract_routes.py checks the app against it.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from spotivault import __version__
from spotivault.api.routers import ROUTERS
from spotivault.errors import install_error_handlers
from spotivault.services import Services
from spotivault.web import events_ws, spa, vnc
from spotivault.web.guard import RequestGuard


def create_app(services: Services) -> FastAPI:
    """The app for these services. Its lifespan is `services.running()`."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with services.running():
            yield

    app = FastAPI(
        title="spotivault controller",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.services = services
    app.add_middleware(RequestGuard, allowed_hosts=services.config.allowed_hosts)
    install_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router)
    app.include_router(events_ws.router)
    app.include_router(vnc.router)
    spa.mount(app, services.config)
    return app
