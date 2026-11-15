"""Read-only container facts (openapi.yaml tag `settings`): Settings › Container.
The facts come from spotivault/container.py."""

from fastapi import APIRouter

from spotivault.api.deps import ServicesDep
from spotivault.api.models import Container

router = APIRouter(tags=["settings"])


@router.get("/api/container", operation_id="getContainer", response_model=Container)
async def get_container(services: ServicesDep) -> Container:
    return await services.container.info()
