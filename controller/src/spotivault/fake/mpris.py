"""`ports.Mpris` over the simulated player: what the controller sees on the session bus.

Reading a property while the client isn't on the bus returns None, and a player method raises
MprisNoClient, as JeepneyMpris does. A logged-out client is on the bus with nothing loaded:
`Stopped`, no metadata, and the player methods do nothing (Q2: MPRIS is no login signal).

Owner: the fake agent.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from spotivault.fake.clock import schedule
from spotivault.fake.player import PlayerEvent, SimPlayer
from spotivault.ports import MprisChange, MprisNoClient, PlaybackStatus, TrackMetadata


class SimMpris:
    """`ports.Mpris` for fake mode.

    `metadata_lag_s` (a knob, 0 by default): the client's PropertiesChanged for a new track comes
    this long after the change, so for that long `metadata()` still names the track before and
    subscribers get the change late. probe.py's `loaded_positions` waits for MPRIS's title to
    agree with Spytify's track.started for this reason (FINDINGS § Playing only the missing
    tracks); the engine must too.
    """

    def __init__(self, player: SimPlayer) -> None:
        self.player = player
        self.calls: list[str] = []  # player methods called, for tests: ["Pause", "Play", ...]
        self.world: object | None = None  # the FakeWorld it belongs to
        self.metadata_lag_s = 0.0
        self._subscribers: set[asyncio.Queue[MprisChange]] = set()
        self._shown: TrackMetadata | None = None  # the metadata MPRIS shows while it lags
        self._lag_until = 0.0  # monotonic time the lag ends
        self._previous: TrackMetadata | None = player.metadata()  # the last track MPRIS was told
        player.listeners.append(self._on_player)

    # --- Older names, kept for tests written against the S4 foundation's FakePlayer ------------

    @property
    def on_bus(self) -> bool:
        return self.player.on_bus

    def set_on_bus(self, present: bool) -> None:
        """Puts the client's name on the bus, or takes it off (a crash, say)."""
        if present:
            self.player.client_started()
        else:
            self.player.client_gone()

    # --- ports.Mpris ---------------------------------------------------------------------------

    async def owner_present(self) -> bool:
        return self.player.on_bus

    async def playback_status(self) -> PlaybackStatus | None:
        return self.player.status if self.player.on_bus else None

    async def metadata(self) -> TrackMetadata | None:
        if not self.player.on_bus:
            return None
        if self.player.clock.monotonic() < self._lag_until:
            return self._shown
        return self.player.metadata()

    async def position_ms(self) -> int | None:
        return self.player.position_ms() if self.player.on_bus else None

    async def play(self) -> None:
        self._call("Play")
        self.player.mpris_play()

    async def pause(self) -> None:
        self._call("Pause")
        self.player.mpris_pause()

    async def play_pause(self) -> None:
        self._call("PlayPause")
        if self.player.status == "Playing":
            self.player.mpris_pause()
        else:
            self.player.mpris_play()

    async def next(self) -> None:
        self._call("Next")
        self.player.mpris_next()

    async def previous(self) -> None:
        self._call("Previous")
        self.player.mpris_previous()

    async def open_uri(self, uri: str) -> None:
        self._call(f"OpenUri {uri}")
        self.player.mpris_open_uri(uri)

    async def quit(self) -> None:
        """The client quits cleanly. FakeClientControl brings it back, as s6 does."""
        self._call("Quit")
        self.player.client_gone()

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[AsyncIterator[MprisChange]]:
        queue: asyncio.Queue[MprisChange] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            yield _drain(queue)
        finally:
            self._subscribers.discard(queue)

    # --- Inside --------------------------------------------------------------------------------

    def _call(self, method: str) -> None:
        if not self.player.on_bus:
            raise MprisNoClient(f"{method}: the client isn't on the bus")
        self.calls.append(method)

    def _on_player(self, event: PlayerEvent) -> None:
        change = _change_for(event)
        if change is None:
            return
        if event.kind == "track" and self.metadata_lag_s > 0:
            clock = self.player.clock
            if clock.monotonic() >= self._lag_until:
                self._shown = self._previous
            self._lag_until = clock.monotonic() + self.metadata_lag_s
            self._previous = event.metadata
            schedule(clock, self.metadata_lag_s, lambda: self._deliver(change))
            return
        if event.kind == "track":
            self._previous = event.metadata
        self._deliver(change)

    def _deliver(self, change: MprisChange) -> None:
        for queue in self._subscribers:
            queue.put_nowait(change)


def _change_for(event: PlayerEvent) -> MprisChange | None:
    """The bus signal a player event gives: PropertiesChanged, Seeked or NameOwnerChanged."""
    if event.kind == "track":
        return MprisChange(at=event.at, metadata=event.metadata)
    if event.kind == "status":
        return MprisChange(at=event.at, playback_status=event.status)
    if event.kind == "seeked":
        return MprisChange(at=event.at, seeked_ms=event.position_ms)
    if event.kind == "bus":
        return MprisChange(at=event.at, owner_present=event.on_bus)
    return None


async def _drain(queue: asyncio.Queue[MprisChange]) -> AsyncIterator[MprisChange]:
    while True:
        yield await queue.get()
