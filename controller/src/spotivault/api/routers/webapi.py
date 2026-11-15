"""Web API usage totals and 429 history (openapi.yaml `getWebApiUsage`), for the S10 analysis.

The service behind it is
`services.webapi_usage` (webapi/usage.py). No page shows it yet.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from spotivault.api.deps import ServicesDep
from spotivault.api.models import WebApiUsage

router = APIRouter(tags=["system"])


@router.get("/api/webapi/usage", operation_id="getWebApiUsage", response_model=WebApiUsage)
async def get_webapi_usage(
    services: ServicesDep, days: Annotated[int, Query(ge=1, le=90)] = 7
) -> WebApiUsage:
    """The last `days` UTC days, today included: per endpoint template per day, every 429 and
    the warnings. Templates only, never ids or tokens."""
    return await services.webapi_usage.usage(days)
