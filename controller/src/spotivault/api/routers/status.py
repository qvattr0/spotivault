"""What's happening now (openapi.yaml `getStatus`).

Owner: S6. Not built yet: answers 501.
"""

from fastapi import APIRouter

from spotivault.api.models import Status
from spotivault.errors import not_built

router = APIRouter(tags=["runs"])


@router.get("/api/status", operation_id="getStatus", response_model=Status)
async def get_status() -> Status:
    raise not_built("getStatus")
