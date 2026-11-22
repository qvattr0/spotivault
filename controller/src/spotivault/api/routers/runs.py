"""The run endpoints that change or show the current run (openapi.yaml tag `runs`).

Owner: engine-run (S6). Each one calls one `services.runs` method (engine/run.py), which raises
the ApiErrors (409 no_run, run_active, not_paused, item_is_current and the quick checks; 404
not_found). History's endpoints (listRuns, getLastRun, getRun, getRunItemTracks) are in
history.py.

**Route order:** app.py includes this router before history.py's, so `/api/runs/current` is
matched here before history's `/api/runs/{id}` could take it. POST /api/runs is here and GET
/api/runs in history.py: Starlette matches the method across both.
"""

from fastapi import APIRouter, Response

from spotivault.api.deps import ServicesDep
from spotivault.api.models import (
    CreateRunRequest,
    CurrentRun,
    RunCreated,
    RunSummary,
    StopCurrentRunRequest,
)
from spotivault.api.params import ItemId

router = APIRouter(tags=["runs"])


@router.post("/api/runs", operation_id="createRun", response_model=RunCreated, status_code=202)
async def create_run(services: ServicesDep, body: CreateRunRequest | None = None) -> RunCreated:
    """Run now without `items`; with them, a run of just those, or they join the current run."""
    items = body.items if body is not None else None
    return await services.runs.create_run(items or None)


@router.get("/api/runs/current", operation_id="getCurrentRun", response_model=CurrentRun)
async def get_current_run(services: ServicesDep) -> CurrentRun:
    return await services.runs.current()


@router.post(
    "/api/runs/current/stop",
    operation_id="stopCurrentRun",
    response_model=RunSummary,
    status_code=202,
)
async def stop_current_run(services: ServicesDep, body: StopCurrentRunRequest) -> RunSummary:
    return await services.runs.stop(body.mode)


@router.post(
    "/api/runs/current/resume",
    operation_id="resumeCurrentRun",
    response_model=RunSummary,
    status_code=202,
)
async def resume_current_run(services: ServicesDep) -> RunSummary:
    return await services.runs.resume()


@router.delete(
    "/api/runs/current/items/{id}",
    operation_id="removeQueuedItem",
    status_code=204,
    response_class=Response,
)
async def remove_queued_item(services: ServicesDep, id: ItemId) -> Response:
    await services.runs.remove_queued(id)
    return Response(status_code=204)
