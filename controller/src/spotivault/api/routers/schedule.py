"""Schedule endpoints (openapi.yaml tag `schedule`): the weekly grid, set with curl in M1 (D5).

Owner: S6. Not built yet: every endpoint answers 501.
"""

from fastapi import APIRouter

from spotivault.api.models import Schedule, ScheduleNext, ScheduleUpdate
from spotivault.errors import not_built

router = APIRouter(tags=["schedule"])


@router.get("/api/schedule", operation_id="getSchedule", response_model=Schedule)
async def get_schedule() -> Schedule:
    raise not_built("getSchedule")


@router.put("/api/schedule", operation_id="putSchedule", response_model=Schedule)
async def put_schedule(body: ScheduleUpdate) -> Schedule:
    raise not_built("putSchedule")


@router.get("/api/schedule/next", operation_id="getScheduleNext", response_model=ScheduleNext)
async def get_schedule_next() -> ScheduleNext:
    raise not_built("getScheduleNext")
