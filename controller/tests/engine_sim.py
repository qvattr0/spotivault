"""The engine simulator: a set-up controller on the fake world, scripted on the fake clock, for
S6's engine tests (plan § Verification, "Engine simulator tests").

    async def test_missing_two_and_four(sim: Sim) -> None:       # the `sim` fixture (conftest.py)
        album = sim.elsewhere()                                  # FINDINGS' 5-track album
        await sim.refresh()
        await sim.add_album(album)
        sim.prerecord(album, [0, 2, 4])                          # tracks 1, 3, 5 are recorded
        job = await sim.job(album.album.id)
        report = await sim.run_item(job)                         # ItemEngine on the clock
        assert report.outcome == "done" and sim.recorded_titles(album) == {...}

What the simulator encodes (fake/player.py, fake/recorder.py, fake/mpris.py follow
prototype/FINDINGS.md and docs/upstream/spytify-bugs.md):
- a track the player is paused on more than 300 ms in counts as already playing (bug 2): use
  `sim.leave_player_on(album, index, position_ms)` before the item;
- at the end of an album, track 1 loads paused; the phantom `track.started` + `track.skipped` for
  it at the idle exit; the idle exit 20 s after the pause, the last `track.finished` 5 s later,
  the exit 3 s after that (28 s, FINDINGS' excerpt);
- SIGTERM (finish the take), a second SIGTERM (stop now, the take held, its WAV left: bug 4),
  SIGKILL (a `.part` left: bug 5);
- stalls (`stall_at`: our player pauses with no other device, `for_s` later it plays on),
  takeovers (`take_over_at`: a phone takes playback), autoplay moving the context
  (`autoplay()`), silent or stalled capture (`capture_at`), MPRIS metadata arriving late
  (`world.mpris.metadata_lag_s`), skip-forward's Next racing the exit (bug 1), relinked ids in
  GET /me/player (Playlist 7 in the fixtures library), GET /me/player still reporting the state
  from before a play (`world.player.state_lag_s`), Web API failures (`world.webapi.failures`).

Everything runs on the FakeClock: `advance_until` jumps from one timer to the next, so an item
of several minutes takes milliseconds. Owner: the S6 foundation (frozen while the builders work).
"""

import asyncio
import json
from collections.abc import Callable, Iterable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spotivault.clock import iso_ms
from spotivault.engine.states import ItemState
from spotivault.engine.types import (
    ItemControl,
    ItemJob,
    ItemReport,
    PlayMode,
    Timeouts,
    TrackCounts,
)
from spotivault.events import Event
from spotivault.fake.catalog import CatalogAlbum, CatalogPlaylist, Entry
from spotivault.fake.clock import FakeClock, Timer, schedule
from spotivault.fake.recorder import Capture
from spotivault.fake.world import FakeWorld, world_of
from spotivault.matching import read_recorded_index, track_key
from spotivault.ports import TokenGrant
from spotivault.services import Services

CLIENT_ID = "0123456789abcdef0123456789abcdef"
GRANT = TokenGrant(access_token="t" * 10, refresh_token="r" * 10, expires_in_s=3600, scopes=())

# FINDINGS' "Elsewhere" (5 × ~90 s), the album most of the prototype's runs used.
ELSEWHERE: list[tuple[str, int]] = [
    ("Passage", 87_000),
    ("Distant Peak", 90_000),
    ("Now And Then", 102_000),
    ("Seaside Stillness", 93_000),
    ("Last Hours", 88_000),
]
ELSEWHERE_ARTIST = "fakename"


@dataclass(slots=True)
class RecordingHost:
    """An `ItemHost` (engine/types.py) that records what the item engine tells it, for
    engine-item tests that run an item without the run engine."""

    phases: list[tuple[ItemState, PlayMode | None, int | None]] = field(default_factory=list)
    counts: list[TrackCounts] = field(default_factory=list)

    async def item_phase(
        self,
        job: ItemJob,
        phase: ItemState,
        *,
        mode: PlayMode | None = None,
        planned: int | None = None,
    ) -> None:
        self.phases.append((phase, mode, planned))

    async def item_counts(self, job: ItemJob, counts: TrackCounts) -> None:
        self.counts.append(counts)

    def phase_names(self) -> list[ItemState]:
        return [phase for phase, _, _ in self.phases]


class Sim:
    """A controller set up as after the wizard, on the fake world (see the module docstring).

    Build it with the `sim` fixture, or `async with Sim.started(services) as sim` inside a test
    that has `running_app` (the store must be open)."""

    def __init__(self, services: Services) -> None:
        self.services = services
        self.world: FakeWorld = world_of(services.ports)
        clock = services.clock
        if not isinstance(clock, FakeClock):
            raise TypeError("the simulator needs the FakeClock")
        self.clock: FakeClock = clock
        self.events: list[Event] = []  # every bus event published since start, in order
        self._stack = AsyncExitStack()
        self._reader: asyncio.Task[None] | None = None
        self._next_item = 0

    # --- Setting up ----------------------------------------------------------------------------

    @classmethod
    def started(cls, services: Services) -> "_Started":
        return _Started(cls(services))

    async def start(self) -> None:
        """The client installed, running and logged in with tidy prefs; the Web API connected
        with the catalog's user; setup complete; an empty library; the meter off."""
        world = self.world
        world.catalog.clear()
        world.recorder.level_interval_s = None
        world.set_up()
        services = self.services
        await services.auth.set_client_id(CLIENT_ID)
        await services.auth.save_grant(CLIENT_ID, GRANT)
        await services.auth.set_account(world.catalog.user)
        now = iso_ms(self.clock.now())
        await services.store.execute(
            "INSERT INTO meta (key, value, updated_at) VALUES ('setup_completed_at', ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (now, now),
        )
        await services.client.refresh()
        subscription = await self._stack.enter_async_context(services.bus.subscribe())
        self._reader = asyncio.ensure_future(self._read(subscription))

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
        await self._stack.aclose()

    async def _read(self, subscription: Any) -> None:
        while True:
            self.events.append(await subscription.next())

    # --- The library ---------------------------------------------------------------------------

    def elsewhere(self) -> CatalogAlbum:
        """FINDINGS' 5-track album "Elsewhere" by "fakename", saved in the account."""
        return self.world.catalog.add_album("Elsewhere", artist=ELSEWHERE_ARTIST, tracks=ELSEWHERE)

    def album(
        self, name: str, tracks: list[tuple[str, int]] | int, *, artist: str = "Test Artist"
    ) -> CatalogAlbum:
        """An album saved in the account (add it to Albums with `add_album`)."""
        return self.world.catalog.add_album(name, artist=artist, tracks=tracks)

    def playlist(
        self,
        name: str,
        entries: list[Entry] | None = None,
        *,
        tracks: int = 0,
        access: str = "owned",
    ) -> CatalogPlaylist:
        """A playlist in the account: owned (missing tracks only) or followed (whole, 403 on
        its items). `sim.world.catalog.entry(title, artist=, duration_ms=)` makes entries."""
        return self.world.catalog.add_playlist(
            name,
            entries=entries,
            tracks=tracks,
            access=access,  # type: ignore[arg-type]
        )

    async def refresh(self) -> None:
        """A catalog refresh, as wizard step 5 leaves one: items and track lists stored."""
        result = await self.services.catalog.refresh(trigger="setup")
        if result.outcome == "failed":
            raise AssertionError(f"the catalog refresh failed: {result.error}")

    async def add_album(self, album: CatalogAlbum) -> None:
        """Adds a saved album to the Albums page (queued for the next run)."""
        added = await self.services.albums.add(ids=[album.album.id])
        if [item.id for item in added.added] != [album.album.id]:
            raise AssertionError(f"album not added: {added}")

    async def add_playlist(self, playlist: CatalogPlaylist) -> None:
        """Adds a followed or linked playlist to the Library by its link (the + modal); it
        comes in tracked. Your own playlists come with the refresh: `track()` them."""
        await self.services.library.add(f"https://open.spotify.com/playlist/{playlist.playlist.id}")

    async def track(self, item_id: str, tracked: bool = True) -> None:
        """Turns tracking on (or off) for a playlist in the Library, or Liked Songs."""
        await self.services.library.set_tracked(item_id, tracked)

    # --- What's recorded -----------------------------------------------------------------------

    def prerecord(self, album: CatalogAlbum | CatalogPlaylist, positions: Iterable[int]) -> None:
        """Puts these entries (0-based) in the music folder and Spytify's index, as an earlier
        run would have. Small writes in place, outside the event loop's slow-callback limit."""
        music = self.services.config.music_dir
        index = music / ".spytify" / "recorded.jsonl"
        index.parent.mkdir(parents=True, exist_ok=True)
        with index.open("a", encoding="utf-8") as fh:
            for position in positions:
                track = album.entries[position].track
                assert track is not None, f"entry {position} has no track"
                artist = track.artists[0] if track.artists else ""
                folder = music / artist / (track.album_name or "Singles")
                path = folder / f"{position + 1:02d} - {track.name}.m4a"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"recorded")
                key = track_key(artist, track.name)
                fh.write(json.dumps({"Key": key, "Path": str(path)}, ensure_ascii=False) + "\n")
        self.services.matching.invalidate()

    def recorded_keys(self) -> set[str]:
        """The keys in Spytify's index whose file exists."""
        return set(read_recorded_index(self.services.config.spytify_index))

    def recorded_titles(self, album: CatalogAlbum | CatalogPlaylist) -> set[str]:
        """The titles of this item's entries that are recorded now."""
        keys = self.recorded_keys()
        titles = set()
        for entry in album.entries:
            track = entry.track
            if track is not None and track_key(track.artists[0], track.name) in keys:
                titles.add(track.name)
        return titles

    def leave_player_on(
        self, album: CatalogAlbum | CatalogPlaylist, index: int, position_ms: int
    ) -> None:
        """Leaves our player paused on that entry, that far in, as an earlier run would have
        (bug 2's case: the engine must seek to 0 before the recorder starts)."""
        uri = album.album.uri if isinstance(album, CatalogAlbum) else album.playlist.uri
        self.world.player.load(uri, index=index, position_ms=position_ms)

    # --- Scripting the world on the clock ------------------------------------------------------

    def at(self, seconds: float, action: Callable[[], None]) -> Timer:
        """Runs `action` `seconds` from now, on the fake clock."""
        return schedule(self.clock, seconds, action)

    def take_over_at(self, seconds: float, device: str = "Pixel 9") -> Timer:
        """Another device takes playback over: our player pauses, that device plays on."""
        return self.at(seconds, lambda: self.world.player.take_over(device))

    def stall_at(self, seconds: float, *, for_s: float | None = None) -> Timer:
        """Our player pauses by itself (a network stall); with `for_s`, it plays on after that
        long (under 20 s: the take is saved with pause_fade; over: the idle exit ended it)."""

        def stall() -> None:
            self.world.player.pause_by_itself()
            if for_s is not None:
                self.at(for_s, self.world.player.resume_by_itself)

        return self.at(seconds, stall)

    def capture_at(self, seconds: float, capture: Capture) -> Timer:
        """The capture turns silent, stalls, or is fine again (Spytify reports 10 s later)."""
        return self.at(seconds, lambda: self.world.recorder.set_capture(capture))

    def autoplay(self, on: bool = True) -> None:
        """Spotify's autoplay: at the end of a context, a radio context plays on."""
        self.world.player.autoplay = on

    async def advance_until(self, condition: Callable[[], bool], *, within: float) -> float:
        """Moves the clock until `condition()` holds; the seconds that passed."""
        return await self.clock.advance_until(condition, within=within)

    # --- Running an item -----------------------------------------------------------------------

    async def job(
        self,
        item_id: str,
        *,
        attempt: int = 1,
        snapshot_unread: bool = False,
        run_id: int | None = None,
        timeouts: Timeouts | None = None,
    ) -> ItemJob:
        """An ItemJob for one item, with a `runs` row (kind run, running, run_now) and its
        `run_items` row (state up_next, as the run engine would leave it)."""
        services = self.services
        row = await services.store.fetchone(
            "SELECT id, kind, uri, name FROM items WHERE id = ?", (item_id,)
        )
        if row is None:
            raise AssertionError(f"no item {item_id}: refresh, add_album or track it first")
        now = iso_ms(self.clock.now())
        if run_id is None:
            run_id = await services.store.fetchval(
                "SELECT id FROM runs WHERE kind = 'run' AND state <> 'ended'"
            )
        if run_id is None:
            result = await services.store.execute(
                "INSERT INTO runs (kind, trigger, state, started_at, recorded, skipped_duplicate, "
                "skipped_other, failed, bytes_added) VALUES ('run', 'run_now', 'running', ?, 0, "
                "0, 0, 0, 0)",
                (now,),
            )
            run_id = result.lastrowid
        self._next_item += 1
        result = await services.store.execute(
            "INSERT INTO run_items (run_id, item_id, queue_pos, state, attempt) "
            "VALUES (?, ?, ?, 'up_next', ?) "
            "ON CONFLICT (run_id, item_id) DO UPDATE SET attempt = excluded.attempt",
            (run_id, item_id, self._next_item, attempt),
        )
        run_item_id = await services.store.fetchval(
            "SELECT id FROM run_items WHERE run_id = ? AND item_id = ?", (run_id, item_id)
        )
        context_uri = row["uri"]
        if row["kind"] == "liked":
            context_uri = self.world.catalog.liked_uri
        config = services.config
        logs = config.spytify_logs_dir
        work = config.runtime_dir / "spytify-cwd"
        return ItemJob(
            run_id=run_id,
            run_item_id=run_item_id,
            item_id=item_id,
            kind=row["kind"],
            name=row["name"],
            context_uri=context_uri,
            attempt=attempt,
            snapshot_unread=snapshot_unread,
            device_id=self.world.catalog.our_device.id,
            log_file=logs / f"{run_id}-{item_id}.log",
            events_file=logs / f"{run_id}-{item_id}.events.jsonl",
            socket_path=config.runtime_dir / f"spytify-{run_id}-{self._next_item}.sock",
            work_dir=work,
            timeouts=timeouts or Timeouts(),
        )

    async def run_item(
        self,
        job: ItemJob,
        *,
        host: RecordingHost | None = None,
        control: ItemControl | None = None,
        within: float = 3600,
    ) -> ItemReport:
        """Runs engine/item.py's ItemEngine for `job` on the fake clock and returns its report.
        `host` defaults to a new RecordingHost; pass your own to look at it afterwards."""
        from spotivault.engine.item import ItemEngine

        engine = ItemEngine(
            self.services, job, host=host or RecordingHost(), control=control or ItemControl()
        )
        task = asyncio.ensure_future(engine.run())
        await self.clock.advance_until(task.done, within=within)
        report = await task
        # Let the simulator's bus reader catch up, so an event published just before the item
        # returned (an `error`, say) is already collected when the test looks.
        await self.clock.settle()
        return report

    # --- Looking at what happened --------------------------------------------------------------

    def events_of(self, *types: str) -> list[dict[str, Any]]:
        """The `data` of every bus event of these types, in order."""
        return [event.data for event in self.events if event.type in types]

    def mpris_calls(self) -> list[str]:
        """The MPRIS player methods the controller called (Spytify's own Next isn't one)."""
        return list(self.world.mpris.calls)

    def webapi_calls(self) -> list[str]:
        """The Web API endpoints called, in order ("PUT /me/player/play", …)."""
        return self.world.webapi.endpoints()

    def recorder_sessions(self) -> Sequence[Any]:
        """Every simulated spytifyd started, oldest first (fake/recorder.py SimRecorderSession)."""
        return self.world.recorder.sessions

    def music_files(self) -> list[Path]:
        """Every file under the music folder but Spytify's own `.spytify/`."""
        music = self.services.config.music_dir
        return sorted(
            path
            for path in music.rglob("*")
            if path.is_file() and ".spytify" not in path.relative_to(music).parts
        )


class _Started:
    """`async with Sim.started(services) as sim`: starts and closes the simulator."""

    def __init__(self, sim: Sim) -> None:
        self.sim = sim

    async def __aenter__(self) -> Sim:
        await self.sim.start()
        return self.sim

    async def __aexit__(self, *exc: object) -> None:
        await self.sim.close()
