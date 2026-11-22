"""Stand-ins for the Spotify client's ports, for the client agent's tests.

`StubClient` and `StubMpris` are set entirely by the test, so these tests don't depend on how the
fake world (spotivault.fake) simulates the client.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from spotivault.events import Event
from spotivault.fake.clock import FakeClock
from spotivault.ports import InstallProgress, LoginSignals
from spotivault.services import Services

WAIT_S = 2.0  # real seconds: how long a test waits for the controller's own work

LOGGED_IN = LoginSignals(user_folder=True, window_title="Spotify Premium")
GOOD_PREFS = {
    "audio.allow_downgrade": "false",
    "audio.automix": "false",
    "audio.normalize_v2": "false",
    "audio.play_bitrate_enumeration": "4",
}


def progress(stage: str, message: str, **fields: Any) -> InstallProgress:
    return InstallProgress(stage=stage, message=message, **fields)


HAPPY = [
    progress("release", "Checking Spotify's repository"),
    progress("download", "Downloading Spotify 1.3.4.258", percent=0, bytes=0, total=100),
    progress("download", "Downloading Spotify 1.3.4.258", percent=50, bytes=50, total=100),
    progress("download", "Downloaded Spotify 1.3.4.258", percent=100, bytes=100, total=100),
    progress("verify", "Checking the download"),
    progress("unpack", "Unpacking"),
    progress("libraries", "Checking the client's libraries"),
    progress("switch", "Switching to Spotify 1.3.4.258"),
    progress("done", "Installed Spotify 1.3.4.258", version="1.3.4.258", previous="", changed=True),
]


class StubClient:
    """`ports.ClientControl` with everything set by the test.

    An install yields the lines the test sends with `send()`, and ends after a `done` or `error`
    line (or a None). With `output_after_result`, it ends only at a None, as spotify-install does
    when it writes more, or takes a moment to exit, after its last line. A `done` line installs
    its version. `send()` returns once the manager has
    handled each line, database writes included, so the test can move the fake clock in between.
    """

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.version: str | None = None
        self.running = False
        self.signals = LoginSignals(user_folder=False, window_title=None)
        self.prefs_values: dict[str, str] | None = None
        self.raise_at_start: Exception | None = None
        self.output_after_result = False
        self.fail_running: Exception | None = None
        self.installs = 0
        self.closed_early = False
        self.restarts = 0
        self._feed: asyncio.Queue[InstallProgress | None] = asyncio.Queue()

    async def send(self, *lines: InstallProgress | None) -> None:
        for line in lines:
            self._feed.put_nowait(line)
            await asyncio.wait_for(self._feed.join(), WAIT_S)

    async def install(
        self, *, version: str | None = None, force: bool = False
    ) -> AsyncIterator[InstallProgress]:
        self.installs += 1
        if self.raise_at_start is not None:
            raise self.raise_at_start
        finished = False
        try:
            while True:
                line = await self._feed.get()
                try:
                    if line is None:
                        finished = True
                        return
                    if line.stage == "done":
                        self.version = line.version
                    yield line
                finally:
                    self._feed.task_done()  # the manager asked for the next line
                if line.stage in ("done", "error") and not self.output_after_result:
                    finished = True
                    return
        finally:
            self.closed_early = not finished

    async def installed_version(self) -> str | None:
        return self.version

    async def is_running(self) -> bool:
        if self.fail_running is not None:
            raise self.fail_running
        return self.running

    async def restart(self) -> None:
        self.restarts += 1

    async def login_signals(self) -> LoginSignals:
        return self.signals

    async def prefs(self) -> dict[str, str] | None:
        return self.prefs_values


class StubMpris:
    def __init__(self) -> None:
        self.present = False

    async def owner_present(self) -> bool:
        return self.present


def use_stubs(services: Services, clock: FakeClock) -> tuple[StubClient, StubMpris]:
    client, mpris = StubClient(clock), StubMpris()
    services.ports.client = client  # type: ignore[assignment]
    services.ports.mpris = mpris  # type: ignore[assignment]
    return client, mpris


def record_events(services: Services) -> list[Event]:
    """The `client.*` events the bus publishes from now on, in order. (Other modules may publish
    their own in reaction, such as `setup.state`; they're left out.)"""
    seen: list[Event] = []
    publish = services.bus.publish

    def recording(type: str, data: Any) -> Event:
        event = publish(type, data)
        if type.startswith("client."):
            seen.append(event)
        return event

    services.bus.publish = recording  # type: ignore[method-assign]
    return seen


@asynccontextmanager
async def started(services: Services, clock: FakeClock) -> AsyncIterator[None]:
    """The controller's lifespan, with the background tasks under way."""
    async with services.running():
        await clock.settle()
        yield
    assert services.fatal_errors == []


async def eventually(condition: Callable[[], bool]) -> None:
    """Waits (in real time) until `condition()` is true. The controller's database writes run on
    their own thread, so a fake clock's `settle()` can't wait for them."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_S
    while not condition():
        if loop.time() > deadline:
            raise AssertionError("timed out waiting for the controller")
        await asyncio.sleep(0.01)


async def run_install(services: Services, client: StubClient, lines: list[InstallProgress]) -> None:
    """Feeds `lines` to the running install, then waits until the manager has recorded its end."""
    await client.send(*lines)
    await eventually(lambda: not services.client.installing)
