"""What's happening now (openapi.yaml `getStatus`).

Owner: engine-run (S6). The run engine (engine/run.py, `services.runs`) answers it; the WS hello's
`status` is the same value.
"""

from fastapi import APIRouter

from spotivault.api.deps import ServicesDep
from spotivault.api.models import Status

router = APIRouter(tags=["runs"])


@router.get("/api/status", operation_id="getStatus", response_model=Status)
async def get_status(services: ServicesDep) -> Status:
    return await services.runs.status()
