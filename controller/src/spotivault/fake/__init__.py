"""Fake mode: a simulated player, recorder, client, Web API, volumes and desktop.

`python -m spotivault --fake` and the tests run the controller against these instead of the real
outside world, so the UI and the engine can be exercised with no Spotify account, no client and no
container. world.py says what each part is; the simulators follow prototype/FINDINGS.md.

`build_fake_ports` is what services.py calls in fake mode. Owner: the fake agent
(controller/ARCHITECTURE.md § Ownership).
"""

from spotivault.config import Config
from spotivault.fake.clock import FakeClock
from spotivault.fake.world import SCENARIOS, FakeWorld, Scenario, world_of
from spotivault.ports import Clock, Ports

__all__ = ["SCENARIOS", "FakeWorld", "Scenario", "build_fake_ports", "world_of"]


def build_fake_ports(config: Config, clock: Clock, *, scenario: Scenario | None = None) -> Ports:
    """One fake world's ports. `scenario` is "fresh", "demo" or "wizard" (world.py). By default
    it's "fresh" on a FakeClock, where a test moves time and starts from a new container, and
    "demo" on any other clock: `python -m spotivault --fake` starts set up, with a library."""
    if scenario is None:
        scenario = "fresh" if isinstance(clock, FakeClock) else "demo"
    return FakeWorld(config, clock, scenario=scenario).ports()
