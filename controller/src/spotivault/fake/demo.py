"""Fake mode's demo, ready for Run now (`python -m spotivault --fake`, the `demo` scenario).

Owner: engine-run (S6). fake/seed.py's start-up hook calls `prepare(services, world)`.

The demo's world is set up (the client installed and logged in with tidy prefs, the Web API
connected), but the controller's own wizard isn't done, so a run would be refused with
`setup_incomplete`. On a fresh `.dev` folder (the Terms notice not acknowledged yet), this walks
the wizard through its own actions, as a user would: step 1's acknowledgement, step 4's Confirm
rows ticked, step 5 marked done (the demo's connection is stored by seed.py), and `complete()`.
Then a catalog refresh is asked for, so the Library shows the account's playlists. A restarted
dev server keeps whatever the UI did since, "Run setup again" included.

It runs as a background task, once every start-up hook is done: the checklist rows it ticks are
created by the client module's start-up hook, which runs after seed.py's. A failure is logged,
never raised: the demo still serves, and the wizard can be walked by hand.

Run now then records every tracked playlist (your own ones come tracked) on the simulated world
in real time; `SPOTIVAULT_FAKE_SPEED` makes the world run faster to watch a whole run.
"""

import logging
from typing import TYPE_CHECKING

from spotivault.fake.world import FakeWorld

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

CONFIRM_ROWS = {"crossfade": True, "gapless": True, "autoplay": True}


def prepare(services: "Services", world: FakeWorld) -> None:
    """Called from seed.py's start-up hook for the demo scenario: completes the setup once the
    other start-up hooks have run (module docstring)."""
    if world.scenario != "demo":
        return

    async def complete_setup() -> None:
        try:
            await complete_demo_setup(services)
        except Exception:
            log.exception("fake demo: the setup couldn't be completed; walk the wizard by hand")

    services.add_background("fake.demo", complete_setup)


async def complete_demo_setup(services: "Services") -> bool:
    """Walks the wizard on a fresh demo. True if it did; False when there was nothing to do."""
    setup = await services.setup.snapshot()
    if setup.completed or setup.tos_acknowledged_at is not None:
        return False
    await services.setup.acknowledge_tos()
    await services.client.confirm(CONFIRM_ROWS)
    await services.setup.mark_done("webapi")
    await services.setup.complete()
    services.catalog.request_refresh("setup")
    log.info("fake demo: setup completed; Run now records the demo library")
    return True
