"""One router per area of openapi.yaml. app.py includes every one of them, in this order.

Each endpoint is declared with the contract's operationId and models. An endpoint a later step
builds answers 501 (`errors.not_built`) until then. Who owns which file: ARCHITECTURE.md.
"""

from fastapi import APIRouter

from spotivault.api.routers import (
    albums,
    backlog,
    client,
    container,
    covers,
    health,
    history,
    library,
    logs,
    runs,
    schedule,
    settings,
    setup,
    spotify,
    status,
    storage,
    webapi,
)

ROUTERS: list[APIRouter] = [
    health.router,
    setup.router,
    client.router,
    spotify.router,
    storage.router,
    settings.router,
    container.router,
    library.router,
    albums.router,
    covers.router,
    backlog.router,
    status.router,
    runs.router,  # before history.router: /api/runs/current before /api/runs/{id}
    history.router,
    logs.router,
    schedule.router,
    webapi.router,
]
