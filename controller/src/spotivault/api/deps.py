"""FastAPI dependencies shared by the routers.

    @router.get("/api/storage", ...)
    async def get_storage(services: ServicesDep) -> Storage:
        return await services.storage.check()

WebSocket handlers get it the same way (HTTPConnection covers both).
"""

from typing import Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from spotivault.services import Services


def get_services(connection: HTTPConnection) -> Services:
    """The app's Services object, which create_app put in `app.state.services`."""
    return connection.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]
