"""The backlog estimate (openapi.yaml `getBacklog`): wizard step 9 and the Dashboard.

Owner: S5. Not built yet: answers 501.
"""

from fastapi import APIRouter

from spotivault.api.models import Backlog
from spotivault.errors import not_built

router = APIRouter(tags=["runs"])


@router.get("/api/backlog", operation_id="getBacklog", response_model=Backlog)
async def get_backlog() -> Backlog:
    raise not_built("getBacklog")
