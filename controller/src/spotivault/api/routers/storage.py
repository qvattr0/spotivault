"""The music folder check (openapi.yaml tag `settings`): wizard step 6, Settings › Files.
The check is in spotivault/storage.py."""

from fastapi import APIRouter

from spotivault.api.deps import ServicesDep
from spotivault.api.models import Storage

router = APIRouter(tags=["settings"])


@router.get("/api/storage", operation_id="getStorage", response_model=Storage)
async def get_storage(services: ServicesDep) -> Storage:
    """Writes and removes a probe file in /music and /config. Step 6 follows the answer."""
    storage = await services.storage.check()
    await services.setup.refresh(storage=storage)
    return storage
