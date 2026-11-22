"""History's endpoints (openapi.yaml tag `history`, and the Dashboard's getLastRun).

Owner: history-files-metrics (S6). Each endpoint calls one `services.history` method
(history.py), named in its comment.

**Route order:** app.py includes runs.py's router first (it has `/api/runs/current`), then this
one; here `/api/runs/last` comes before `/api/runs/{id}`, so "last" is never read as a run id.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from spotivault.api.deps import ServicesDep
from spotivault.api.models import GetRunItemTracksResponse, LastRun, ListRunsResponse, RunDetail
from spotivault.api.params import ItemId, RunId

router = APIRouter()


@router.get("/api/runs", operation_id="listRuns", response_model=ListRunsResponse, tags=["history"])
async def list_runs(
    services: ServicesDep,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    filter: Literal["all", "with_issues", "scheduled", "run_now"] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ListRunsResponse:
    return await services.history.list_runs(cursor=cursor, filter=filter, limit=limit)


@router.get("/api/runs/last", operation_id="getLastRun", response_model=LastRun, tags=["runs"])
async def get_last_run(services: ServicesDep) -> LastRun:
    return await services.history.last_run()


@router.get("/api/runs/{id}", operation_id="getRun", response_model=RunDetail, tags=["history"])
async def get_run(id: RunId, services: ServicesDep) -> RunDetail:
    return await services.history.run(id)


@router.get(
    "/api/runs/{id}/items/{item}/tracks",
    operation_id="getRunItemTracks",
    response_model=GetRunItemTracksResponse,
    tags=["history"],
)
async def get_run_item_tracks(
    id: RunId, item: ItemId, services: ServicesDep
) -> GetRunItemTracksResponse:
    return await services.history.run_item_tracks(id, item)
