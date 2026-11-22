"""The backlog estimate (openapi.yaml `getBacklog`): wizard step 9 and the Dashboard.

The service behind it is
`services.backlog` (backlog.py).
"""

from fastapi import APIRouter

from spotivault.api.deps import ServicesDep
from spotivault.api.models import Backlog

router = APIRouter(tags=["runs"])


@router.get("/api/backlog", operation_id="getBacklog", response_model=Backlog)
async def get_backlog(services: ServicesDep) -> Backlog:
    """The last estimate, as is; a catalog refresh may follow (see BacklogService.current)."""
    return await services.backlog.current()
