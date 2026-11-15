"""The fake world: every simulator wired together, in a starting scenario.

    world = FakeWorld(config, clock, scenario="demo")
    ports = world.ports()                   # what services.py runs on
    world.player.take_over("Pixel 9")       # then change things from the outside

| Part | Class | Port |
|---|---|---|
| The account: library, devices | `Catalog` (catalog.py) | — |
| The client's player, Connect | `SimPlayer` (player.py) | — |
| MPRIS on the bus | `SimMpris` (mpris.py) | `ports.Mpris` |
| The client as a program | `FakeClientControl` (client.py) | `ports.ClientControl` |
| spytifyd | `SimRecorder` (recorder.py) | `ports.Recorder` |
| The Web API | `FakeWebApi` (webapi.py) | `ports.WebApi` |
| Spotify's image CDN | `FakeImageCdn` (cdn.py) | `ports.ImageCdn` |
| Volumes | `FakeStorageProbe` (system.py) | `ports.StorageProbe` |
| Screen, sound, VNC | `FakeDesktop` + `FakeScreen` (system.py, vnc.py) | `ports.Desktop` |

**Scenarios:**
- **fresh:** a new container. The client isn't installed (installing it works), nothing is
  logged in, the Web API isn't connected, and the VNC server refuses connections until
  `desktop.vnc = True`. What tests start from.
- **demo:** a container that's set up: the client installed, running and logged in with a tidy
  prefs file, the Web API connected, the library and devices (ours included) there. What
  `python -m spotivault --fake` starts from.
- **wizard:** fresh, but the client logs itself in 20 s after it starts (a click on the fake VNC
  screen does it at once) with Spotify's default prefs, which turn tidy 30 s later: for walking
  the setup wizard by hand.

Every fake port has a `world` attribute, so a test reaches the world from the services:
`world_of(services.ports)`. Owner: the fake agent.
"""

from typing import Literal

from spotivault.config import Config
from spotivault.fake.catalog import Catalog
from spotivault.fake.cdn import FakeImageCdn
from spotivault.fake.client import FakeClientControl
from spotivault.fake.mpris import SimMpris
from spotivault.fake.player import SimPlayer
from spotivault.fake.recorder import SimRecorder
from spotivault.fake.system import FakeDesktop, FakeStorageProbe
from spotivault.fake.vnc import FakeScreen
from spotivault.fake.webapi import FakeWebApi
from spotivault.ports import Clock, Ports

type Scenario = Literal["fresh", "demo", "wizard"]
SCENARIOS: tuple[Scenario, ...] = ("fresh", "demo", "wizard")

# Where the volumes come from, for Settings › Container, as the real probe reads them on the NAS:
# each shared folder's path inside its volume. /volume6/Music on the host shows as /Music, because
# the container can't see where the host mounts /volume6 (openapi.yaml Container.music_source).
MUSIC_SOURCE = "/Music"
CONFIG_SOURCE = "/docker/spotivault/config"


class FakeWorld:
    """Everything fake mode simulates, sharing one clock, catalog and player."""

    def __init__(
        self,
        config: Config,
        clock: Clock,
        *,
        scenario: Scenario = "fresh",
        library: Literal["fixtures", "empty"] = "fixtures",
    ) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown fake scenario {scenario!r}: one of {', '.join(SCENARIOS)}")
        self.config = config
        self.clock = clock
        self.scenario = scenario
        self.catalog = Catalog(device_name=config.device_name, library=library)
        self.player = SimPlayer(clock, self.catalog)
        self.mpris = SimMpris(self.player)
        self.client = FakeClientControl(clock, self.player)
        self.storage = FakeStorageProbe()
        self.recorder = SimRecorder(
            clock,
            self.player,
            music_dir=config.music_dir,
            storage=self.storage,
            mpris_name=config.mpris_name,
        )
        self.webapi = FakeWebApi(clock, self.catalog, self.player)
        self.cdn = FakeImageCdn()
        self.screen = FakeScreen(self.player, self.client)
        self.desktop = FakeDesktop(self.screen)
        self.desktop.vnc = scenario != "fresh"  # tests turn it on when they want a screen
        self.storage.sources[config.music_dir] = MUSIC_SOURCE
        self.storage.sources[config.config_dir] = CONFIG_SOURCE
        for port in (self.mpris, self.client, self.recorder, self.webapi, self.storage, self.cdn):
            port.world = self
        self.desktop.world = self
        if scenario == "demo":
            self.set_up()
        elif scenario == "wizard":
            self.client.auto_login_after_s = 20.0
            self.client.auto_fix_prefs_after_s = 30.0

    def set_up(self) -> None:
        """A container through the wizard: the client installed, running and logged in, and
        the Web API connected."""
        self.client.installed()
        self.client.log_in()
        self.client.start()
        self.webapi.connected = True

    def ports(self) -> Ports:
        return Ports(
            clock=self.clock,
            mpris=self.mpris,
            client=self.client,
            recorder=self.recorder,
            webapi=self.webapi,
            storage=self.storage,
            desktop=self.desktop,
            cdn=self.cdn,
        )


def world_of(ports: Ports) -> FakeWorld:
    """The FakeWorld behind fake ports: `world_of(services.ports).player.take_over()`."""
    world = getattr(ports.client, "world", None)
    if not isinstance(world, FakeWorld):
        raise TypeError("these ports aren't fake ones")
    return world
