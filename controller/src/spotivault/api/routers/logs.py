"""History › Logs' endpoints (openapi.yaml tag `history`: listLogs, downloadLogs). Each calls one
`services.logs` method (logview/service.py). The live tail is on WS /api/events (web/events_ws.py).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from spotivault.api.deps import ServicesDep
from spotivault.api.models import LogPage

router = APIRouter()

SourceParam = Literal["controller", "spytify", "client", "system"]
LevelParam = Literal["debug", "info", "warning", "error"]


@router.get("/api/logs", operation_id="listLogs", response_model=LogPage, tags=["history"])
async def list_logs(
    services: ServicesDep,
    source: Annotated[list[SourceParam] | None, Query(max_length=4)] = None,
    level: Annotated[list[LevelParam] | None, Query(max_length=4)] = None,
    run: Annotated[int | None, Query(ge=1)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    before: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> LogPage:
    return await services.logs.page(
        sources=source, levels=level, run=run, q=q, before=before, limit=limit
    )


@router.get(
    "/api/logs/download",
    operation_id="downloadLogs",
    tags=["history"],
    response_class=StreamingResponse,
    responses={200: {"content": {"application/zip": {}}, "description": "The zip."}},
)
async def download_logs(
    services: ServicesDep,
    days: Annotated[int, Query(ge=1, le=14)] = 7,
) -> StreamingResponse:
    handle, name = await services.logs.download(days)
    return StreamingResponse(
        services.logs.stream(handle),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )
