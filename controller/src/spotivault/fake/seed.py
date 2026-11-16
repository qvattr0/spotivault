"""Fake mode's ties to the controller's own state. services.py calls `attach(services)`.

- **The fake Web API follows the stored token.** The fake port gets the controller's AuthStore,
  so a call is connected exactly when the controller holds a token (fake/webapi.py).
- **The demo scenario starts connected.** At start-up, if no Client ID is stored yet, it stores a
  made-up one and a grant for the catalog's user, as wizard step 5 would have. Its "tokens" are
  plain placeholders: the fake port never checks them.

Both run again at start-up on whatever fake ports the services hold then, so a test that swaps
`services.ports` before the lifespan starts gets them too.

"""

from typing import TYPE_CHECKING

from spotivault.fake import demo
from spotivault.fake.webapi import SCOPES
from spotivault.fake.world import FakeWorld, world_of
from spotivault.ports import TokenGrant

if TYPE_CHECKING:
    from spotivault.services import Services

DEMO_CLIENT_ID = "0123456789abcdef0123456789abcdef"


def attach(services: "Services") -> None:
    """Ties the fake world to `services` now, and again at start-up (see the module docstring)."""
    world = _world(services)
    if world is not None:
        world.webapi.auth = services.auth

    async def start() -> None:
        world = _world(services)
        if world is None:
            return
        world.webapi.auth = services.auth
        if world.scenario == "demo":
            await seed_demo_connection(services, world)
            demo.prepare(services, world)  # setup completed for Run now (fake/demo.py)

    services.add_startup("fake.attach", start)


async def seed_demo_connection(services: "Services", world: FakeWorld) -> None:
    """Stores a connection for the demo, unless one is stored already (a restarted dev server
    keeps whatever was connected or disconnected through the UI)."""
    row = await services.auth.load()
    if row.client_id is not None:
        return
    await services.auth.set_client_id(DEMO_CLIENT_ID)
    grant = TokenGrant(
        access_token="fake-demo-access-token",
        refresh_token="fake-demo-refresh-token",
        expires_in_s=3600,
        scopes=SCOPES,
    )
    await services.auth.save_grant(DEMO_CLIENT_ID, grant)
    await services.auth.set_account(world.catalog.user)


def _world(services: "Services") -> FakeWorld | None:
    try:
        return world_of(services.ports)
    except TypeError:  # not fake ports
        return None
