"""Runs and History endpoints (openapi.yaml tags `runs` and `history`).

Owner: S6. Not built yet: every endpoint answers 501. The literal paths (/last, /current) come
before /api/runs/{id}, so "last" is never read as a run id.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from spotivault.api.models import (
    CreateRunRequest,
    CurrentRun,
    GetRunItemTracksResponse,
    LastRun,
    ListRunsResponse,
    RunCreated,
    RunDetail,
    RunSummary,
    StopCurrentRunRequest,
)
from spotivault.api.params import ItemId, RunId
from spotivault.errors import not_built

router = APIRouter()


@router.get("/api/runs", operation_id="listRuns", response_model=ListRunsResponse, tags=["history"])
async def list_runs(
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    filter: Literal["all", "with_issues", "scheduled", "run_now"] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ListRunsResponse:
    raise not_built("listRuns")


@router.post(
    "/api/runs", operation_id="createRun", response_model=RunCreated, status_code=202, tags=["runs"]
)
async def create_run(body: CreateRunRequest | None = None) -> RunCreated:
    raise not_built("createRun")


@router.get("/api/runs/last", operation_id="getLastRun", response_model=LastRun, tags=["runs"])
async def get_last_run() -> LastRun:
    raise not_built("getLastRun")


@router.get(
    "/api/runs/current", operation_id="getCurrentRun", response_model=CurrentRun, tags=["runs"]
)
async def get_current_run() -> CurrentRun:
    raise not_built("getCurrentRun")


@router.post(
    "/api/runs/current/stop",
    operation_id="stopCurrentRun",
    response_model=RunSummary,
    status_code=202,
    tags=["runs"],
)
async def stop_current_run(body: StopCurrentRunRequest) -> RunSummary:
    raise not_built("stopCurrentRun")


@router.post(
    "/api/runs/current/resume",
    operation_id="resumeCurrentRun",
    response_model=RunSummary,
    status_code=202,
    tags=["runs"],
)
async def resume_current_run() -> RunSummary:
    raise not_built("resumeCurrentRun")


@router.delete(
    "/api/runs/current/items/{id}",
    operation_id="removeQueuedItem",
    status_code=204,
    response_class=Response,
    tags=["runs"],
)
async def remove_queued_item(id: ItemId) -> Response:
    raise not_built("removeQueuedItem")


@router.get("/api/runs/{id}", operation_id="getRun", response_model=RunDetail, tags=["history"])
async def get_run(id: RunId) -> RunDetail:
    raise not_built("getRun")


@router.get(
    "/api/runs/{id}/items/{item}/tracks",
    operation_id="getRunItemTracks",
    response_model=GetRunItemTracksResponse,
    tags=["history"],
)
async def get_run_item_tracks(id: RunId, item: ItemId) -> GetRunItemTracksResponse:
    raise not_built("getRunItemTracks")
