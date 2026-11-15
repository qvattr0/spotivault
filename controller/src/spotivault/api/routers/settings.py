"""Settings endpoints (openapi.yaml tag `settings`): Settings › Recording, Files and Library,
and wizard steps 6 and 7. The rules are in spotivault/settings.py."""

from fastapi import APIRouter

from spotivault.api.deps import ServicesDep
from spotivault.api.models import Settings, SettingsUpdate

router = APIRouter(tags=["settings"])


@router.get("/api/settings", operation_id="getSettings", response_model=Settings)
async def get_settings(services: ServicesDep) -> Settings:
    return await services.settings.get()


@router.put(
    "/api/settings",
    operation_id="putSettings",
    response_model=Settings,
    responses={422: {"description": "`invalid_layout` or `validation_failed`."}},
)
async def put_settings(body: SettingsUpdate, services: ServicesDep) -> Settings:
    """Fields left out keep their value. A change saved during a run applies from the next item."""
    return await services.settings.update(body)
