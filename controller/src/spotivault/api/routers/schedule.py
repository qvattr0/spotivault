"""Schedule endpoints (openapi.yaml tag `schedule`): the weekly grid, set with curl in M1 (D5).

Owner: schedule (S6). Each endpoint calls one `services.schedule` method (schedule.py).
"""

from fastapi import APIRouter

from spotivault.api.deps import ServicesDep
from spotivault.api.models import Schedule, ScheduleNext, ScheduleUpdate

router = APIRouter(tags=["schedule"])


@router.get("/api/schedule", operation_id="getSchedule", response_model=Schedule)
async def get_schedule(services: ServicesDep) -> Schedule:
    """The grid, the zone, the run order and the week's window and hour counts."""
    return await services.schedule.get()


@router.put("/api/schedule", operation_id="putSchedule", response_model=Schedule)
async def put_schedule(body: ScheduleUpdate, services: ServicesDep) -> Schedule:
    """Saves the grid (and run_order when given). Turning off the current hour during a
    scheduled run stops it after the current track."""
    return await services.schedule.put(body)


@router.get("/api/schedule/next", operation_id="getScheduleNext", response_model=ScheduleNext)
async def get_schedule_next(services: ServicesDep) -> ScheduleNext:
    """The next window, what it will cover, and why it's held, if it is."""
    return await services.schedule.next()
