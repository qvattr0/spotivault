"""Web API usage totals and 429 history (openapi.yaml `getWebApiUsage`), for the S10 analysis.

Owner: S5. Not built yet: answers 501.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from spotivault.api.models import WebApiUsage
from spotivault.errors import not_built

router = APIRouter(tags=["system"])


@router.get("/api/webapi/usage", operation_id="getWebApiUsage", response_model=WebApiUsage)
async def get_webapi_usage(days: Annotated[int, Query(ge=1, le=90)] = 7) -> WebApiUsage:
    raise not_built("getWebApiUsage")
