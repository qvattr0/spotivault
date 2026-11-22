"""Spotify client endpoints (openapi.yaml tag `client`), plus step 4's checklist confirm.

Owner: the client agent. The work is in `services.client` (client/manager.py).
"""

from fastapi import APIRouter

from spotivault.api.deps import ServicesDep
from spotivault.api.models import Checklist, ClientInstall, ClientStatus, ConfirmChecklistRequest

router = APIRouter(tags=["client"])

_RUN_ACTIVE = {409: {"description": "Not allowed while a backup is recording (`run_active`)."}}


@router.post(
    "/api/setup/checklist/confirm",
    operation_id="confirmChecklist",
    response_model=Checklist,
    tags=["setup"],
    responses={422: {"description": "A row that isn't a Confirm row (`validation_failed`)."}},
)
async def confirm_checklist(body: ConfirmChecklistRequest, services: ServicesDep) -> Checklist:
    return await services.client.confirm(body.rows)


@router.get("/api/client/status", operation_id="getClientStatus", response_model=ClientStatus)
async def get_client_status(services: ServicesDep) -> ClientStatus:
    return await services.client.status()


@router.post(
    "/api/client/install",
    operation_id="installClient",
    response_model=ClientInstall,
    status_code=202,
    responses={
        409: {
            "description": "An install is already running (`install_in_progress`), or a run "
            "is active (`run_active`)."
        }
    },
)
async def install_client(services: ServicesDep) -> ClientInstall:
    return await services.client.start_install()


@router.get("/api/client/checklist", operation_id="getClientChecklist", response_model=Checklist)
async def get_client_checklist(services: ServicesDep) -> Checklist:
    return await services.client.checklist()


@router.post(
    "/api/client/restart",
    operation_id="restartClient",
    response_model=ClientStatus,
    status_code=202,
    responses=_RUN_ACTIVE,
)
async def restart_client(services: ServicesDep) -> ClientStatus:
    return await services.client.restart()
