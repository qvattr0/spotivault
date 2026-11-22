"""Setup wizard endpoints (openapi.yaml tag `setup`), except the checklist confirm, which
is in routers/client.py. The step rules are in spotivault/setup.py."""

from fastapi import APIRouter

from spotivault.api.deps import ServicesDep
from spotivault.api.models import AcknowledgeTosRequest, Setup

router = APIRouter(tags=["setup"])


@router.get("/api/setup", operation_id="getSetup", response_model=Setup)
async def get_setup(services: ServicesDep) -> Setup:
    """Each step's state after running the live checks."""
    return await services.setup.refresh()


@router.post(
    "/api/setup/tos",
    operation_id="acknowledgeTos",
    response_model=Setup,
    responses={422: {"description": "`understood` isn't true (`validation_failed`)."}},
)
async def acknowledge_tos(body: AcknowledgeTosRequest, services: ServicesDep) -> Setup:
    return await services.setup.acknowledge_tos()


@router.post(
    "/api/setup/restart",
    operation_id="restartSetup",
    response_model=Setup,
    responses={409: {"description": "A backup is recording (`run_active`)."}},
)
async def restart_setup(services: ServicesDep) -> Setup:
    """Settings › About › "Run setup again": reopens the wizard from step 2."""
    return await services.setup.restart()


@router.post("/api/setup/albums/later", operation_id="chooseAlbumsLater", response_model=Setup)
async def choose_albums_later(services: ServicesDep) -> Setup:
    """Step 8's "I'll choose in Albums": the step is done, and nothing is queued. The other
    answer, "Back up all my saved albums", is POST /api/albums, which marks it done too."""
    return await services.setup.mark_done("albums")


@router.post(
    "/api/setup/complete",
    operation_id="completeSetup",
    response_model=Setup,
    responses={409: {"description": "A step from 1 to 6 isn't done (`setup_incomplete`)."}},
)
async def complete_setup(services: ServicesDep) -> Setup:
    """Step 9's Open Library and Back up now: finishes the wizard."""
    return await services.setup.complete()
