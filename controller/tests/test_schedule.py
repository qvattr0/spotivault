"""schedule.py and the schedule endpoints: the grid, the windows, and the tick's rules.

Owner: schedule. The run engine and the history are other builders' (engine-run, history-files-
metrics), so these tests put doubles in their places: `FakeRuns` records the scheduler's calls and
writes the `runs` rows the real engine writes; `FakeHistory` builds a HistoryRow from the row.

The controller keeps Berlin time in this module. The nightly grid is Mon–Fri 01:00–07:00 and
Sat–Sun 00:00–09:00 (local time).
"""

import asyncio
import dataclasses
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI

from contract import CONTRACTS
from spotivault.api.models import HistoryRow, HistoryRowWindow, Hours, ScheduleUpdate
from spotivault.clock import iso_ms, parse_iso
from spotivault.engine.run import ActiveRun
from spotivault.fake.clock import FakeClock
from spotivault.services import Services
from spotivault.windows import DAYS, Window

BERLIN = ZoneInfo("Europe/Berlin")
PLAYLIST_ID = "ScheduleTestPlaylist12"  # 22 characters, as Spotify's ids are
ALBUM_ID = "ScheduleTestAlbum00012"

NIGHTLY = {
    "mon": [1, 2, 3, 4, 5, 6],
    "tue": [1, 2, 3, 4, 5, 6],
    "wed": [1, 2, 3, 4, 5, 6],
    "thu": [1, 2, 3, 4, 5, 6],
    "fri": [1, 2, 3, 4, 5, 6],
    "sat": list(range(0, 9)),
    "sun": list(range(0, 9)),
}
VECTORS = json.loads((CONTRACTS / "vectors" / "schedule-windows.json").read_text(encoding="utf-8"))


def berlin(text: str) -> datetime:
    """A wall-clock time in Berlin ("2026-11-16T01:00") as an aware UTC instant."""
    return datetime.fromisoformat(text).replace(tzinfo=BERLIN).astimezone(UTC)


def monday_window() -> Window:
    """Monday 16 Nov 2026, 01:00–07:00 Berlin: the nightly grid's window."""
    return Window(start=berlin("2026-11-16T01:00"), end=berlin("2026-11-16T07:00"))


def nightly_update() -> ScheduleUpdate:
    return ScheduleUpdate(hours=Hours.model_validate(NIGHTLY))


async def set_grid(services: Services, hours: dict[str, list[int]]) -> None:
    """Writes the grid straight to the table, as PUT does, without waking the tick. A test that
    calls tick() itself mustn't race the watch task."""
    rows = [(day, hour) for day, name in enumerate(DAYS) for hour in hours.get(name, [])]

    def write(conn: Any) -> None:
        conn.execute("DELETE FROM schedule_hours")
        conn.executemany("INSERT INTO schedule_hours (day, hour) VALUES (?, ?)", rows)

    await services.store.transaction(write)


async def set_seen_at(services: Services, moment: datetime) -> None:
    """Sets the meta row the tick writes: when it last ran."""
    await services.store.execute(
        "INSERT INTO meta (key, value, updated_at) VALUES ('scheduler_seen_at', ?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (iso_ms(moment), iso_ms(moment)),
    )


async def track_playlist(services: Services) -> None:
    """A tracked playlist, which a window has something to record for."""
    await services.store.execute(
        "INSERT INTO items (id, kind, uri, name, tracked, added_by, added_at) "
        "VALUES (?, 'owned', ?, 'Test list', 1, 'user', ?) ON CONFLICT (id) DO NOTHING",
        (PLAYLIST_ID, f"spotify:playlist:{PLAYLIST_ID}", iso_ms(services.clock.now())),
    )


async def add_queued_album(services: Services) -> None:
    """An album on the Albums page that has never been recorded: Queued."""
    await services.store.execute(
        "INSERT INTO items (id, kind, uri, name, artist, tracked, added_by, added_at, item_access, "
        "total) VALUES (?, 'album', ?, 'Test album', 'Test artist', 1, 'user', ?, 1, 0)",
        (ALBUM_ID, f"spotify:album:{ALBUM_ID}", iso_ms(services.clock.now())),
    )


async def run_rows(services: Services) -> list[dict[str, Any]]:
    """Every `runs` row, oldest first, as plain dicts."""
    found = await services.store.fetchall("SELECT * FROM runs ORDER BY id")
    return [dict(row) for row in found]


async def rows_of_kind(services: Services, kind: str) -> list[dict[str, Any]]:
    return [row for row in await run_rows(services) if row["kind"] == kind]


class FakeRuns:
    """Stands in for engine-run's RunEngine: the scheduler's calls, recorded. `start_scheduled`
    writes the run's row as the real engine does, so the next tick sees the window taken."""

    def __init__(self, services: Services) -> None:
        self.services = services
        self.started: list[tuple[Window, str]] = []
        self.ended_windows = 0
        self.window_ends: list[datetime | None] = []  # set_window_end's calls
        self.current: ActiveRun | None = None
        self.closing = False

    def active(self) -> ActiveRun | None:
        return self.current

    async def start_scheduled(self, window: Window, *, trigger: str) -> int:
        self.started.append((window, trigger))
        return await self.start_run(trigger=trigger, window=window)

    async def start_run(self, *, trigger: str, window: Window | None = None) -> int:
        """A run going now: a forced one (no window) or a scheduled one."""
        now = iso_ms(self.services.clock.now())
        result = await self.services.store.execute(
            "INSERT INTO runs (kind, trigger, state, started_at, window_start, window_end) "
            "VALUES ('run', ?, 'running', ?, ?, ?)",
            (
                trigger,
                now,
                None if window is None else iso_ms(window.start),
                None if window is None or window.end is None else iso_ms(window.end),
            ),
        )
        assert result.lastrowid is not None
        self.current = ActiveRun(
            run_id=result.lastrowid,
            trigger=trigger,  # type: ignore[arg-type]
            state="running",
            paused_reason=None,
            window=window,
        )
        return result.lastrowid

    async def finish(self, outcome: str = "completed") -> None:
        """The going run ends, with this outcome, now."""
        assert self.current is not None
        now = iso_ms(self.services.clock.now())
        await self.services.store.execute(
            "UPDATE runs SET state = 'ended', outcome = ?, ended_at = ? WHERE id = ?",
            (outcome, now, self.current.run_id),
        )
        self.current = None

    def stopping(self) -> None:
        assert self.current is not None
        self.current = dataclasses.replace(self.current, state="stopping")

    def pause(self) -> None:
        assert self.current is not None
        self.current = dataclasses.replace(
            self.current, state="paused", paused_reason="device_moved"
        )

    async def end_window(self) -> None:
        self.ended_windows += 1
        if self.current is not None:
            self.current = dataclasses.replace(self.current, state="stopping")

    async def set_window_end(self, end: datetime | None) -> None:
        self.window_ends.append(end)
        if self.current is not None and self.current.window is not None:
            window = Window(start=self.current.window.start, end=end)
            self.current = dataclasses.replace(self.current, window=window)


class FakeHistory:
    """Stands in for history-files-metrics' HistoryService.history_row: the row's own columns."""

    def __init__(self, services: Services) -> None:
        self.services = services

    async def history_row(self, run_id: int) -> HistoryRow:
        row = await self.services.store.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
        if row is None:
            raise LookupError(run_id)
        window = None
        if row["window_start"] is not None and row["window_end"] is not None:
            window = HistoryRowWindow(
                start=parse_iso(row["window_start"]), end=parse_iso(row["window_end"])
            )
        return HistoryRow(
            id=row["id"],
            kind=row["kind"],
            trigger=row["trigger"],
            started_at=parse_iso(row["started_at"]),
            ended_at=None if row["ended_at"] is None else parse_iso(row["ended_at"]),
            duration_s=None,
            outcome=row["outcome"],
            counters=None,
            reason=row["reason"],
            window=window,
        )


def be_healthy(
    services: Services,
    monkeypatch: pytest.MonkeyPatch,
    *,
    setup: bool = True,
    connection: str | None = None,
    logged_in: bool = True,
    installed: bool = True,
    running: bool = True,
) -> None:
    """Setup, the connection and the client as the held checks read them. Each call replaces the
    last one's answers. A client that isn't running isn't logged in either (no window)."""

    async def is_complete() -> bool:
        return setup

    async def held_reason() -> str | None:
        return connection

    async def status() -> SimpleNamespace:
        return SimpleNamespace(
            installed=installed, running=running, logged_in=logged_in and running
        )

    monkeypatch.setattr(services.setup, "is_complete", is_complete)
    monkeypatch.setattr(services.connection, "held_reason", held_reason)
    monkeypatch.setattr(services.client, "status", status)


def spy_events(services: Services, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Records every event published, and still publishes it."""
    published: list[tuple[str, Any]] = []
    original = services.bus.publish

    def publish(type: str, data: Any) -> Any:
        published.append((type, data))
        return original(type, data)

    monkeypatch.setattr(services.bus, "publish", publish)
    return published


@dataclass
class Rig:
    services: Services
    clock: FakeClock
    runs: FakeRuns
    published: list[tuple[str, Any]]

    def finished(self) -> list[HistoryRow]:
        """The HistoryRows published as run.finished, in order."""
        return [data["run"] for kind, data in self.published if kind == "run.finished"]


@pytest.fixture
def env(env: dict[str, str]) -> dict[str, str]:
    """This module's controller keeps Berlin time."""
    return {**env, "TZ": "Europe/Berlin"}


async def let_the_watch_sleep(services: Services) -> None:
    """The watch task's first tick runs on the loop after start-up, and it can run during a
    test's own steps (it would start a run from the test's grid). Waits, in real time, until that
    tick is done and the task is about to sleep: nothing else of its touches the database then."""
    loop = asyncio.get_running_loop()
    give_up = loop.time() + 5
    while services.schedule.next_wake_at is None:
        if loop.time() > give_up:
            raise AssertionError("the watch task never got to its first sleep")
        await asyncio.sleep(0.005)


@pytest.fixture
async def rig(
    running_app: FastAPI,
    services: Services,
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Rig]:
    """A controller set up, connected and logged in, with the run engine and history doubled
    and the events recorded. The start-up hooks ran before the doubles went in: the grid was
    empty then, so they did nothing. The watch task is asleep before the test starts."""
    await let_the_watch_sleep(services)
    runs = FakeRuns(services)
    services.runs = runs  # type: ignore[assignment]
    services.history = FakeHistory(services)  # type: ignore[assignment]
    be_healthy(services, monkeypatch)
    yield Rig(services, fake_clock, runs, spy_events(services, monkeypatch))


# --- The grid and the endpoints ------------------------------------------------------------------


async def test_get_and_put_the_grid(
    services: Services, fake_clock: FakeClock, client: httpx.AsyncClient
) -> None:
    """PUT saves the grid and run_order in one go; `tz` is ignored; GET returns the same; a
    repeated hour or group is refused."""
    # Sunday noon in Berlin: no window is in progress, so the tick that the PUT wakes does nothing.
    fake_clock.set_now(berlin("2026-11-15T12:00"))
    body = {
        "hours": NIGHTLY,
        "tz": "Pacific/Auckland",
        "run_order": ["albums", "playlists", "liked", "carried_over"],
    }
    put = await client.put("/api/schedule", json=body)
    assert put.status_code == 200, put.text
    saved = put.json()
    assert saved["hours"] == NIGHTLY
    assert saved["tz"] == "Europe/Berlin"  # the zone the controller keeps, not the body's
    assert saved["run_order"] == ["albums", "playlists", "liked", "carried_over"]
    assert saved["windows_per_week"] == 7
    assert saved["hours_per_week"] == 48

    got = await client.get("/api/schedule")
    assert got.status_code == 200
    assert got.json() == saved

    # Without run_order, the stored order stays.
    again = await client.put("/api/schedule", json={"hours": {**NIGHTLY, "sun": []}})
    assert again.status_code == 200
    assert again.json()["run_order"] == ["albums", "playlists", "liked", "carried_over"]
    assert again.json()["hours_per_week"] == 39

    repeated = {**NIGHTLY, "mon": [1, 1, 2]}
    refused = await client.put("/api/schedule", json={"hours": repeated})
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "validation_failed"

    dup_order = await client.put(
        "/api/schedule",
        json={"hours": NIGHTLY, "run_order": ["liked", "liked", "albums", "playlists"]},
    )
    assert dup_order.status_code == 422
    assert services.config.tz == "Europe/Berlin"


async def test_the_default_run_order_and_the_empty_grid(rig: Rig) -> None:
    """A fresh grid is Manual only, with the default run order."""
    schedule = await rig.services.schedule.get()
    assert schedule.hours_per_week == 0
    assert schedule.windows_per_week == 0
    assert schedule.run_order == ["carried_over", "liked", "playlists", "albums"]


async def test_put_stops_a_run_when_its_current_hour_is_turned_off(rig: Rig) -> None:
    """Turning off the current hour during a scheduled run ends it after the track. Turning off
    another hour does nothing, and so does a forced run."""
    services = rig.services
    rig.clock.set_now(berlin("2026-11-16T02:00"))  # Monday 02:00, inside the 01–07 window
    await set_grid(services, NIGHTLY)
    await rig.runs.start_scheduled(monday_window(), trigger="scheduled")

    # Thursday 03:00 goes off: not the current hour.
    thursday_off = {**NIGHTLY, "thu": [1, 2, 4, 5, 6]}
    await services.schedule.put(ScheduleUpdate(hours=Hours.model_validate(thursday_off)))
    assert rig.runs.ended_windows == 0

    # Monday 02:00 goes off: the current hour, so the run stops after this track.
    monday_off = {**NIGHTLY, "mon": [1, 3, 4, 5, 6]}
    await services.schedule.put(ScheduleUpdate(hours=Hours.model_validate(monday_off)))
    assert rig.runs.ended_windows == 1


async def test_a_put_moves_the_end_of_the_running_window(rig: Rig) -> None:
    """Shortening the window in progress (Monday 01–07 → 01–04) moves where the run stops: the
    tick ends it at the new end, not at the end it started with."""
    services = rig.services
    rig.clock.set_now(berlin("2026-11-16T02:00"))
    await set_grid(services, NIGHTLY)
    await rig.runs.start_scheduled(monday_window(), trigger="scheduled")

    shorter = {**NIGHTLY, "mon": [1, 2, 3]}
    await services.schedule.put(ScheduleUpdate(hours=Hours.model_validate(shorter)))
    assert rig.runs.window_ends[-1] == berlin("2026-11-16T04:00")
    assert rig.runs.ended_windows == 0

    rig.clock.set_now(berlin("2026-11-16T03:59:59"))
    await services.schedule.tick()
    assert rig.runs.ended_windows == 0
    rig.clock.set_now(berlin("2026-11-16T04:00"))
    await services.schedule.tick()
    assert rig.runs.ended_windows == 1


async def test_a_put_that_splits_the_window_stops_at_the_gap(rig: Rig) -> None:
    services = rig.services
    rig.clock.set_now(berlin("2026-11-16T01:30"))
    await set_grid(services, NIGHTLY)
    await rig.runs.start_scheduled(monday_window(), trigger="scheduled")
    split = {**NIGHTLY, "mon": [1, 2, 4, 5, 6]}  # 03:00 off: 01–03, then 04–07
    await services.schedule.put(ScheduleUpdate(hours=Hours.model_validate(split)))
    assert rig.runs.window_ends[-1] == berlin("2026-11-16T03:00")
    rig.clock.set_now(berlin("2026-11-16T03:00"))
    await services.schedule.tick()
    assert rig.runs.ended_windows == 1


async def test_a_put_that_extends_the_window_lets_the_run_go_on(rig: Rig) -> None:
    services = rig.services
    rig.clock.set_now(berlin("2026-11-16T02:00"))
    await set_grid(services, NIGHTLY)
    await rig.runs.start_scheduled(monday_window(), trigger="scheduled")
    longer = {**NIGHTLY, "mon": [1, 2, 3, 4, 5, 6, 7]}  # 01–08
    await services.schedule.put(ScheduleUpdate(hours=Hours.model_validate(longer)))
    assert rig.runs.window_ends[-1] == berlin("2026-11-16T08:00")

    rig.clock.set_now(berlin("2026-11-16T07:00"))
    await services.schedule.tick()
    assert rig.runs.ended_windows == 0  # the old end passed: it goes on
    rig.clock.set_now(berlin("2026-11-16T08:00"))
    await services.schedule.tick()
    assert rig.runs.ended_windows == 1


async def test_schedule_next_and_its_held_reason_order(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-15T12:00"))  # Sunday noon: the next window is Monday's

    nxt = await services.schedule.next()
    assert nxt.at == berlin("2026-11-16T01:00")
    assert nxt.window_end == berlin("2026-11-16T07:00")
    assert nxt.in_progress is False
    assert nxt.playlists_to_check == 1
    assert nxt.albums_queued == 0
    assert nxt.held_reason is None

    await add_queued_album(services)
    assert (await services.schedule.next()).albums_queued == 1

    rig.clock.set_now(berlin("2026-11-15T02:00"))  # inside Sunday's window
    during = await services.schedule.next()
    assert during.in_progress is True
    assert during.at == berlin("2026-11-15T00:00")

    # The held reasons, the first that applies: setup, the connection, the client, the run.
    be_healthy(services, monkeypatch, setup=False, connection="not_connected")
    assert (await services.schedule.next()).held_reason == "setup_incomplete"
    be_healthy(services, monkeypatch, connection="connection_expired", logged_in=False)
    assert (await services.schedule.next()).held_reason == "connection_expired"
    be_healthy(services, monkeypatch, connection="not_connected", logged_in=False)
    assert (await services.schedule.next()).held_reason == "not_connected"
    be_healthy(services, monkeypatch, logged_in=False)
    assert (await services.schedule.next()).held_reason == "client_logged_out"
    be_healthy(services, monkeypatch)
    assert (await services.schedule.next()).held_reason is None
    await rig.runs.start_run(trigger="run_now")
    rig.runs.pause()
    assert (await services.schedule.next()).held_reason == "run_paused"


async def test_manual_only_has_no_next_window(rig: Rig) -> None:
    nxt = await rig.services.schedule.next()
    assert nxt.at is None
    assert nxt.window_end is None
    assert nxt.in_progress is False


# --- The vectors ----------------------------------------------------------------------------------


@pytest.mark.parametrize("case", VECTORS["cases"], ids=[c["id"] for c in VECTORS["cases"]])
async def test_every_schedule_windows_vector_case(rig: Rig, case: dict[str, Any]) -> None:
    """Each case's grid, in its zone and at its instant: the counts, the next window, and the
    tick (a window in progress starts one run; nothing else does). DST cases included."""
    services = rig.services
    given = case["input"]
    expected = case["expected"]
    services.config = dataclasses.replace(services.config, tz=given["tz"])
    try:
        await services.store.execute("DELETE FROM runs")
        rig.runs.current = None
        rig.runs.started.clear()
        await set_grid(services, given["hours"])
        await track_playlist(services)
        rig.clock.set_now(parse_iso(given["now"]))

        schedule = await services.schedule.get()
        assert schedule.windows_per_week == expected["windows_per_week"]
        assert schedule.hours_per_week == expected["hours_per_week"]

        nxt = await services.schedule.next()
        if not expected["next_windows"]:
            assert nxt.at is None
            assert nxt.in_progress is False
            await services.schedule.tick()
            assert rig.runs.started == []
            return
        first = expected["next_windows"][0]
        assert nxt.at == parse_iso(first["start"])
        assert nxt.in_progress is expected["in_window"]
        if first["end"] is None:
            assert nxt.window_end is None
        else:
            assert nxt.window_end == parse_iso(first["end"])

        await services.schedule.tick()
        if not expected["in_window"]:
            assert rig.runs.started == []
            return
        assert len(rig.runs.started) == 1
        window, trigger = rig.runs.started[0]
        assert trigger == "scheduled"
        if first["end"] is None:
            assert window.end is None  # a window that never ends is anchored at its week's start
        else:
            assert window.start == parse_iso(first["start"])
            assert window.end == parse_iso(first["end"])
    finally:
        services.config = dataclasses.replace(services.config, tz="Europe/Berlin")


# --- The tick -------------------------------------------------------------------------------------


async def test_a_window_start_starts_a_scheduled_run(rig: Rig) -> None:
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)

    rig.clock.set_now(berlin("2026-11-16T00:30"))
    await services.schedule.tick()
    assert rig.runs.started == []

    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()
    assert [(window, trigger) for window, trigger in rig.runs.started] == [
        (monday_window(), "scheduled")
    ]

    # The next tick, still inside the window, sees the run and starts nothing more.
    rig.clock.set_now(berlin("2026-11-16T01:05"))
    await services.schedule.tick()
    assert len(rig.runs.started) == 1


async def test_a_window_end_ends_the_run_window_ended(rig: Rig) -> None:
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()

    rig.clock.set_now(berlin("2026-11-16T06:59:59"))
    await services.schedule.tick()
    assert rig.runs.ended_windows == 0

    rig.clock.set_now(berlin("2026-11-16T07:00"))
    await services.schedule.tick()
    assert rig.runs.ended_windows == 1
    await services.schedule.tick()  # stopping now: it isn't asked again
    assert rig.runs.ended_windows == 1


async def test_a_paused_run_gives_a_skipped_row(rig: Rig) -> None:
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T00:30"))
    await rig.runs.start_run(trigger="run_now")
    rig.runs.pause()

    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()
    assert rig.runs.started == []
    skipped = await rows_of_kind(services, "skipped")
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "previous_paused"
    assert skipped[0]["window_start"] == iso_ms(berlin("2026-11-16T01:00"))
    assert skipped[0]["ended_at"] is None
    assert skipped[0]["outcome"] is None
    assert [row.kind for row in rig.finished()] == ["skipped"]

    rig.clock.set_now(berlin("2026-11-16T01:30"))
    await services.schedule.tick()  # one row per window
    assert len(await rows_of_kind(services, "skipped")) == 1


async def test_a_forced_run_covers_the_window(rig: Rig) -> None:
    """A run now that goes on into the window, or ran in it, means no scheduled run starts."""
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T00:55"))
    await rig.runs.start_run(trigger="run_now")

    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()
    assert rig.runs.started == []

    rig.clock.set_now(berlin("2026-11-16T01:30"))
    await rig.runs.finish()
    rig.clock.set_now(berlin("2026-11-16T02:00"))
    await services.schedule.tick()
    assert rig.runs.started == []
    assert [row["trigger"] for row in await rows_of_kind(services, "run")] == ["run_now"]


async def test_a_run_that_ended_before_the_window_does_not_cover_it(rig: Rig) -> None:
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T00:20"))
    await rig.runs.start_run(trigger="run_now")
    rig.clock.set_now(berlin("2026-11-16T00:50"))
    await rig.runs.finish()

    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()
    assert len(rig.runs.started) == 1


async def test_a_run_stopping_as_the_window_opens_doesnt_cover_it(rig: Rig) -> None:
    """Run now at 00:50, stopped at 00:59: it was stopping when the window opened, so once it
    has ended (01:01:30) the window gets its own run."""
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T00:50"))
    await rig.runs.start_run(trigger="run_now")
    rig.runs.stopping()

    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()
    assert rig.runs.started == []  # it's still going: nothing starts beside it

    rig.clock.set_now(berlin("2026-11-16T01:01:30"))
    await rig.runs.finish("stopped")
    rig.clock.set_now(berlin("2026-11-16T01:01:40"))
    await services.schedule.tick()
    assert rig.runs.started == [(monday_window(), "scheduled")]


async def test_a_forced_run_that_failed_doesnt_cover_the_window(rig: Rig) -> None:
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T00:55"))
    await rig.runs.start_run(trigger="run_now")
    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()
    assert rig.runs.started == []

    rig.clock.set_now(berlin("2026-11-16T01:00:10"))
    await rig.runs.finish("failed")  # device_missing, say: it did none of the window's work
    rig.clock.set_now(berlin("2026-11-16T01:01"))
    await services.schedule.tick()
    assert len(rig.runs.started) == 1


async def test_a_client_that_isnt_running_yet_holds_nothing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reboot inside a window: the client isn't up yet when the controller decides. The run
    starts, and its pre-run check waits for the device; no held row decides the window."""
    services = rig.services
    be_healthy(services, monkeypatch, running=False)
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T02:00"))
    assert (await services.schedule.next()).held_reason is None
    await services.schedule.start()
    assert [trigger for _, trigger in rig.runs.started] == ["startup"]
    assert await rows_of_kind(services, "held") == []


async def test_a_client_that_isnt_installed_is_held(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = rig.services
    be_healthy(services, monkeypatch, installed=False, running=False)
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()
    assert rig.runs.started == []
    [held] = await rows_of_kind(services, "held")
    assert held["reason"] == "client_logged_out"


async def test_no_run_starts_while_the_controller_is_stopping(rig: Rig) -> None:
    """The tick can wake between the runs shutdown hook and the tasks' cancellation."""
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.runs.closing = True
    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()
    assert rig.runs.started == []
    assert await run_rows(services) == []


@pytest.mark.parametrize(
    ("reason", "setup", "connection", "logged_in"),
    [
        ("setup_incomplete", False, None, True),
        ("not_connected", True, "not_connected", True),
        ("connection_expired", True, "connection_expired", True),
        ("client_logged_out", True, None, False),
    ],
)
async def test_held_rows(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    setup: bool,
    connection: str | None,
    logged_in: bool,
) -> None:
    """A window that opens while the controller can't run it writes a held row with the reason,
    and no run starts. The row is written once for the window."""
    services = rig.services
    be_healthy(services, monkeypatch, setup=setup, connection=connection, logged_in=logged_in)
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()
    await services.schedule.tick()

    assert rig.runs.started == []
    held = await rows_of_kind(services, "held")
    assert len(held) == 1
    assert held[0]["reason"] == reason
    assert held[0]["trigger"] == "scheduled"
    assert held[0]["started_at"] == iso_ms(berlin("2026-11-16T01:00"))
    assert held[0]["window_end"] == iso_ms(berlin("2026-11-16T07:00"))
    assert held[0]["ended_at"] is None
    assert [row.kind for row in rig.finished()] == ["held"]


async def test_nothing_tracked_writes_no_row_and_a_later_item_starts_the_run(rig: Rig) -> None:
    """With nothing tracked, a window starts no run and writes no row. Tracking something during
    the window starts one at the next tick."""
    services = rig.services
    await set_grid(services, NIGHTLY)
    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()
    assert rig.runs.started == []
    assert await run_rows(services) == []

    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T01:20"))
    await services.schedule.tick()
    assert len(rig.runs.started) == 1


async def test_a_queued_album_alone_starts_a_run(rig: Rig) -> None:
    services = rig.services
    await set_grid(services, NIGHTLY)
    await add_queued_album(services)
    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()
    assert len(rig.runs.started) == 1


async def test_a_failing_tick_is_logged_not_raised(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The watch task survives a tick that raises: the next one still runs."""
    calls: list[int] = []

    async def boom() -> None:
        calls.append(1)
        raise RuntimeError("the tick broke")

    monkeypatch.setattr(rig.services.schedule, "tick", boom)
    with caplog.at_level("ERROR", logger="spotivault.schedule"):
        await rig.clock.advance_until(lambda: len(calls) >= 2, within=600)
    assert any("tick failed" in record.getMessage() for record in caplog.records)
    assert rig.services.fatal_errors == []


async def test_the_watch_task_wakes_at_a_window_start(rig: Rig) -> None:
    """The background task sleeps until the next window, with no tick in between. put() wakes it
    to find the boundary, and the clock then carries it to the window's start."""
    services = rig.services
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T00:30"))
    await services.schedule.put(nightly_update())  # wakes the watch task
    await rig.clock.advance_until(lambda: len(rig.runs.started) == 1, within=3 * 3600)
    assert rig.runs.started == [(monday_window(), "scheduled")]


# --- Start-up -------------------------------------------------------------------------------------


async def test_missed_windows_after_downtime(rig: Rig) -> None:
    """The tick last ran on Sunday noon. On Wednesday noon, the windows that passed in between
    are written as missed, each once."""
    services = rig.services
    await set_grid(services, NIGHTLY)
    await set_seen_at(services, berlin("2026-11-15T12:00"))
    rig.clock.set_now(berlin("2026-11-18T12:00"))
    await services.schedule.start()

    missed = await rows_of_kind(services, "missed")
    assert [row["window_start"] for row in missed] == [
        iso_ms(berlin("2026-11-16T01:00")),
        iso_ms(berlin("2026-11-17T01:00")),
        iso_ms(berlin("2026-11-18T01:00")),
    ]
    assert all(row["reason"] == "not_running" for row in missed)
    assert all(row["trigger"] == "scheduled" for row in missed)
    assert [row.kind for row in rig.finished()] == ["missed"] * 3

    await services.schedule.start()  # again: no duplicates
    assert len(await rows_of_kind(services, "missed")) == 3


async def test_missed_windows_reach_back_21_days_at_most(rig: Rig) -> None:
    services = rig.services
    await set_grid(services, NIGHTLY)
    await set_seen_at(services, berlin("2026-09-01T12:00"))
    rig.clock.set_now(berlin("2026-11-18T12:00"))
    await services.schedule.start()

    starts = sorted(row["window_start"] for row in await rows_of_kind(services, "missed"))
    # The windows that ended in the 21 days up to now: from 29 Oct (the first start after
    # 28 Oct noon) to 18 Nov, one a day.
    assert len(starts) == 21
    assert starts[0] == iso_ms(berlin("2026-10-29T01:00"))
    assert starts[-1] == iso_ms(berlin("2026-11-18T01:00"))


async def test_a_start_up_run_inside_a_window(rig: Rig) -> None:
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T02:00"))
    await services.schedule.start()
    assert [trigger for _, trigger in rig.runs.started] == ["startup"]


async def test_a_start_up_run_restarts_a_window_a_restart_cut_off(rig: Rig) -> None:
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    await services.store.execute(
        "INSERT INTO runs (kind, trigger, state, outcome, reason, started_at, ended_at, "
        "window_start, window_end) VALUES ('run', 'scheduled', 'ended', 'failed', "
        "'container_restarted', ?, ?, ?, ?)",
        (
            iso_ms(berlin("2026-11-16T01:00")),
            iso_ms(berlin("2026-11-16T02:10")),
            iso_ms(berlin("2026-11-16T01:00")),
            iso_ms(berlin("2026-11-16T07:00")),
        ),
    )
    rig.clock.set_now(berlin("2026-11-16T02:20"))
    await services.schedule.start()
    assert [trigger for _, trigger in rig.runs.started] == ["startup"]


async def test_a_window_stopped_by_hand_is_not_restarted_at_start_up(rig: Rig) -> None:
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    await services.store.execute(
        "INSERT INTO runs (kind, trigger, state, outcome, started_at, ended_at, window_start, "
        "window_end) VALUES ('run', 'scheduled', 'ended', 'stopped', ?, ?, ?, ?)",
        (
            iso_ms(berlin("2026-11-16T01:00")),
            iso_ms(berlin("2026-11-16T02:10")),
            iso_ms(berlin("2026-11-16T01:00")),
            iso_ms(berlin("2026-11-16T07:00")),
        ),
    )
    rig.clock.set_now(berlin("2026-11-16T02:20"))
    await services.schedule.start()
    assert rig.runs.started == []


async def test_a_scheduled_run_row_carries_its_window(rig: Rig) -> None:
    """The run's row has the window, so the next tick and a start-up both see it."""
    services = rig.services
    await set_grid(services, NIGHTLY)
    await track_playlist(services)
    rig.clock.set_now(berlin("2026-11-16T01:00"))
    await services.schedule.tick()
    [run] = await rows_of_kind(services, "run")
    assert run["window_start"] == iso_ms(berlin("2026-11-16T01:00"))
    assert run["window_end"] == iso_ms(berlin("2026-11-16T07:00"))
    assert run["trigger"] == "scheduled"
