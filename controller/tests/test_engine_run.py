"""engine/run.py, queue.py, precheck.py, recovery.py and the runs/status endpoints.

Owner: engine-run. Most tests run the run engine with a scripted item engine (`ScriptedItems`
below, put in place of `services.runs.make_item_engine`): each item goes through its phases and
ends as its script says, on the fake clock. That tests the run engine's own rules (the queue,
pauses, stops, interruptions, events, rows) apart from the item engine's, which
tests/test_engine_item.py covers on the simulator. The tests at the end run the real ItemEngine
end to end; they're skipped while engine/item.py is still a stub.
"""

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from contract import assert_response, assert_schema
from engine_sim import ELSEWHERE, ELSEWHERE_ARTIST, Sim
from spotivault.api.models import Counters, HistoryRow, RunTimeLeft
from spotivault.app import create_app
from spotivault.clock import iso_ms, parse_iso
from spotivault.config import Config
from spotivault.engine import run as run_module
from spotivault.engine.item import ItemEngine
from spotivault.engine.queue import (
    DEFAULT_RUN_ORDER,
    Candidate,
    order_queue,
    run_order_groups,
)
from spotivault.engine.recovery import recover
from spotivault.engine.run import RunEngine, merge_attempts
from spotivault.engine.states import ItemState
from spotivault.engine.types import (
    InterruptedBy,
    ItemControl,
    ItemJob,
    ItemLeft,
    ItemLive,
    ItemOutcome,
    ItemReport,
    ItemTimings,
    MissingTrack,
    RunFailure,
    StopRequest,
    Takeover,
    TrackCounts,
)
from spotivault.errors import ApiError
from spotivault.fake import build_fake_ports
from spotivault.fake.clock import FakeClock
from spotivault.fake.world import world_of
from spotivault.ports import Device, LoginSignals, SpotifyUnavailable
from spotivault.services import Services, build_services
from spotivault.windows import Window

PIXEL = Device(
    id="pixel9device0000000000000000000000000000",
    name="Pixel 9",
    type="Smartphone",
    is_active=True,
    is_restricted=False,
    volume_percent=60,
)
ITEM_ENGINE_BUILT = 'NotImplementedError("engine-item' not in inspect.getsource(ItemEngine)
needs_item_engine = pytest.mark.skipif(
    not ITEM_ENGINE_BUILT, reason="S6 engine-item: ItemEngine isn't built yet"
)


# --- A scripted item engine --------------------------------------------------------------------


@dataclass
class Script:
    """How one attempt at an item goes. By default: every phase, 10 s of playing, 2 tracks
    recorded, a 5 s finishing tail (the real one is ~25 s), done."""

    outcome: ItemOutcome = "done"
    play_s: float = 10.0
    counts: TrackCounts = field(
        default_factory=lambda: TrackCounts(recorded=2, skipped_duplicate=1, bytes=2_000_000)
    )
    interrupted_by: InterruptedBy | None = None
    run_failure: RunFailure | None = None
    until_stopped: bool = False  # plays until a stop comes
    ignore_stop: bool = False  # a stop changes nothing: it never ends (the SIGTERM bound)
    crash: bool = False  # run() raises in `playing`
    left: ItemLeft | None = None  # ItemLive.left while playing (None: as if not planned yet)


class ScriptedItem:
    """One attempt, as its Script says. Reports phases and counts like the real item engine."""

    def __init__(
        self,
        services: Services,
        job: ItemJob,
        host: Any,
        control: ItemControl,
        script: Script,
    ) -> None:
        self.services = services
        self.job = job
        self.host = host
        self.control = control
        self.script = script
        self.phase: ItemState = "up_next"
        self.reported: ItemState = "up_next"  # the last phase the run engine has taken in

    @property
    def recorder_pid(self) -> int | None:
        return 4242 if self.phase in ("starting", "playing", "finishing") else None

    def live(self) -> ItemLive:
        return ItemLive(
            phase=self.phase,
            session_state="recording" if self.phase == "playing" else None,
            now_playing=None,
            tracks=(),
            left=self.script.left if self.phase == "playing" else None,
        )

    async def _enter(self, phase: ItemState, **extra: Any) -> None:
        self.phase = phase
        await self.host.item_phase(self.job, phase, **extra)
        self.reported = phase

    def _report(self, outcome: ItemOutcome, counts: TrackCounts, **extra: Any) -> ItemReport:
        now = self.services.clock.now()
        timings = ItemTimings(started_at=now, ended_at=now, phase_s={"playing": 1.0})
        return ItemReport(
            outcome=outcome, counts=counts, timings=timings, mode="missing_only", planned=2, **extra
        )

    async def run(self) -> ItemReport:
        script = self.script
        clock = self.services.clock
        await self._enter("planning")
        if script.outcome == "up_to_date":
            return self._report("up_to_date", TrackCounts(), up_to_date_by="nothing_missing")
        await self._enter("preflight", mode="missing_only", planned=2)
        if script.outcome == "device_busy":
            return self._report("device_busy", TrackCounts(), device_busy=PIXEL)
        for phase in ("preparing", "starting", "playing"):
            await self._enter(phase)  # type: ignore[arg-type]
        stop = None
        if script.ignore_stop:
            await clock.sleep(100_000)
        elif script.until_stopped:
            stop = await self.control.changed()
        else:
            stop = await first_of(clock.sleep(script.play_s), self.control.changed())
        if script.crash:
            raise RuntimeError("scripted crash")
        counts = script.counts
        await self.host.item_counts(self.job, counts)
        await self._enter("finishing")
        await clock.sleep(5)
        if isinstance(stop, StopRequest):
            if stop.cause == "shutdown":
                return self._report("interrupted", counts, interrupted_by="shutdown")
            outcome: ItemOutcome = "carried_over" if stop.cause == "window_end" else "stopped"
            return self._report(outcome, counts)
        if script.outcome == "interrupted":
            takeover = None
            if script.interrupted_by == "takeover":
                takeover = Takeover(device=PIXEL, discarded_take_id="20261115-000000-001")
            return self._report(
                "interrupted", counts, interrupted_by=script.interrupted_by, takeover=takeover
            )
        return self._report(script.outcome, counts, run_failure=script.run_failure)


async def first_of(sleeping: Any, stopping: Any) -> StopRequest | None:
    """Waits for the sleep or a stop, whichever comes first: the stop, or None."""
    async with asyncio.TaskGroup() as group:
        sleep = group.create_task(sleeping)
        stop = group.create_task(stopping)
        await asyncio.wait({sleep, stop}, return_when=asyncio.FIRST_COMPLETED)
        sleep.cancel()
        stop.cancel()
    return stop.result() if stop.done() and not stop.cancelled() else None


class ScriptedItems:
    """`services.runs.make_item_engine` for these tests: a ScriptedItem per attempt, from the
    scripts given per item (attempt after attempt), else the default Script."""

    def __init__(self) -> None:
        self.scripts: dict[str, list[Script]] = {}
        self.jobs: list[ItemJob] = []
        self.engines: list[ScriptedItem] = []

    def script(self, item_id: str, *scripts: Script) -> None:
        self.scripts[item_id] = list(scripts)

    def __call__(
        self, services: Services, job: ItemJob, *, host: Any, control: ItemControl
    ) -> ScriptedItem:
        self.jobs.append(job)
        queued = self.scripts.get(job.item_id)
        script = queued.pop(0) if queued else Script()
        engine = ScriptedItem(services, job, host, control, script)
        self.engines.append(engine)
        return engine

    def ran(self) -> list[str]:
        return [job.item_id for job in self.jobs]

    def attempts(self) -> list[tuple[str, int]]:
        return [(job.item_id, job.attempt) for job in self.jobs]


# --- Fixtures and helpers ----------------------------------------------------------------------


@pytest.fixture
async def items(sim: Sim) -> AsyncIterator[ScriptedItems]:
    """The scripted item engine, in place of ItemEngine. At the end, a run a failed test left
    going is stopped as SIGTERM would, so the app's own shutdown doesn't wait on the fake
    clock."""
    services = sim.services
    scripted = ScriptedItems()
    services.runs.make_item_engine = scripted
    use_history_rows(services)
    yield scripted
    if services.runs.active() is not None:
        stopping = asyncio.ensure_future(services.runs.shutdown())
        await sim.clock.advance_until(stopping.done, within=120)
        await stopping


def use_history_rows(services: Services) -> None:
    """run.finished needs History's row. While history.py is still a stub, a minimal one from
    the runs row stands in; once it's built, the real one is used."""
    real = services.history.history_row

    async def row(run_id: int) -> HistoryRow:
        try:
            return await real(run_id)
        except NotImplementedError:
            return await minimal_history_row(services, run_id)

    services.history.history_row = row  # type: ignore[method-assign]


async def minimal_history_row(services: Services, run_id: int) -> HistoryRow:
    row = await services.store.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
    if row is None:
        raise LookupError(run_id)
    return HistoryRow(
        id=row["id"],
        kind=row["kind"],
        trigger=row["trigger"],
        started_at=parse_iso(row["started_at"]),
        ended_at=parse_iso(row["ended_at"]) if row["ended_at"] else None,
        duration_s=None,
        outcome=row["outcome"],
        counters=Counters(
            recorded=row["recorded"] or 0,
            skipped_duplicate=row["skipped_duplicate"] or 0,
            skipped_other=row["skipped_other"] or 0,
            failed=row["failed"] or 0,
            bytes_added=row["bytes_added"] or 0,
        ),
        reason=row["reason"],
        window=None,
    )


async def until(sim: Sim, condition: Callable[[], bool], *, within: float = 3600) -> None:
    """Moves the fake clock a second at a time until `condition()` holds. The short real sleep
    lets the store's thread finish what the engine waits on."""
    clock = sim.clock
    end = clock.monotonic() + within
    while not condition():
        if clock.monotonic() >= end:
            raise TimeoutError(f"still not true after {within} s of fake time")
        await clock.advance(1.0)
        await asyncio.sleep(0.001)
    await clock.settle()  # the simulator's event reader catches up


async def settle(sim: Sim) -> None:
    """Lets the simulator's event reader catch up with what was just published."""
    await sim.clock.settle()


def idle(services: Services) -> Callable[[], bool]:
    """No run is going, and the last one's end is all out. `active()` is None a little early:
    the engine then still publishes run.finished, after reading History's row on the store's
    thread, while `until` moves the clock. Its idle flag is set only once that's done."""
    runs = services.runs
    return lambda: runs.active() is None and runs._idle.is_set()


def state_is(services: Services, *states: str) -> Callable[[], bool]:
    def check() -> bool:
        active = services.runs.active()
        return active is not None and active.state in states

    return check


def running_item(items: ScriptedItems, item_id: str, phase: str = "playing") -> Callable[[], bool]:
    """The item is in `phase`, and the run engine has taken it in: its `item_phase` call
    returned, so the run.state it may send for the phase is out or held, not still to come.
    `until` moves the clock while that call waits on the store's thread."""

    def check() -> bool:
        return any(e.job.item_id == item_id and e.reported == phase for e in items.engines[-1:])

    return check


async def run_items(services: Services, run_id: int) -> dict[str, Any]:
    rows = await services.store.fetchall(
        "SELECT * FROM run_items WHERE run_id = ? ORDER BY queue_pos", (run_id,)
    )
    return {row["item_id"]: row for row in rows}


async def run_row(services: Services, run_id: int) -> Any:
    return await services.store.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))


@dataclass
class Library:
    liked: str
    old_playlist: str  # changed longer ago
    new_playlist: str  # changed recently
    followed: str  # never changed (changed_at NULL)
    old_album: str  # added first
    new_album: str
    untracked: str


async def make_library(sim: Sim) -> Library:
    """Liked Songs, three tracked playlists, two albums and an untracked playlist, with
    changed_at and added_at set so the run order is known."""
    old = sim.playlist("Old Mix", tracks=3)
    new = sim.playlist("New Mix", tracks=3)
    untracked = sim.playlist("Not Tracked", tracks=2)
    followed = sim.playlist("Theirs", tracks=4, access="followed")
    first = sim.album("First Album", 3)
    second = sim.album("Second Album", 3)
    await sim.refresh()
    await sim.add_playlist(followed)
    await sim.add_album(first)
    await sim.add_album(second)
    await sim.track(untracked.playlist.id, False)
    await sim.track("liked")
    store = sim.services.store
    for item_id, changed in (
        (old.playlist.id, "2026-10-01T00:00:00.000Z"),
        (new.playlist.id, "2026-11-01T00:00:00.000Z"),
        (followed.playlist.id, None),
    ):
        await store.execute("UPDATE items SET changed_at = ? WHERE id = ?", (changed, item_id))
    for item_id, added in (
        (first.album.id, "2026-09-01T00:00:00.000Z"),
        (second.album.id, "2026-09-02T00:00:00.000Z"),
    ):
        await store.execute("UPDATE items SET added_at = ? WHERE id = ?", (added, item_id))
    return Library(
        liked="liked",
        old_playlist=old.playlist.id,
        new_playlist=new.playlist.id,
        followed=followed.playlist.id,
        old_album=first.album.id,
        new_album=second.album.id,
        untracked=untracked.playlist.id,
    )


async def one_album(sim: Sim, name: str = "Elsewhere") -> str:
    album = sim.elsewhere() if name == "Elsewhere" else sim.album(name, 3)
    await sim.refresh()
    await sim.add_album(album)
    await sim.track("liked", False)
    return album.album.id


async def two_albums(sim: Sim) -> tuple[str, str]:
    first = sim.album("First Album", 3)
    second = sim.album("Second Album", 3)
    await sim.refresh()
    await sim.add_album(first)
    await sim.add_album(second)
    await sim.track("liked", False)
    await sim.services.store.execute(
        "UPDATE items SET added_at = ? WHERE id = ?", ("2026-09-01T00:00:00.000Z", first.album.id)
    )
    return first.album.id, second.album.id


async def start(services: Services, ids: list[str] | None = None) -> int:
    created = await services.runs.create_run(ids)
    assert created.started
    return created.run_id


async def scheduled_window(sim: Sim, hours: int = 6) -> Window:
    """A window in progress in the grid: this hour and the next ones, written to the grid as a
    PUT would, so the scheduler's tick lets a scheduled run go on (it records only in active
    hours, and stops once now is in none)."""
    zone = sim.services.config.zone
    start = sim.clock.now().astimezone(zone).replace(minute=0, second=0, microsecond=0)
    cells = [start + timedelta(hours=n) for n in range(hours)]
    rows = [(cell.weekday(), cell.hour) for cell in cells]

    def write(conn: Any) -> None:
        conn.execute("DELETE FROM schedule_hours")
        conn.executemany("INSERT INTO schedule_hours (day, hour) VALUES (?, ?)", rows)

    await sim.services.store.transaction(write)
    return Window(start=start.astimezone(UTC), end=(start + timedelta(hours=hours)).astimezone(UTC))


# --- The queue's order (pure) ------------------------------------------------------------------


def candidate(
    item_id: str,
    kind: str,
    *,
    changed: str | None = None,
    added: str = "2026-01-01T00:00:00.000Z",
    carried: bool = False,
) -> Candidate:
    return Candidate(item_id, kind, changed, added, carried)  # type: ignore[arg-type]


def test_order_queue_follows_the_run_order_and_each_groups_fixed_order() -> None:
    items = [
        candidate("a2", "album", added="2026-02-01T00:00:00.000Z"),
        candidate("a1", "album", added="2026-01-01T00:00:00.000Z"),
        candidate("p-never", "followed"),
        candidate("p-old", "owned", changed="2026-01-01T00:00:00.000Z"),
        candidate("p-new", "linked", changed="2026-03-01T00:00:00.000Z"),
        candidate("liked", "liked", changed="2026-03-02T00:00:00.000Z"),
        candidate("carried-album", "album", carried=True),
        candidate("carried-playlist", "owned", carried=True),
    ]
    ids = [c.item_id for c in order_queue(items, DEFAULT_RUN_ORDER)]
    assert ids == [
        "carried-playlist",  # carried over first; among them, the other groups' order
        "carried-album",
        "liked",
        "p-new",  # most recently changed first, never changed last
        "p-old",
        "p-never",
        "a1",  # oldest added first
        "a2",
    ]
    albums_first = order_queue(items, ["albums", "playlists", "liked", "carried_over"])
    assert [c.item_id for c in albums_first] == [
        "a1",
        "a2",
        "p-new",
        "p-old",
        "p-never",
        "liked",
        "carried-album",
        "carried-playlist",
    ]


def test_a_damaged_run_order_still_has_every_group() -> None:
    assert run_order_groups(["albums", "bogus", "albums"]) == (
        "albums",
        "carried_over",
        "liked",
        "playlists",
    )
    assert run_order_groups(None) == DEFAULT_RUN_ORDER
    duplicate = [candidate("x", "owned"), candidate("x", "owned")]
    assert [c.item_id for c in order_queue(duplicate, DEFAULT_RUN_ORDER)] == ["x"]


def test_a_retry_doesnt_count_its_duplicates_twice() -> None:
    first = TrackCounts(recorded=3, skipped_duplicate=2, failed=1, bytes=300)
    retry = TrackCounts(recorded=1, skipped_duplicate=5, failed=0, bytes=100)
    merged = merge_attempts(first, retry)
    assert merged == TrackCounts(recorded=4, skipped_duplicate=4, failed=0, bytes=400)
    assert merge_attempts(TrackCounts(), retry) == retry


# --- Run now -----------------------------------------------------------------------------------


async def test_run_now_runs_everything_due_in_run_order(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    library = await make_library(sim)
    run_id = await start(services)
    await until(sim, idle(services))
    assert items.ran() == [
        library.liked,
        library.new_playlist,
        library.old_playlist,
        library.followed,
        library.old_album,
        library.new_album,
    ]
    run = await run_row(services, run_id)
    assert (run["state"], run["outcome"], run["reason"]) == ("ended", "completed", None)
    assert (run["recorded"], run["skipped_duplicate"], run["bytes_added"]) == (12, 6, 12_000_000)
    rows = await run_items(services, run_id)
    assert list(rows) == items.ran()  # queue_pos follows the order
    assert {row["state"] for row in rows.values()} == {"done"}
    assert [rows[i]["ran_order"] for i in items.ran()] == [1, 2, 3, 4, 5, 6]
    first = rows[library.liked]
    assert (first["recorded"], first["skipped"], first["mode"], first["planned"]) == (
        2,
        1,
        "missing_only",
        2,
    )
    assert first["started_at"] is not None and first["ended_at"] is not None
    assert first["timings"] is not None and first["log_file"].endswith(f"{run_id}-liked.log")


async def test_the_run_order_setting_applies(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    library = await make_library(sim)
    await services.settings.set_value("run_order", ["albums", "playlists", "liked", "carried_over"])
    await start(services)
    await until(sim, idle(services))
    assert items.ran()[:2] == [library.old_album, library.new_album]
    assert items.ran()[-1] == library.liked


async def test_a_new_run_order_applies_from_the_next_item(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    library = await make_library(sim)
    items.script(library.liked, Script(play_s=120))
    await start(services)
    await until(sim, running_item(items, library.liked))
    await services.settings.set_value("run_order", ["albums", "playlists", "liked", "carried_over"])
    await until(sim, idle(services))
    assert items.ran() == [
        library.liked,  # already going
        library.old_album,
        library.new_album,
        library.new_playlist,
        library.old_playlist,
        library.followed,
    ]


async def test_items_run_just_those(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    library = await make_library(sim)
    created = await services.runs.create_run([library.untracked, library.old_album])
    assert created.added == [library.untracked, library.old_album]
    await until(sim, idle(services))
    assert items.ran() == [library.untracked, library.old_album]  # tracking doesn't matter


async def test_up_to_date_items_and_an_empty_queue(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    album = await one_album(sim)
    items.script(album, Script(outcome="up_to_date"))
    run_id = await start(services)
    await until(sim, idle(services))
    rows = await run_items(services, run_id)
    assert (rows[album]["state"], rows[album]["up_to_date_by"]) == ("up_to_date", "nothing_missing")
    assert (await run_row(services, run_id))["outcome"] == "completed"

    await services.store.execute("UPDATE items SET removed_at = '2026-11-15T00:00:00.000Z'")
    run_id = await start(services)
    await until(sim, idle(services))
    assert (await run_row(services, run_id))["outcome"] == "completed"
    assert await run_items(services, run_id) == {}


# --- The quick checks and the pre-run check ----------------------------------------------------


async def test_the_quick_checks_answer_409(
    sim: Sim, items: ScriptedItems, client: httpx.AsyncClient
) -> None:
    services = sim.services
    world = sim.world
    album = await one_album(sim)

    async def post(body: dict[str, Any]) -> tuple[int, str | None]:
        response = await client.post("/api/runs", json=body)
        assert_response(response, "/api/runs")
        if response.status_code >= 400:
            return response.status_code, response.json()["error"]["code"]
        return response.status_code, None

    response = await client.post("/api/runs", json={"items": ["0" * 22]})
    assert response.status_code == 404
    assert response.json()["error"]["details"] == {"ids": ["0" * 22]}

    # Run now while a run is going.
    items.script(album, Script(until_stopped=True))
    assert await post({}) == (202, None)
    await until(sim, running_item(items, album))
    assert await post({}) == (409, "run_active")
    await services.runs.stop("now")
    await until(sim, idle(services))
    runs = await services.store.fetchval("SELECT count(*) FROM runs")

    world.client.log_out()
    await services.client.refresh()
    assert await post({}) == (409, "client_logged_out")
    world.client.log_in()
    world.client.version = None
    await services.client.refresh()
    assert await post({}) == (409, "client_not_installed")
    world.client.installed()
    await services.client.refresh()

    world.webapi.expired = True
    with pytest.raises(Exception, match="invalid_grant"):
        await services.ports.webapi.me()
    assert await post({}) == (409, "connection_expired")
    await services.auth.disconnect()
    assert await post({}) == (409, "not_connected")
    await services.store.execute("DELETE FROM meta WHERE key = 'setup_completed_at'")
    assert await post({}) == (409, "setup_incomplete")
    assert await services.store.fetchval("SELECT count(*) FROM runs") == runs  # none started


@pytest.mark.parametrize("problem", ["storage", "setting_drifted"])
async def test_a_failed_pre_run_check_ends_the_run_failed(
    sim: Sim, items: ScriptedItems, problem: str
) -> None:
    services = sim.services
    await one_album(sim)
    if problem == "storage":
        sim.world.storage.set_state(services.config.music_dir, writable=False)
    else:
        sim.world.client.set_pref("audio.automix", "true")
    run_id = await start(services)
    await until(sim, idle(services))
    run = await run_row(services, run_id)
    assert (run["state"], run["outcome"], run["reason"]) == ("ended", "failed", problem)
    assert items.ran() == [] and await run_items(services, run_id) == {}
    errors = sim.events_of("error")
    if problem == "storage":
        assert [e["code"] for e in errors] == ["storage"]
        assert errors[0]["source"] == "controller" and errors[0]["run_id"] == run_id
    else:
        assert errors == []  # the failure reason says it (no error code for it in events.md)
    states = [(e["previous_state"], e["state"]) for e in sim.events_of("run.state")]
    assert states == [("idle", "starting"), ("starting", "idle")]
    finished = sim.events_of("run.finished")
    assert [f["run"]["id"] for f in finished] == [run_id]
    assert (await services.client.status()).restartable  # set_run_active(False) on failure


async def test_a_web_api_failure_in_the_pre_run_check(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    await one_album(sim)
    sim.world.webapi.failures = [SpotifyUnavailable("503 after every retry", status=503)]
    run_id = await start(services)
    await until(sim, idle(services))
    run = await run_row(services, run_id)
    assert (run["outcome"], run["reason"]) == ("failed", "webapi")
    errors = sim.events_of("error")
    assert [(e["code"], e["fatal"], e["withdrawn"]) for e in errors] == [("webapi", False, False)]
    assert items.ran() == []


async def test_our_device_missing_restarts_the_client_once(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    world = sim.world
    album = await one_album(sim)
    # The client looks logged in, but its device isn't listed (logged out on Spotify's side).
    world.client.signals = LoginSignals(user_folder=True, window_title="Spotify Premium")
    world.player.logged_in = False
    run_id = await start(services)
    await until(sim, idle(services))
    assert world.client.restarts == 1
    assert [e["code"] for e in sim.events_of("error")] == ["client_restarted"]
    assert (await run_row(services, run_id))["outcome"] == "completed"
    assert items.ran() == [album]

    # It doesn't come back: the run fails device_missing after 60 s.
    world.player.logged_in = False
    world.client.login_saved = False
    run_id = await start(services)
    await until(sim, idle(services))
    run = await run_row(services, run_id)
    assert (run["outcome"], run["reason"]) == ("failed", "device_missing")
    assert world.client.restarts == 2
    ended = parse_iso(run["ended_at"]) - parse_iso(run["started_at"])
    assert timedelta(seconds=60) <= ended < timedelta(seconds=70)


async def test_d6_starts_paused_and_never_takes_playback(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    album = await one_album(sim)
    sim.world.player.play_elsewhere("Pixel 9")
    run_id = await start(services)
    await until(sim, state_is(services, "paused"))
    active = services.runs.active()
    assert active is not None and active.paused_reason == "device_busy"
    moved = sim.events_of("device.moved")
    assert len(moved) == 1
    assert moved[0]["item_id"] is None and moved[0]["discarded_take_id"] is None
    assert moved[0]["device"]["name"] == "Pixel 9"
    await sim.clock.advance(600)
    assert items.ran() == [] and "PUT /me/player/play" not in sim.webapi_calls()
    assert sim.world.player.remote is not None and sim.world.player.remote.is_playing
    queue = (await services.runs.current()).queue
    assert [(q.item_id, q.state) for q in queue] == [(album, "up_next")]

    # Resume: the phone is paused, and the run goes on.
    summary = await services.runs.resume()
    assert summary.state == "running" and summary.paused_reason is None
    assert "PUT /me/player/pause" in sim.webapi_calls()
    await until(sim, idle(services))
    assert items.ran() == [album]
    assert (await run_row(services, run_id))["outcome"] == "completed"


async def test_d6_between_items_pauses_and_the_item_runs_first(
    sim: Sim, items: ScriptedItems
) -> None:
    services = sim.services
    first, second = await two_albums(sim)
    items.script(second, Script(outcome="device_busy"), Script())
    run_id = await start(services)
    await until(sim, state_is(services, "paused"))
    rows = await run_items(services, run_id)
    assert rows[second]["state"] == "up_next" and rows[first]["state"] == "done"
    status = await services.runs.status()
    assert status.item is not None and status.item.item_id == second
    await services.runs.resume()
    await until(sim, idle(services))
    assert items.attempts() == [(first, 1), (second, 1), (second, 1)]


# --- The queue while the run goes --------------------------------------------------------------


async def test_forced_items_go_right_after_the_current_one(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    library = await make_library(sim)
    items.script(library.liked, Script(play_s=300))
    run_id = await start(services)
    await until(sim, running_item(items, library.liked))
    created = await services.runs.create_run([library.new_album, library.untracked])
    assert (created.run_id, created.started) == (run_id, False)
    assert created.added == [library.new_album, library.untracked]
    queue = [q.item_id for q in (await services.runs.current()).queue]
    assert queue == [
        library.liked,
        library.new_album,  # moved up from the end
        library.untracked,  # added
        library.new_playlist,
        library.old_playlist,
        library.followed,
        library.old_album,
    ]
    await settle(sim)
    assert sim.events_of("run.queue")[-1]["queue"][1]["item_id"] == library.new_album
    # The current item isn't added again.
    assert (await services.runs.create_run([library.liked])).added == []
    await until(sim, idle(services))
    assert items.ran() == queue
    rows = await run_items(services, run_id)
    assert rows[library.untracked]["forced"] == 1 and rows[library.new_album]["forced"] == 1
    assert rows[library.old_album]["forced"] == 0


async def test_naming_the_current_item_adds_only_the_others(sim: Sim, items: ScriptedItems) -> None:
    """Back up now on [the current item, a waiting one]: the current item isn't queued again,
    and `added` names only the one that moved (openapi.yaml RunCreated.added)."""
    services = sim.services
    library = await make_library(sim)
    items.script(library.liked, Script(play_s=300))
    run_id = await start(services)
    await until(sim, running_item(items, library.liked))
    created = await services.runs.create_run([library.liked, library.old_album])
    assert (created.run_id, created.started, created.added) == (run_id, False, [library.old_album])
    queue = [q.item_id for q in (await services.runs.current()).queue]
    assert queue[:2] == [library.liked, library.old_album]
    assert queue.count(library.liked) == 1
    await until(sim, idle(services))
    assert items.ran() == queue


async def test_items_forced_while_starting_go_first(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    library = await make_library(sim)
    run_id = await start(services)
    created = await services.runs.create_run([library.new_album])
    assert (created.run_id, created.started, created.added) == (run_id, False, [library.new_album])
    await until(sim, idle(services))
    assert items.ran()[0] == library.new_album
    assert (await run_items(services, run_id))[library.new_album]["forced"] == 1


async def test_remove_queued_item(
    sim: Sim, items: ScriptedItems, client: httpx.AsyncClient
) -> None:
    services = sim.services
    first, second = await two_albums(sim)
    path = "/api/runs/current/items/{id}"
    response = await client.delete(path.format(id=second))
    assert (response.status_code, response.json()["error"]["code"]) == (409, "no_run")
    assert_response(response, path)
    items.script(first, Script(play_s=300))
    run_id = await start(services)
    await until(sim, running_item(items, first))
    response = await client.delete(path.format(id=first))
    assert (response.status_code, response.json()["error"]["code"]) == (409, "item_is_current")
    response = await client.delete(path.format(id="liked"))
    assert response.status_code == 404
    assert_response(response, path)
    response = await client.delete(path.format(id=second))
    assert response.status_code == 204
    await settle(sim)
    assert sim.events_of("item.state")[-1]["item"]["state"] == "removed"
    await until(sim, idle(services))
    assert items.ran() == [first]
    rows = await run_items(services, run_id)
    assert rows[second]["state"] == "removed"
    assert (await run_row(services, run_id))["outcome"] == "completed"


# --- Interruptions -----------------------------------------------------------------------------


async def test_interrupted_is_requeued_once_then_partial(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    first, second = await two_albums(sim)
    stall = Script(outcome="interrupted", interrupted_by="stall")
    items.script(first, stall, stall)
    run_id = await start(services)
    await until(sim, idle(services))
    assert items.attempts() == [(first, 1), (second, 1), (first, 2)]
    requeued = [e for e in sim.events_of("item.state") if e["item"]["state"] == "interrupted"]
    assert requeued[0]["item"]["attempt"] == 2 and requeued[0]["item"]["badges"] == []
    queues = sim.events_of("run.queue")
    assert [q["item_id"] for q in queues[-1]["queue"]] == [second, first]
    rows = await run_items(services, run_id)
    row = rows[first]
    assert (row["state"], row["attempt"], row["interrupted_count"]) == ("partial", 2, 2)
    assert row["interrupted_by"] == "stall" and row["reason"] == "Interrupted twice."
    assert list(rows) == [second, first]  # queue_pos: re-queued at the end
    # The retry's duplicates are what the first attempt recorded: counted once.
    assert (row["recorded"], row["skipped"]) == (4, 1)
    run = await run_row(services, run_id)
    assert run["outcome"] == "completed_with_issues"
    detail = (await services.runs.current()).queue  # idle now: empty
    assert detail == []


async def test_a_takeover_pauses_the_run_and_resume_restarts_the_item(
    sim: Sim, items: ScriptedItems, client: httpx.AsyncClient
) -> None:
    services = sim.services
    first, second = await two_albums(sim)
    items.script(first, Script(outcome="interrupted", interrupted_by="takeover"), Script())
    response = await client.post("/api/runs/current/resume")
    assert (response.status_code, response.json()["error"]["code"]) == (409, "no_run")
    run_id = await start(services)
    await until(sim, state_is(services, "paused"))
    active = services.runs.active()
    assert active is not None and active.paused_reason == "device_moved"
    moved = sim.events_of("device.moved")
    assert moved == [
        {
            "run_id": run_id,
            "item_id": first,
            "device": {"id": PIXEL.id, "name": "Pixel 9", "type": "Smartphone"},
            "discarded_take_id": "20261115-000000-001",
        }
    ]
    status = (await client.get("/api/status")).json()
    assert status["state"] == "paused" and status["item"]["state"] == "interrupted"
    assert status["item"]["reason"] == "Playback moved to Pixel 9."
    await sim.clock.advance(600)
    assert items.attempts() == [(first, 1)]  # it never takes playback back by itself

    response = await client.post("/api/runs/current/resume")
    assert response.status_code == 202
    assert_response(response, "/api/runs/current/resume")
    await until(sim, idle(services))
    assert items.attempts() == [(first, 1), (first, 2), (second, 1)]  # the same item first
    rows = await run_items(services, run_id)
    assert (rows[first]["state"], rows[first]["interrupted_count"]) == ("done", 1)
    assert (await run_row(services, run_id))["outcome"] == "completed"
    response = await client.post("/api/runs/current/resume")
    assert response.status_code == 409


async def test_a_second_takeover_ends_the_item_partial(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    first, second = await two_albums(sim)
    takeover = Script(outcome="interrupted", interrupted_by="takeover")
    items.script(first, takeover, takeover)
    run_id = await start(services)
    await until(sim, state_is(services, "paused"))
    await services.runs.resume()
    await until(sim, lambda: len(items.jobs) == 2 and state_is(services, "paused")())
    rows = await run_items(services, run_id)
    assert (rows[first]["state"], rows[first]["interrupted_count"]) == ("partial", 2)
    assert len(sim.events_of("device.moved")) == 2  # the run pauses again
    await services.runs.resume()
    await until(sim, idle(services))
    assert items.attempts() == [(first, 1), (first, 2), (second, 1)]
    assert (await run_row(services, run_id))["outcome"] == "completed_with_issues"


async def test_an_item_engine_crash_fails_the_item_not_the_run(
    sim: Sim, items: ScriptedItems
) -> None:
    services = sim.services
    first, second = await two_albums(sim)
    items.script(first, Script(crash=True))
    run_id = await start(services)
    await until(sim, idle(services))
    rows = await run_items(services, run_id)
    assert rows[first]["state"] == "failed" and rows[second]["state"] == "done"
    assert (await run_row(services, run_id))["outcome"] == "completed_with_issues"


async def test_a_run_failure_ends_the_run(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    first, second = await two_albums(sim)
    failure = RunFailure("recorder", "spytifyd exited 2: bad setting")
    items.script(first, Script(outcome="failed", run_failure=failure))
    run_id = await start(services)
    await until(sim, idle(services))
    rows = await run_items(services, run_id)
    assert rows[first]["state"] == "failed" and rows[second]["state"] == "stopped"
    assert rows[first]["reason"] == failure.message
    run = await run_row(services, run_id)
    assert (run["outcome"], run["reason"]) == ("failed", "recorder")


# --- Stopping ----------------------------------------------------------------------------------


async def test_stop_after_this_track_and_stop_now(
    sim: Sim, items: ScriptedItems, client: httpx.AsyncClient
) -> None:
    services = sim.services
    first, second = await two_albums(sim)
    path = "/api/runs/current/stop"
    response = await client.post(path, json={"mode": "now"})
    assert (response.status_code, response.json()["error"]["code"]) == (409, "no_run")
    items.script(first, Script(until_stopped=True))
    run_id = await start(services)
    await until(sim, running_item(items, first))
    response = await client.post(path, json={"mode": "after_track"})
    assert response.status_code == 202
    assert_response(response, path)
    body = response.json()
    assert (body["state"], body["stop_mode"]) == ("stopping", "after_track")
    control = items.engines[0].control
    assert control.stop == StopRequest("after_track", "user")
    response = await client.post(path, json={"mode": "now"})  # upgrades it
    assert response.json()["stop_mode"] == "now"
    assert control.stop == StopRequest("now", "user")
    await until(sim, idle(services))
    rows = await run_items(services, run_id)
    assert rows[first]["state"] == "stopped" and rows[second]["state"] == "stopped"
    assert rows[second]["started_at"] is None  # it never ran
    run = await run_row(services, run_id)
    assert (run["outcome"], run["stop_mode"]) == ("stopped", "now")
    states = [e["state"] for e in sim.events_of("run.state")]
    assert "stopping" in states and states[-1] == "idle"
    assert "finishing" not in states[states.index("stopping") :]  # stopping stays stopping


def hold_the_refresh(services: Services, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The run's catalog refresh never ends (a large library, 250 ms a request): the stop must
    not wait for it. Returns the triggers it was called with."""
    called: list[str] = []

    async def refresh(*, trigger: str, run_id: int | None = None) -> Any:
        called.append(trigger)
        await asyncio.Event().wait()

    monkeypatch.setattr(services.catalog, "refresh", refresh)
    return called


async def test_stop_while_starting_ends_the_run_before_any_item(
    sim: Sim, items: ScriptedItems, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = sim.services
    first, _ = await two_albums(sim)
    refreshing = hold_the_refresh(services, monkeypatch)
    run_id = await start(services)
    await until(sim, lambda: refreshing == ["run"])
    summary = await services.runs.stop("after_track")
    assert (summary.state, summary.stop_mode) == ("stopping", "after_track")
    # The refresh was cancelled, not waited for: it never ends. The run ends with no time
    # passing; the slack is for its store work, in real time, while `until` moves the clock.
    await until(sim, idle(services), within=35)
    assert items.ran() == []
    run = await run_row(services, run_id)
    assert (run["outcome"], run["stop_mode"]) == ("stopped", "after_track")


async def test_sigterm_while_starting_ends_the_run_by_the_book(
    sim: Sim, items: ScriptedItems, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = sim.services
    await two_albums(sim)
    refreshing = hold_the_refresh(services, monkeypatch)
    run_id = await start(services)
    await until(sim, lambda: refreshing == ["run"])
    forced = []
    monkeypatch.setattr(services.runs, "_force_end", lambda run: forced.append(run))
    stopping = asyncio.ensure_future(services.runs.shutdown())
    # Inside the 40 s bound. The run ends with no time passing; the slack is for its store
    # work, in real time, while `until` moves the clock.
    await until(sim, stopping.done, within=35)
    await stopping
    assert forced == []  # ended by the driver, not repaired at the bound
    run = await run_row(services, run_id)
    assert (run["outcome"], run["reason"]) == ("failed", "container_restarted")
    assert items.ran() == []


async def test_a_stopping_run_takes_nothing_new(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    first, second = await two_albums(sim)
    items.script(first, Script(play_s=120))
    await start(services, [first])
    await until(sim, running_item(items, first))
    await services.runs.stop("after_track")  # the item's take finishes first: still stopping
    with pytest.raises(Exception, match="run_active"):
        await services.runs.create_run([second])
    await until(sim, idle(services))


async def test_no_run_starts_once_the_controller_is_stopping(
    sim: Sim, items: ScriptedItems
) -> None:
    services = sim.services
    first, _ = await two_albums(sim)
    await services.runs.shutdown()  # SIGTERM with nothing going: from now on, nothing starts
    assert services.runs.closing
    with pytest.raises(ApiError) as refused:
        await services.runs.create_run([first])
    assert (refused.value.status, refused.value.code) == (409, "run_active")
    with pytest.raises(RuntimeError, match="stopping"):
        await services.runs.start_scheduled(await scheduled_window(sim), trigger="scheduled")
    assert services.runs.active() is None


async def test_stop_while_paused_ends_the_run(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    album = await one_album(sim)
    sim.world.player.play_elsewhere("Pixel 9")
    run_id = await start(services)
    await until(sim, state_is(services, "paused"))
    await services.runs.stop("after_track")
    await until(sim, idle(services))
    run = await run_row(services, run_id)
    assert (run["outcome"], run["paused_reason"]) == ("stopped", None)
    assert (await run_items(services, run_id))[album]["state"] == "stopped"


async def test_end_window_carries_the_item_over(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    library = await make_library(sim)
    stall = Script(outcome="interrupted", interrupted_by="stall")
    items.script(library.liked, stall)
    items.script(library.old_playlist, Script(until_stopped=True))
    run_id = await services.runs.start_scheduled(await scheduled_window(sim), trigger="scheduled")
    await until(sim, running_item(items, library.old_playlist))
    with pytest.raises(RuntimeError):
        await services.runs.start_scheduled(await scheduled_window(sim), trigger="scheduled")
    await services.runs.end_window()
    await until(sim, idle(services))
    assert items.engines[-1].control.stop == StopRequest("after_track", "window_end")
    rows = await run_items(services, run_id)
    assert rows[library.old_playlist]["state"] == "carried_over"
    assert rows[library.old_playlist]["carried_over_out"] == 1
    assert rows[library.liked]["state"] == "carried_over"  # interrupted, waiting: cut off too
    assert rows[library.followed]["state"] == "stopped"  # up next: waits for the next window
    run = await run_row(services, run_id)
    assert (run["outcome"], run["trigger"]) == ("window_ended", "scheduled")
    assert run["window_start"] is not None and run["window_end"] is not None


async def test_end_window_does_nothing_to_run_now(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    album = await one_album(sim)
    items.script(album, Script(play_s=120))
    run_id = await start(services)
    await until(sim, running_item(items, album))
    await services.runs.end_window()
    await until(sim, idle(services))
    assert (await run_row(services, run_id))["outcome"] == "completed"


async def test_carried_over_items_go_first_next_run(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    library = await make_library(sim)
    items.script(library.old_album, Script(until_stopped=True))
    await services.runs.start_scheduled(await scheduled_window(sim), trigger="scheduled")
    await until(sim, running_item(items, library.old_album))
    await services.runs.end_window()
    await until(sim, idle(services))
    items.jobs.clear()
    items.engines.clear()
    run_id = await services.runs.start_scheduled(await scheduled_window(sim), trigger="scheduled")
    await until(sim, idle(services))
    assert items.ran()[0] == library.old_album
    rows = await run_items(services, run_id)
    assert rows[library.old_album]["carried_over_in"] == 1
    assert sim.events_of("run.queue")[-1]["queue"][0]["badges"] == ["carried_over_in"]
    # Once it ran again, it isn't carried over any more.
    items.jobs.clear()
    await start(services)
    await until(sim, idle(services))
    assert items.ran()[0] == library.liked


# --- What the API and the events show ----------------------------------------------------------


async def test_status_and_current_run_follow_the_run(
    sim: Sim, items: ScriptedItems, client: httpx.AsyncClient
) -> None:
    services = sim.services
    first, second = await two_albums(sim)
    response = await client.get("/api/status")
    assert response.json()["state"] == "idle" and response.json()["view_only"] is False
    current = await client.get("/api/runs/current")
    assert current.json() == {"run": None, "queue": [], "current_tracks": []}
    assert_response(current, "/api/runs/current")

    response = await client.post("/api/runs", json={})
    assert response.status_code == 202
    assert_response(response, "/api/runs")
    run_id = response.json()["run_id"]
    assert response.json() == {"run_id": run_id, "started": True, "added": []}
    await until(sim, running_item(items, first))
    response = await client.get("/api/status")
    assert_response(response, "/api/status")
    status = response.json()
    assert (status["state"], status["view_only"], status["session_state"]) == (
        "running",
        True,
        "recording",
    )
    assert status["run"]["id"] == run_id and status["run"]["trigger"] == "run_now"
    assert status["item"]["item_id"] == first and status["item"]["state"] == "playing"
    assert status["item"]["expect"] == {"kind": "tracks", "count": 2}  # planned, once known
    assert services.runs.recorder_pid() == 4242
    response = await client.get("/api/runs/current")
    assert_response(response, "/api/runs/current")
    queue = response.json()["queue"]
    assert [(q["item_id"], q["state"]) for q in queue] == [(first, "playing"), (second, "up_next")]
    assert queue[1]["expect"] == {"kind": "tracks", "count": 3}  # nothing recorded yet
    hello = await services.bus.snapshot()
    assert hello["status"]["state"] == "running"

    await until(sim, state_is(services, "finishing"))
    assert (await services.runs.status()).item.state == "finishing"  # type: ignore[union-attr]
    await until(sim, running_item(items, second))
    response = await client.get("/api/runs/current")
    queue = response.json()["queue"]
    assert [(q["item_id"], q["state"]) for q in queue] == [(first, "done"), (second, "playing")]
    assert queue[0]["counts"] == {"recorded": 2, "skipped": 1, "failed": 0}
    await until(sim, idle(services))
    assert (await client.get("/api/status")).json()["state"] == "idle"


async def test_events_run_state_queue_item_state_finished(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    album = await one_album(sim)
    run_id = await start(services)
    await until(sim, idle(services))
    run_states = sim.events_of("run.state")
    transitions = [(e["previous_state"], e["state"]) for e in run_states]
    changes = [t for t in transitions if t[0] != t[1]]
    assert changes == [
        ("idle", "starting"),
        ("starting", "running"),
        ("running", "finishing"),
        ("finishing", "running"),
        ("running", "idle"),
    ]
    for event in run_states:
        assert_schema("RunSummary", {k: v for k, v in event.items() if k != "previous_state"})
    last = run_states[-1]
    assert last["counters"]["recorded"] == 2 and last["id"] == run_id
    item_states = [(e["previous_state"], e["item"]["state"]) for e in sim.events_of("item.state")]
    assert item_states == [
        ("up_next", "planning"),
        ("planning", "preflight"),
        ("preflight", "preparing"),
        ("preparing", "starting"),
        ("starting", "playing"),
        ("playing", "finishing"),
        ("finishing", "done"),
    ]
    for event in sim.events_of("item.state"):
        assert event["run_id"] == run_id
        assert_schema("QueueItem", event["item"])
    queues = sim.events_of("run.queue")
    assert len(queues) == 1 and [q["item_id"] for q in queues[0]["queue"]] == [album]
    for queue_item in queues[0]["queue"]:
        assert_schema("QueueItem", queue_item)
    finished = sim.events_of("run.finished")
    assert [f["run"]["id"] for f in finished] == [run_id]
    assert_schema("HistoryRow", finished[0]["run"])
    # The last run.state (idle) comes right before run.finished.
    types = [e.type for e in sim.events if e.type in ("run.state", "run.finished")]
    assert types[-2:] == ["run.state", "run.finished"]
    assert sim.events_of("album.item") != []  # the album's progress


async def test_idle_only_once_run_finished_is_out(
    sim: Sim, items: ScriptedItems, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The engine is idle (what SIGTERM and `idle()` wait for) only once run.finished is out.
    `active()` is None before that, while History's row is read for it."""
    services = sim.services
    await one_album(sim)
    read = services.history.history_row
    held = asyncio.Event()

    async def history_row(run_id: int) -> HistoryRow:
        await held.wait()  # a slow store
        return await read(run_id)

    monkeypatch.setattr(services.history, "history_row", history_row)
    run_id = await start(services)
    try:
        await until(sim, lambda: services.runs.active() is None)
        assert not idle(services)()
        assert sim.events_of("run.finished") == []
    finally:
        held.set()  # else the run's end keeps the engine's lock, and teardown waits forever
    await until(sim, idle(services))
    assert [f["run"]["id"] for f in sim.events_of("run.finished")] == [run_id]


async def test_counters_are_sent_at_most_once_a_second(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    album = await one_album(sim)
    items.script(album, Script(until_stopped=True))
    await start(services)
    await until(sim, running_item(items, album))
    engine = items.engines[0]
    await sim.clock.advance(2)  # a held run.state goes out, then a second passes
    before = len(sim.events_of("run.state"))
    for recorded in range(1, 6):
        await services.runs.item_counts(engine.job, TrackCounts(recorded=recorded))
    sent = sim.events_of("run.state")[before:]
    assert [e["counters"]["recorded"] for e in sent] == [1]
    await sim.clock.advance(1.5)
    await asyncio.sleep(0.01)
    sent = sim.events_of("run.state")[before:]
    assert [e["counters"]["recorded"] for e in sent] == [1, 5]
    await services.runs.stop("now")
    await until(sim, idle(services))


async def test_set_run_active_follows_the_run_failures_included(
    sim: Sim, items: ScriptedItems
) -> None:
    services = sim.services
    album = await one_album(sim)
    items.script(album, Script(play_s=60))
    await start(services)
    assert not (await services.client.status()).restartable
    with pytest.raises(Exception, match="run_active"):
        await services.client.restart()
    await until(sim, idle(services))
    assert (await services.client.status()).restartable

    sim.world.client.set_pref("audio.normalize_v2", "true")  # the pre-run check fails
    await start(services)
    assert not (await services.client.status()).restartable
    await until(sim, idle(services))
    assert (await services.client.status()).restartable
    restartable = [e["restartable"] for e in sim.events_of("client.status")]
    assert restartable[-4:] == [False, True, False, True]
    assert (await services.store.fetchval("SELECT count(*) FROM runs WHERE state <> 'ended'")) == 0


# --- Start-up recovery and SIGTERM -------------------------------------------------------------


async def test_start_up_recovery_fails_unfinished_runs(
    running_app: FastAPI, services: Services, config: Config
) -> None:
    store = services.store
    await store.execute(
        "INSERT INTO items (id, kind, uri, name, tracked, added_by, added_at, artist, total) "
        "VALUES ('liked', 'liked', 'spotify:user:u:collection', 'Liked Songs', 1, 'auto', "
        "'2026-11-01T00:00:00.000Z', NULL, NULL), "
        "('4glBZ0bZMgkmFyi6TD4h69', 'album', 'spotify:album:4glBZ0bZMgkmFyi6TD4h69', "
        "'Elsewhere', 1, 'user', '2026-11-01T00:00:00.000Z', 'fakename', 5)"
    )
    run_id = (
        await store.execute(
            "INSERT INTO runs (kind, trigger, state, started_at, recorded, skipped_duplicate, "
            "skipped_other, failed, bytes_added) VALUES ('run', 'scheduled', 'running', "
            "'2026-11-15T01:00:00.000Z', 0, 0, 0, 0, 0)"
        )
    ).lastrowid
    current = (
        await store.execute(
            "INSERT INTO run_items (run_id, item_id, queue_pos, ran_order, state, recorded, "
            "skipped, skipped_other, bytes, started_at) VALUES (?, 'liked', 1, 1, 'playing', 3, "
            "2, 1, 3000, '2026-11-15T01:00:05.000Z')",
            (run_id,),
        )
    ).lastrowid
    await store.execute(
        "INSERT INTO run_items (run_id, item_id, queue_pos, state) "
        "VALUES (?, '4glBZ0bZMgkmFyi6TD4h69', 2, 'up_next')",
        (run_id,),
    )
    await store.execute(
        "INSERT INTO track_results (run_item_id, take_id, artist, title, planned, started_at) "
        "VALUES (?, 't1', 'a', 'b', 1, '2026-11-15T01:42:10.000Z')",
        (current,),
    )
    world = world_of(services.ports)
    world.recorder.orphans = 2
    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    (config.runtime_dir / "spytify-7-1.sock").write_text("")
    (config.runtime_dir / "other.sock").write_text("")

    result = await recover(services)
    assert (result.runs_failed, result.orphans_killed, result.sockets_removed) == (1, 2, 1)
    assert (config.runtime_dir / "other.sock").exists()
    run = await store.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
    assert (run["state"], run["outcome"], run["reason"]) == (
        "ended",
        "failed",
        "container_restarted",
    )
    assert run["ended_at"] == "2026-11-15T01:42:10.000Z"  # its last activity, not now
    assert (run["recorded"], run["skipped_duplicate"], run["skipped_other"]) == (3, 1, 1)
    rows = {
        row["item_id"]: row
        for row in await store.fetchall("SELECT * FROM run_items WHERE run_id = ?", (run_id,))
    }
    liked = rows["liked"]
    assert (liked["state"], liked["interrupted_by"], liked["interrupted_count"]) == (
        "interrupted",
        "shutdown",
        1,
    )
    assert rows["4glBZ0bZMgkmFyi6TD4h69"]["state"] == "stopped"
    take = await store.fetchone("SELECT result, reason FROM track_results")
    assert (take["result"], take["reason"]) == ("failed", "interrupted")
    again = await recover(services)
    assert again.runs_failed == 0


async def test_recovery_pauses_a_playing_player(sim: Sim) -> None:
    album = await one_album(sim)
    sim.world.player.load(f"spotify:album:{album}", play=True)
    result = await recover(sim.services)
    assert result.player_paused and sim.world.player.status == "Paused"
    assert (await recover(sim.services)).player_paused is False


async def test_sigterm_interrupts_the_item_within_40_s(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    first, second = await two_albums(sim)
    items.script(first, Script(until_stopped=True))
    run_id = await start(services)
    await until(sim, running_item(items, first))
    stopping = asyncio.ensure_future(services.runs.shutdown())
    took = await sim.advance_until(stopping.done, within=60)
    await stopping
    assert took <= 40
    assert items.engines[0].control.stop == StopRequest("now", "shutdown")
    rows = await run_items(services, run_id)
    assert (rows[first]["state"], rows[first]["interrupted_by"]) == ("interrupted", "shutdown")
    assert rows[second]["state"] == "stopped"
    run = await run_row(services, run_id)
    assert (run["outcome"], run["reason"]) == ("failed", "container_restarted")
    assert services.runs.active() is None
    assert sim.events_of("run.state")[-1]["state"] == "idle"


async def test_sigterm_past_the_bound_repairs_the_run(sim: Sim, items: ScriptedItems) -> None:
    services = sim.services
    first, _ = await two_albums(sim)
    items.script(first, Script(ignore_stop=True))
    run_id = await start(services)
    await until(sim, running_item(items, first))
    stopping = asyncio.ensure_future(services.runs.shutdown())
    took = await sim.advance_until(stopping.done, within=60)
    await stopping
    assert 40 <= took <= 50  # the bound, then the repair (the store works in real time)
    run = await run_row(services, run_id)
    assert (run["state"], run["outcome"], run["reason"]) == (
        "ended",
        "failed",
        "container_restarted",
    )
    rows = await run_items(services, run_id)
    assert rows[first]["state"] == "interrupted"
    assert services.runs.active() is None
    assert sim.events_of("run.state")[-1]["state"] == "idle"


# --- The run's own time left (RunSummary.time_left) --------------------------------------------


@dataclass
class Albums:
    """Albums in Albums, in this order, by different artists (Spytify's key is the first artist
    and the title, so one artist's "Track 1" on two albums would be one track)."""

    first: str  # 100 s + 200 s
    second: str  # 50 s
    third: str  # 3 × 30 s


async def albums_of_known_length(sim: Sim) -> Albums:
    first = sim.album("First", [("F1", 100_000), ("F2", 200_000)], artist="Ann")
    second = sim.album("Second", [("S1", 50_000)], artist="Bob")
    third = sim.album("Third", [("T1", 30_000), ("T2", 30_000), ("T3", 30_000)], artist="Cat")
    await sim.refresh()
    for n, album in enumerate((first, second, third), start=1):
        await sim.add_album(album)
        await sim.services.store.execute(
            "UPDATE items SET added_at = ? WHERE id = ?",
            (f"2026-09-0{n}T00:00:00.000Z", album.album.id),
        )
    await sim.track("liked", False)
    return Albums(first.album.id, second.album.id, third.album.id)


async def flushed(sim: Sim) -> None:
    """Lets a `run.state` the counters' second held back go out, and the reader catch up."""
    await sim.clock.advance(1.5)
    await asyncio.sleep(0.01)
    await settle(sim)


def time_left_of(sim: Sim) -> dict[str, Any] | None:
    """The time left in the last `run.state`."""
    return sim.events_of("run.state")[-1]["time_left"]


def seconds_left(sim: Sim) -> int | None:
    left = time_left_of(sim)
    return left["seconds"] if left is not None else None


# How far what the UI shows may be from what's really left. A new time left goes out once its
# whole seconds moved 5 s from the count-down (events.md), and rounding to whole seconds can
# hide up to half a second more.
SHOWN_WITHIN_S = run_module.TIME_LEFT_SLACK_S + 0.5


def shown_now(sim: Sim) -> float:
    """What the UI shows now: the last time left, counted down from its as_of."""
    left = time_left_of(sim)
    assert left is not None
    return left["seconds"] - (sim.clock.now() - parse_iso(left["as_of"])).total_seconds()


async def test_the_time_left_is_this_runs_queue_not_the_backlog(
    sim: Sim, items: ScriptedItems, client: httpx.AsyncClient
) -> None:
    """The current item before its plan is known counts its missing tracks as stored; each
    waiting item adds its own and 35 s; a followed playlist that plays whole is of unknown
    length. An album not in this run is the backlog's, not the run's."""
    services = sim.services
    albums = await albums_of_known_length(sim)
    followed = sim.playlist("Theirs", tracks=4, access="followed")
    await sim.refresh()
    await sim.add_playlist(followed)
    await services.settings.set_value("run_order", ["albums", "playlists", "liked", "carried_over"])
    items.script(albums.first, Script(until_stopped=True))
    run_id = await start(services, [albums.first, albums.second, followed.playlist.id])
    await until(sim, running_item(items, albums.first))
    await flushed(sim)
    expected = {"seconds": 300 + 50 + 35, "unknown_items": 1}
    left = time_left_of(sim)
    assert left is not None and {k: left[k] for k in expected} == expected
    backlog = await services.backlog.update()
    assert backlog.seconds_left >= 300 + 35 + 50 + 35 + 90 + 35  # the third album too
    # The same figure in the REST answers as in the last run.state.
    current = await client.get("/api/runs/current")
    assert_response(current, "/api/runs/current")
    assert current.json()["run"]["time_left"] == left
    status = await client.get("/api/status")
    assert_response(status, "/api/status")
    assert status.json()["run"]["time_left"] == left
    await services.runs.stop("now")
    await until(sim, idle(services))
    assert time_left_of(sim) is None  # the last run.state: the run has ended
    assert (await run_row(services, run_id))["outcome"] == "stopped"


async def test_the_time_left_counts_the_current_take_and_plan_then_the_stops(
    sim: Sim, items: ScriptedItems, client: httpx.AsyncClient
) -> None:
    """Once planned, the current item counts the rest of its take and its planned tracks not
    started (the item engine's ItemLive.left). Stop after this track: just the take. Stop now:
    nothing."""
    services = sim.services
    albums = await albums_of_known_length(sim)
    left = ItemLeft(
        take_ms=61_200,
        take_key="ann\x1ff1",
        tracks=(MissingTrack(key="ann\x1ff2", duration_ms=200_000),),
    )
    items.script(albums.first, Script(until_stopped=True, left=left))
    await start(services, [albums.first, albums.second])
    await until(sim, running_item(items, albums.first))
    await flushed(sim)
    assert seconds_left(sim) == 61 + 200 + 50 + 35  # 61.2 s rounds to 61
    assert time_left_of(sim)["unknown_items"] == 0  # type: ignore[index]
    await services.runs.stop("after_track")
    await settle(sim)
    assert time_left_of(sim)["seconds"] == 61  # type: ignore[index]
    response = await client.get("/api/runs/current")
    assert response.json()["run"]["time_left"]["seconds"] == 61
    await services.runs.stop("now")
    await settle(sim)
    stopped = time_left_of(sim)
    assert stopped is not None and (stopped["seconds"], stopped["unknown_items"]) == (0, 0)
    await until(sim, idle(services))


async def test_the_time_left_keeps_an_interrupted_item_and_drops_a_removed_one(
    sim: Sim, items: ScriptedItems
) -> None:
    services = sim.services
    albums = await albums_of_known_length(sim)
    items.script(albums.first, Script(outcome="interrupted", interrupted_by="stall"), Script())
    items.script(albums.second, Script(until_stopped=True))
    await start(services, [albums.first, albums.second, albums.third])
    await until(sim, running_item(items, albums.second))
    await flushed(sim)
    # The second album records; the third waits, and the first will retry at the end.
    assert seconds_left(sim) == 50 + (90 + 35) + (300 + 35)
    before = len(sim.events_of("run.state"))
    await sim.clock.advance(2)  # out of the counters' second
    await services.runs.remove_queued(albums.third)
    await settle(sim)
    sent = sim.events_of("run.state")[before:]
    assert [e["time_left"]["seconds"] for e in sent] == [50 + 300 + 35]
    await services.runs.stop("now")
    await until(sim, idle(services))


async def test_the_time_left_is_null_while_starting_and_stands_still_while_paused(
    sim: Sim, items: ScriptedItems
) -> None:
    services = sim.services
    albums = await albums_of_known_length(sim)
    takeover = Script(outcome="interrupted", interrupted_by="takeover")
    items.script(albums.first, takeover, Script(until_stopped=True))
    await start(services, [albums.first, albums.second])
    status = await services.runs.status()
    assert status.run is not None and status.run.time_left is None  # the queue isn't built
    await settle(sim)
    assert [e["time_left"] for e in sim.events_of("run.state")] == [None]
    await until(sim, state_is(services, "paused"))
    await settle(sim)
    paused = time_left_of(sim)
    # What the run records once resumed: the first album runs again, so it counts whole, with
    # its 35 s, though the scripted item played 10 s of it before the takeover.
    assert paused is not None and paused["seconds"] == (300 + 35) + (50 + 35)
    paused_at = parse_iso(paused["as_of"])
    await sim.clock.advance(300)
    status = await services.runs.status()
    assert status.run is not None and status.run.time_left is not None
    assert status.run.time_left.model_dump(mode="json") == paused  # stands still
    # Resume: worked out again, to the same figure.
    await services.runs.resume()
    await settle(sim)
    resumed = time_left_of(sim)
    assert resumed is not None and resumed["seconds"] == (300 + 35) + (50 + 35)
    assert parse_iso(resumed["as_of"]) > paused_at
    await services.runs.stop("now")
    await until(sim, idle(services))


async def test_a_new_time_left_goes_out_only_when_it_moved() -> None:
    """Worked out again often (each take's end, each phase), sent only when it moved 5 s or more
    from its count-down, or its unknown items changed."""
    at = parse_iso("2026-11-15T00:00:00.000Z")

    def left(seconds: int, after_s: float = 0, unknown: int = 0) -> RunTimeLeft:
        return RunTimeLeft(
            seconds=seconds, unknown_items=unknown, as_of=at + timedelta(seconds=after_s)
        )

    moved = run_module._time_left_moved
    assert not moved(None, None)
    assert moved(None, left(300)) and moved(left(300), None)
    assert not moved(left(300), left(240, after_s=60))  # just the count-down
    assert not moved(left(300), left(244, after_s=60))  # 4 s off
    assert moved(left(300), left(245, after_s=60))  # 5 s off: a jump, a skip, a stall
    assert moved(left(300), left(300, after_s=60))  # stood still (a stall)
    assert moved(left(300), left(240, after_s=60, unknown=1))
    assert not moved(left(10), left(0, after_s=60))  # counted down to 0, never under


async def test_the_time_left_follows_the_queue_while_paused(sim: Sim, items: ScriptedItems) -> None:
    """Paused (D6 at the start here), the figure stands still, but a change to the queue works
    it out again and sends it at once (no item runs, so nothing would send a held one): a
    removed item takes its tracks and its 35 s away, and one Back up now adds brings its own."""
    services = sim.services
    albums = await albums_of_known_length(sim)
    sim.world.player.play_elsewhere("Pixel 9")
    await start(services, [albums.first, albums.second])
    await until(sim, state_is(services, "paused"))
    assert seconds_left(sim) == (300 + 35) + (50 + 35)
    await services.runs.remove_queued(albums.second)
    await settle(sim)
    assert seconds_left(sim) == 300 + 35
    created = await services.runs.create_run([albums.third])
    assert created.added == [albums.third]
    await settle(sim)
    assert seconds_left(sim) == (300 + 35) + (90 + 35)
    status = await services.runs.status()
    assert status.run is not None and status.run.time_left is not None
    assert status.run.time_left.model_dump(mode="json") == time_left_of(sim)
    await services.runs.stop("now")
    await until(sim, idle(services))


async def test_a_scheduled_runs_time_left_ends_with_its_window(
    sim: Sim, items: ScriptedItems
) -> None:
    """A scheduled run stops at its window's end, so its time left is at most what's left of
    the window, and nothing of unknown length runs past it. When the window grows, the figure
    is worked out again."""
    services = sim.services
    long = sim.album("Long", [(f"Part {n}", 600_000) for n in range(1, 19)], artist="Long Band")
    followed = sim.playlist("Theirs", tracks=4, access="followed")
    await sim.refresh()
    await sim.add_album(long)
    await sim.add_playlist(followed)
    await sim.track("liked", False)
    await services.settings.set_value("run_order", ["albums", "playlists", "liked", "carried_over"])
    items.script(long.album.id, Script(until_stopped=True))
    window = await scheduled_window(sim, hours=1)
    assert window.end is not None
    await services.runs.start_scheduled(window, trigger="scheduled")
    await until(sim, running_item(items, long.album.id))
    await flushed(sim)
    # 3 h of tracks and a followed playlist, in a window with less than an hour left.
    left = time_left_of(sim)
    assert left is not None and left["unknown_items"] == 0
    window_ms = (window.end - parse_iso(left["as_of"])) // timedelta(milliseconds=1)
    assert 0 < window_ms < 3_600_000 and left["seconds"] == (window_ms + 500) // 1000
    # The window grows to 6 h: the queue's own figure, and its playlist of unknown length.
    longer = await scheduled_window(sim, hours=6)
    await services.runs.set_window_end(longer.end)
    await settle(sim)
    left = time_left_of(sim)
    assert left is not None and (left["seconds"], left["unknown_items"]) == (18 * 600, 1)
    await services.runs.stop("now")
    await until(sim, idle(services))


# --- The real item engine (skipped until engine-item is built) ---------------------------------


@needs_item_engine
async def test_run_now_records_an_album_end_to_end(sim: Sim) -> None:
    services = sim.services
    use_history_rows(services)
    album = sim.elsewhere()
    await sim.refresh()
    await sim.add_album(album)
    await sim.track("liked", False)
    sim.prerecord(album, [0, 2])
    run_id = await start(services)
    await until(sim, idle(services), within=1800)
    rows = await run_items(services, run_id)
    row = rows[album.album.id]
    assert (row["state"], row["recorded"], row["planned"]) == ("done", 3, 3)
    run = await run_row(services, run_id)
    assert (run["outcome"], run["recorded"]) == ("completed", 3)
    assert len(sim.recorded_titles(album)) == 5


@needs_item_engine
async def test_a_real_takeover_pauses_and_resume_finishes(sim: Sim) -> None:
    services = sim.services
    use_history_rows(services)
    album = sim.elsewhere()
    await sim.refresh()
    await sim.add_album(album)
    await sim.track("liked", False)
    run_id = await start(services)
    await until(sim, lambda: bool(sim.events_of("track.started")))
    sim.take_over_at(20)
    await until(sim, state_is(services, "paused"), within=600)
    assert sim.events_of("device.moved")[-1]["item_id"] == album.album.id
    await services.runs.resume()
    await until(sim, idle(services), within=1800)
    row = (await run_items(services, run_id))[album.album.id]
    assert (row["state"], row["attempt"]) == ("done", 2)
    assert len(sim.recorded_titles(album)) == 5


async def assert_cut_take_skipped(services: Services, run_id: int, album: str) -> None:
    """The take a stop cut (Stop now or SIGTERM) is skipped `discarded`: counted under the run's
    and the item's skipped_other, never failed, so History has nothing to retry and the Last run
    card no issue."""
    take = await services.store.fetchone(
        "SELECT tr.result, tr.reason FROM track_results tr "
        "JOIN run_items ri ON ri.id = tr.run_item_id WHERE ri.run_id = ? AND tr.planned = 1",
        (run_id,),
    )
    assert (take["result"], take["reason"]) == ("skipped", "discarded")
    run = await run_row(services, run_id)
    assert (run["skipped_other"], run["failed"]) == (1, 0)
    row = (await run_items(services, run_id))[album]
    assert (row["skipped"], row["skipped_other"], row["failed"]) == (1, 1, 0)
    detail = await services.history.run(run_id)
    [item] = [i for i in detail.items if i.item_id == album]
    assert (item.counts.skipped, item.counts.failed, item.can_retry) == (1, 0, False)
    assert (await services.history.last_run()).issues == []


@needs_item_engine
async def test_a_real_stop_now_counts_the_cut_take_as_skipped(sim: Sim) -> None:
    services = sim.services
    use_history_rows(services)
    album = await one_album(sim)
    run_id = await start(services)
    await until(sim, lambda: bool(sim.events_of("track.started")))
    await sim.clock.advance(20)  # Passage (90 s) is recording
    await services.runs.stop("now")
    await until(sim, idle(services), within=600)
    run = await run_row(services, run_id)
    assert run["outcome"] == "stopped"
    assert (await run_items(services, run_id))[album]["state"] == "stopped"
    await assert_cut_take_skipped(services, run_id, album)
    # The live counters said so before the run ended: Skipped 1, Failed 0.
    counters = [e["counters"] for e in sim.events_of("run.state") if e["state"] == "stopping"]
    assert counters[-1]["skipped_other"] == 1 and counters[-1]["failed"] == 0


@needs_item_engine
async def test_a_real_shutdown_counts_the_cut_take_as_skipped(sim: Sim) -> None:
    services = sim.services
    use_history_rows(services)
    album = await one_album(sim)
    run_id = await start(services)
    await until(sim, lambda: bool(sim.events_of("track.started")))
    await sim.clock.advance(20)  # Passage (90 s) is recording
    stopping = asyncio.ensure_future(services.runs.shutdown())
    assert await sim.advance_until(stopping.done, within=60) <= 40
    await stopping
    run = await run_row(services, run_id)
    assert (run["outcome"], run["reason"]) == ("failed", "container_restarted")
    row = (await run_items(services, run_id))[album]
    assert (row["state"], row["interrupted_by"]) == ("interrupted", "shutdown")
    await assert_cut_take_skipped(services, run_id, album)


@needs_item_engine
async def test_a_real_d6_start_resumes_with_a_single_pause(sim: Sim) -> None:
    """D6 as before: the phone playing at the start pauses the run, and nothing touches the
    player. Resume pauses the phone; the item then finds nothing playing, so preparing doesn't
    pause again (Spotify would answer 403), and the item records on our device."""
    services = sim.services
    use_history_rows(services)
    album = sim.elsewhere()
    await sim.refresh()
    await sim.add_album(album)
    await sim.track("liked", False)
    sim.prerecord(album, [0, 1, 2, 3])
    sim.world.player.play_elsewhere("Pixel 9")
    run_id = await start(services)
    await until(sim, state_is(services, "paused"))
    active = services.runs.active()
    assert active is not None and active.paused_reason == "device_busy"
    assert [c for c in sim.webapi_calls() if c.startswith("PUT")] == []
    await services.runs.resume()
    await until(sim, idle(services), within=1800)
    assert (await run_items(services, run_id))[album.album.id]["state"] == "done"
    puts = [c for c in sim.webapi_calls() if c.startswith("PUT")]
    assert puts[: puts.index("PUT /me/player/play")] == [
        "PUT /me/player/pause",  # Resume's, to the phone
        "PUT /me/player/seek",
        "PUT /me/player/shuffle",
        "PUT /me/player/repeat",
    ]


@needs_item_engine
async def test_a_real_runs_time_left_counts_its_own_tracks_down(
    sim: Sim, client: httpx.AsyncClient
) -> None:
    """Elsewhere with tracks 1 and 3 recorded: Distant Peak (90 s), Seaside Stillness (93 s) and
    Last Hours (88 s) to record, 271 s."""
    services = sim.services
    use_history_rows(services)
    album = sim.elsewhere()
    await sim.refresh()
    await sim.add_album(album)
    await sim.track("liked", False)
    sim.prerecord(album, [0, 2])
    await start(services)
    await until(sim, state_is(services, "running"))
    assert seconds_left(sim) == 271 + 35  # waiting: its stored tracks and 35 s
    await until(sim, lambda: bool(sim.events_of("track.started")))
    playing = (await services.runs.status()).track
    assert playing is not None and playing.title == "Distant Peak"

    def truth() -> float:  # the rest of Distant Peak, then the two others
        return 271 - (sim.clock.now() - playing.started_at).total_seconds()

    # The current item, planned: its own tracks, without the 35 s. The UI counts the last figure
    # down, within a few seconds of what's really left. The figure itself isn't always 271:
    # `until` moves the clock while the item engine waits on the store, so it can take the
    # take's start in a second or two late, and then sends 270 or 269.
    assert abs(shown_now(sim) - truth()) < SHOWN_WITHIN_S
    await sim.clock.advance(60)
    left = time_left_of(sim)
    still = (await services.runs.status()).track
    assert still is not None and still.take_id == playing.take_id
    assert abs(shown_now(sim) - truth()) < SHOWN_WITHIN_S
    response = await client.get("/api/runs/current")
    assert response.json()["run"]["time_left"] == left
    await until(sim, state_is(services, "finishing"), within=1800)
    assert seconds_left(sim) == 0  # playback is over
    await until(sim, idle(services), within=1800)
    assert time_left_of(sim) is None
    # Sent at changes, not every second: a handful over the run's ~5 minutes.
    sent = [e["time_left"] for e in sim.events_of("run.state")]
    assert len(sent) < 20


@needs_item_engine
async def test_a_real_runs_time_left_doesnt_count_again_what_it_recorded(sim: Sim) -> None:
    """Elsewhere, then a Deluxe copy with the same five tracks (the same artist and titles, so
    the same Spytify keys): the copy will have nothing to record, though its list, read when the
    queue was built, has them all. The figure counts down with what's really left: the rest of
    the track playing and Elsewhere's tracks after it, then nothing once it's finishing."""
    services = sim.services
    album = sim.elsewhere()
    deluxe = sim.album("Elsewhere (Deluxe)", ELSEWHERE, artist=ELSEWHERE_ARTIST)
    await sim.refresh()
    for n, saved in enumerate((album, deluxe), start=1):
        await sim.add_album(saved)
        await services.store.execute(
            "UPDATE items SET added_at = ? WHERE id = ?",
            (f"2026-09-0{n}T00:00:00.000Z", saved.album.id),
        )
    await sim.track("liked", False)
    await start(services)
    await until(sim, lambda: bool(sim.events_of("track.started")))
    lengths_s = {title: ms / 1000 for title, ms in ELSEWHERE}
    order = [title for title, _ in ELSEWHERE]
    checks = 0
    while True:
        await sim.clock.advance(5)
        await asyncio.sleep(0.001)
        await settle(sim)
        status = await services.runs.status()
        if status.item is None or status.item.item_id != album.album.id:
            break  # Elsewhere is over
        if status.item.state == "finishing":
            truth = 0.0
        elif status.track is not None:
            played = (sim.clock.now() - status.track.started_at).total_seconds()
            later = order[order.index(status.track.title) + 1 :]
            truth = max(0.0, lengths_s[status.track.title] - played)
            truth += sum(lengths_s[title] for title in later)
        else:
            continue
        shown = max(0.0, shown_now(sim))
        assert abs(shown - truth) < SHOWN_WITHIN_S, (status.track, status.item.state, shown)
        checks += 1
    assert checks > 80  # Elsewhere's 460 s and its finishing, every 5 s
    await until(sim, idle(services), within=600)
    # From Elsewhere's finishing on, through the switch to the copy, nothing was left.
    sent = sim.events_of("run.state")
    finishing = next(n for n, event in enumerate(sent) if event["state"] == "finishing")
    assert [event["time_left"] for event in sent[finishing:-1]] != []
    assert all(event["time_left"]["seconds"] == 0 for event in sent[finishing:-1])
    assert sim.recorded_titles(deluxe) == set(order)


@needs_item_engine
async def test_a_real_whole_items_first_take_counts_from_its_start(sim: Sim) -> None:
    """A followed playlist plays whole, then Elsewhere (460 s and 35 s). The whole item's
    length isn't known, but the take playing is: it counts from the moment it starts, not only
    once it ends."""
    services = sim.services
    catalog = sim.world.catalog
    entries = [catalog.entry(title, artist="Band", duration_ms=150_000) for title in ("A", "B")]
    playlist = sim.playlist("Theirs", entries, access="followed")
    album = sim.elsewhere()
    await sim.refresh()
    await sim.add_playlist(playlist)
    await sim.add_album(album)
    await sim.track("liked", False)
    await services.settings.set_value("run_order", ["playlists", "albums", "liked", "carried_over"])
    await start(services)
    await until(sim, lambda: bool(sim.events_of("track.started")))
    await sim.clock.advance(20)
    await settle(sim)
    playing = (await services.runs.status()).track
    assert playing is not None and playing.title == "A"
    left = time_left_of(sim)
    assert left is not None and left["unknown_items"] == 1  # the playlist plays whole
    truth = 150 - (sim.clock.now() - playing.started_at).total_seconds() + 460 + 35
    assert abs(shown_now(sim) - truth) < SHOWN_WITHIN_S
    await services.runs.stop("now")
    await until(sim, idle(services), within=600)


@pytest.fixture
def demo(config: Config, fake_clock: FakeClock) -> tuple[Services, FastAPI]:
    """The dev server's demo scenario on the fake clock. Built outside the event loop: building
    the app takes longer than a callback may."""
    services = build_services(config, clock=fake_clock)
    services.ports = build_fake_ports(config, fake_clock, scenario="demo")
    return services, create_app(services)


async def setup_completed(services: Services) -> None:
    """Waits for fake/demo.py's background task to complete the demo's setup."""
    for _ in range(500):
        if await services.setup.is_complete():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the demo's setup wasn't completed")


async def test_the_demo_is_set_up_for_run_now(demo: tuple[Services, FastAPI]) -> None:
    services, app = demo
    async with app.router.lifespan_context(app):
        await setup_completed(services)
        assert await services.connection.held_reason() is None
        status = await services.client.status()
        assert status.installed and status.logged_in
        assert await services.client.drifted_rows() == []
        assert (await services.setup.snapshot()).tos_acknowledged_at is not None


@needs_item_engine
@pytest.mark.allow_slow_callbacks  # the fixtures library's catalog refresh (S5) is large
async def test_a_whole_demo_run_in_fake_mode(
    demo: tuple[Services, FastAPI], fake_clock: FakeClock
) -> None:
    """The dev server's demo (`python -m spotivault --fake`): set up at start-up, Run now on
    one of the account's playlists records what's missing end to end. All but two of its
    tracks are recorded already, to keep the test short."""
    services, app = demo
    world = world_of(services.ports)
    world.recorder.level_interval_s = None  # the meter: 10 events a second
    async with app.router.lifespan_context(app):
        await setup_completed(services)
        await services.catalog.refresh(trigger="setup")
        row = await services.store.fetchone(
            "SELECT id FROM items WHERE kind = 'owned' AND tracked = 1 AND total > 2 "
            "ORDER BY total LIMIT 1"
        )
        assert row is not None
        playlist = next(p for p in world.catalog.library_playlists() if p.playlist.id == row["id"])
        playable = [i for i, entry in enumerate(playlist.entries) if entry.playable]
        Sim(services).prerecord(playlist, playable[:-2])
        created = await services.runs.create_run([row["id"]])
        end = fake_clock.monotonic() + 3600
        while services.runs.active() is not None:
            assert fake_clock.monotonic() < end
            await fake_clock.advance(5.0)  # every timer in between still runs on time
            await asyncio.sleep(0.001)
        run = await services.store.fetchone("SELECT * FROM runs WHERE id = ?", (created.run_id,))
        assert run["outcome"] in ("completed", "completed_with_issues")
        assert run["recorded"] >= 1


# --- Odds and ends -----------------------------------------------------------------------------


def test_the_run_engine_is_its_item_engines_host(services: Services) -> None:
    engine = services.runs
    assert isinstance(engine, RunEngine)
    assert engine.make_item_engine is ItemEngine
    assert run_module.SHUTDOWN_BOUND_S == 40.0
    assert iso_ms(services.clock.now())  # the clock is the fake one
