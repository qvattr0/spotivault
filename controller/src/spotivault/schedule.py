"""The scheduler engine: the weekly grid, and runs that follow it (plan D5: the engine is in M1,
its UI isn't; the grid is set with `PUT /api/schedule`).

Owner: **schedule** (controller/ARCHITECTURE.md § S6's parts). Built by services.py as
`services.schedule`. Frozen interface: the ScheduleService methods below (the router and the run
engine's docs refer to them). The router is api/routers/schedule.py, this builder's too. Not to
be confused with webapi/scheduler.py, the Web API's request scheduler.

Specs: web-ui.md § Schedule (How runs follow the grid, Run order, endpoints) and § History (the
missed, skipped and held rows); openapi.yaml tag `schedule` (getSchedule, putSchedule,
getScheduleNext) and `Schedule`, `ScheduleUpdate`, `ScheduleNext`, `HistoryRow`;
contracts/vectors/schedule-windows.json (every case, DST included); windows.py (frozen: the same
windows the backlog walks: `weekly_windows`, `window_instances`, `load_hours`, `hours_per_week`).

**The grid** is the `schedule_hours` table (day 0 = Monday), wall-clock hours in `config.zone`.
`run_order` is the settings key of that name, saved in the same transaction as the grid.

**The tick** (`watch()`, a background task): sleep on services.clock until the next boundary (the
next window start, the current window's end, or 60 s, whichever is first), or until `put()` wakes
it. Each tick, `meta.scheduler_seen_at` = now, then `tick()`:
1. **The running window follows the grid** (`_follow_grid`, also after a PUT): a scheduled or
   start-up run that isn't stopping already, while now is in no active hour →
   `services.runs.end_window()` (stop after this track; the item is carried over; Window ended).
   Otherwise its window's end becomes the end of the window now is in
   (`services.runs.set_window_end`), so a PUT that shortens, splits or extends the window in
   progress moves where the run stops.
2. **A window is in progress** (`_window_in_progress`), and it isn't decided yet, in this order:
   - the window already has a `runs` row (any kind, except a run a restart cut off), or a run
     covered it: one that overlapped it, ended, didn't fail, and wasn't already stopping when the
     window opened → nothing: the window is decided;
   - a run is going and paused → a `skipped` row (reason previous_paused);
   - a run is going and stopping → nothing yet: it doesn't cover the window, which is decided
     once it has ended;
   - a run is going (a forced one) → nothing: it covers the window ("Run now ignores the grid");
   - the controller is stopping (`services.runs.closing`) → nothing;
   - held → a `held` row with the reason: setup_incomplete, connection_expired or not_connected
     (services.connection.held_reason; `expiring` holds nothing), client_logged_out (a client
     that isn't installed, or runs logged out; one that isn't running yet, as at a reboot, is
     the pre-run check's to restart and wait for, as for createRun);
   - nothing tracked at all (no tracked playlist, no Queued or Partial album) → no run and no
     row, one log line (cautious: History's skipped rows mean "the previous run was paused");
   - otherwise `services.runs.start_scheduled(window, trigger="scheduled")`.

Each no-run row: kind missed/skipped/held, trigger scheduled, started_at = window_start = the
window's start, window_end, reason, ended_at NULL (no run happened, so no duration); then
`run.finished` with `services.history.history_row(id)`.

A window that never ends (every hour active) has no start of its own, so it's anchored at the
Monday 00:00 of its week: one run per week, not one per tick.

**Start-up** (`start()`, a start-up hook, after the run engine's recovery):
- **Missed windows:** every window that started after `meta.scheduler_seen_at` and ended before
  now, with no row yet → a `missed` row (reason not_running). At most the last 21 days.
- **Inside a window now:** the same decision as a tick (trigger `startup`). A run a restart cut
  off (failed, container_restarted) doesn't decide its window, so the window is restarted;
  a window you stopped by hand is left alone (cautious).

**PUT /api/schedule** while a scheduled or start-up run is going: rule 1 at once. If now is no
longer in an active hour, `services.runs.end_window()` ("Editing during a run: if you turn off the
current hour, the run stops after the current track"); otherwise the run's window end follows the
new grid. Then wake the tick.

**GET /api/schedule/next:** the first window that hasn't ended (window_instances, limit 1):
`at`, `window_end`, `in_progress`; `playlists_to_check` (tracked playlists, Liked Songs included,
not removed or unavailable), `albums_queued` (Queued and Partial albums, from services.albums);
`held_reason`: setup_incomplete, then connection_expired / not_connected, then client_logged_out
(as for held rows), then run_paused, else null. Manual only: at, window_end null.

Tests: tests/test_schedule.py, on the FakeClock (`set_now` to put the wall clock where a case
needs it), with every case of schedule-windows.json driving a tick, DST nights included, a
missed window after downtime, and each held and skipped row.
"""

import asyncio
import json
import logging
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from spotivault.api.models import Hours as HoursModel
from spotivault.api.models import Schedule, ScheduleNext, ScheduleUpdate
from spotivault.clock import iso_ms, parse_iso
from spotivault.errors import validation_failed
from spotivault.windows import (
    DAYS,
    Window,
    hours_per_week,
    load_hours,
    weekly_windows,
    window_instances,
)

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

TICK_MAX_S = 60.0  # the tick wakes at least this often
MISSED_HORIZON_DAYS = 21  # missed windows older than this aren't written after a long downtime
SEEN_AT_KEY = "scheduler_seen_at"  # the meta row: when the tick last ran

# The end of a window that never ends, for the SQL comparisons (times sort as text, all UTC).
NEVER = "9999-12-31T23:59:59.999Z"
# A run a restart cut off (the run engine's recovery) doesn't decide its window: see the docstring.
NOT_RESTART_CUT = "NOT (kind = 'run' AND outcome IS 'failed' AND reason IS 'container_restarted')"

type HeldReason = Literal[
    "setup_incomplete", "connection_expired", "not_connected", "client_logged_out"
]
type NoRunKind = Literal["missed", "skipped", "held"]


def _grid(hours: HoursModel) -> dict[str, list[int]]:
    """The API's Hours as day → sorted hours, refusing an hour listed twice (uniqueItems)."""
    grid: dict[str, list[int]] = {}
    for day in DAYS:
        values = list(getattr(hours, day))
        if len(set(values)) != len(values):
            raise validation_failed(f"hours.{day}", f"{day} lists an hour more than once.")
        grid[day] = sorted(values)
    return grid


def _week_start(now: datetime, zone: ZoneInfo) -> datetime:
    """Monday 00:00 of the week `now` is in, in `zone`, as an instant (the anchor of a window
    that never ends)."""
    local = now.astimezone(zone)
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday.astimezone(UTC)


def _window_in_progress(
    hours: Mapping[str, list[int]], zone: ZoneInfo, now: datetime
) -> Window | None:
    """The window `now` is inside, or None. A window that never ends is anchored at its week's
    Monday (see the module docstring); `window_instances` alone would start it at now."""
    found = window_instances(hours, zone, now, limit=1)
    if not found or found[0].start > now:
        return None
    window = found[0]
    if window.end is None:
        return Window(start=_week_start(now, zone), end=None)
    return window


class ScheduleService:
    """The grid and the tick. Built by services.py as `services.schedule`."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        # Set by put(), so the tick runs at once. Cleared before each tick, so a put during one
        # is never lost.
        self._wake = asyncio.Event()
        # The window whose "nothing tracked" line was logged, so the line isn't repeated each tick.
        self._idle_logged: datetime | None = None
        # The monotonic time the watch task sleeps until: None until its first tick is done.
        # Tests wait on it to know the task is asleep.
        self.next_wake_at: float | None = None
        # Runs that were stopping when a window opened (window start → run ids): they don't
        # cover that window, so it gets its own run once they've ended. In memory: a restart
        # ends every run as `container_restarted`, which covers nothing anyway.
        self._stopping_at_open: dict[datetime, set[int]] = {}
        services.add_startup("schedule", self.start)
        services.add_background("schedule.tick", self.watch)

    # --- The API -------------------------------------------------------------------------------

    async def get(self) -> Schedule:
        """GET /api/schedule: the grid, the zone, the run order, windows and hours per week."""
        services = self.services
        hours = await load_hours(services.store)
        run_order = await services.settings.get_value("run_order")
        return Schedule(
            hours=HoursModel.model_validate(hours),
            tz=services.config.tz,
            run_order=run_order,
            windows_per_week=len(weekly_windows(hours)[0]),
            hours_per_week=hours_per_week(hours),
        )

    async def put(self, update: ScheduleUpdate) -> Schedule:
        """PUT /api/schedule: saves the grid (and run_order when given) in one transaction; `tz`
        is ignored. See the module docstring for a run that's going."""
        services = self.services
        grid = _grid(update.hours)
        run_order = update.run_order
        if run_order is not None and len(set(run_order)) != len(run_order):
            raise validation_failed("run_order", "Each group appears once.")
        rows = [(day, hour) for day, day_name in enumerate(DAYS) for hour in grid[day_name]]
        stamp = iso_ms(services.clock.now())

        def write(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM schedule_hours")
            conn.executemany("INSERT INTO schedule_hours (day, hour) VALUES (?, ?)", rows)
            if run_order is not None:
                conn.execute(
                    "INSERT INTO settings (key, value, updated_at) VALUES ('run_order', ?, ?) "
                    "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
                    "updated_at = excluded.updated_at",
                    (json.dumps(run_order), stamp),
                )

        await services.store.transaction(write)
        await self._follow_grid(grid, services.clock.now())
        self._wake.set()
        return await self.get()

    async def next(self) -> ScheduleNext:
        """GET /api/schedule/next (the Dashboard's Next backup card)."""
        services = self.services
        now = services.clock.now()
        hours = await load_hours(services.store)
        found = window_instances(hours, services.config.zone, now, limit=1)
        window = found[0] if found else None
        playlists, albums = await self._counts()
        held = await self._hold_reason()
        active = services.runs.active()
        if held is None and active is not None and active.state == "paused":
            held = "run_paused"
        return ScheduleNext(
            at=None if window is None else window.start,
            window_end=None if window is None else window.end,
            in_progress=window is not None and window.start <= now,
            playlists_to_check=playlists,
            albums_queued=albums,
            held_reason=held,
        )

    # --- The tick ------------------------------------------------------------------------------

    async def tick(self) -> None:
        """One pass of the rules above, at services.clock's now. Tests call it directly."""
        services = self.services
        now = services.clock.now()
        hours = await load_hours(services.store)
        await self._follow_grid(hours, now)
        window = _window_in_progress(hours, services.config.zone, now)
        if window is not None:
            await self._decide(window, trigger="scheduled")

    async def start(self) -> None:
        """Start-up hook: missed windows, then a start-up run if now is in a window. A failure
        is logged, never raised: start-up must not stop on the scheduler."""
        services = self.services
        try:
            now = services.clock.now()
            hours = await load_hours(services.store)
            seen = await self._seen_at()
            if seen is not None:
                await self._write_missed(hours, seen, now)
            window = _window_in_progress(hours, services.config.zone, now)
            if window is not None:
                await self._decide(window, trigger="startup")
        except Exception:
            log.exception("schedule: the start-up checks failed; the tick carries on")

    async def watch(self) -> None:
        """Background task: the tick loop (module docstring). A failing tick is logged, never
        raised: it would stop the controller."""
        while True:
            self._wake.clear()
            await self._tick_and_record()
            seconds = await self._seconds_to_boundary()
            self.next_wake_at = self.services.clock.monotonic() + seconds
            await self._wait(seconds)

    # --- Ending and holding ---------------------------------------------------------------------

    async def _tick_and_record(self) -> None:
        """Writes `scheduler_seen_at` = now, then runs one tick. A failure is logged."""
        services = self.services
        stamp = iso_ms(services.clock.now())
        try:
            await services.store.execute(
                "INSERT INTO meta (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (SEEN_AT_KEY, stamp, stamp),
            )
            await self.tick()
        except Exception:
            log.exception("schedule: the tick failed; the next one runs as usual")

    async def _seconds_to_boundary(self) -> float:
        """Seconds until the next window starts or the current one ends, at most TICK_MAX_S."""
        services = self.services
        try:
            now = services.clock.now()
            hours = await load_hours(services.store)
            best: datetime | None = None
            for window in window_instances(hours, services.config.zone, now):
                # A window in progress ends at its end; a later one starts at its start.
                moment = window.start if window.start > now else window.end
                if moment is not None and (best is None or moment < best):
                    best = moment
        except Exception:
            log.exception("schedule: can't read the next boundary; the tick waits its maximum")
            return TICK_MAX_S
        if best is None:
            return TICK_MAX_S
        return min(TICK_MAX_S, max(0.0, (best - now).total_seconds()))

    async def _wait(self, seconds: float) -> None:
        """Sleeps `seconds` on services.clock, or until put() wakes the tick, whichever is first.
        The two waits are tasks, so the one that lost is cancelled and awaited here."""
        sleeper = asyncio.create_task(self.services.clock.sleep(seconds))
        waker = asyncio.create_task(self._wake.wait())
        try:
            await asyncio.wait({sleeper, waker}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleeper.cancel()
            waker.cancel()
            await asyncio.gather(sleeper, waker, return_exceptions=True)

    async def _follow_grid(self, hours: Mapping[str, list[int]], now: datetime) -> None:
        """Rule 1: a scheduled or start-up run stops after the current track once now is in no
        active hour (its window ended, or a PUT turned the hour off); otherwise its window ends
        where the window now is in ends, as the grid is now."""
        services = self.services
        active = services.runs.active()
        if (
            active is None
            or active.trigger == "run_now"
            or active.window is None
            or active.state == "stopping"
        ):
            return
        current = _window_in_progress(hours, services.config.zone, now)
        if current is None:
            log.info("schedule: the run's window ended (or its hour was turned off); it stops")
            await services.runs.end_window()
            return
        if current.end != active.window.end:
            await services.runs.set_window_end(current.end)

    # --- Deciding one window -------------------------------------------------------------------

    async def _decide(self, window: Window, *, trigger: Literal["scheduled", "startup"]) -> None:
        """The rules for a window in progress, in the order the module docstring gives."""
        services = self.services
        if await self._has_window_row(window):
            return
        active = services.runs.active()
        if active is not None:
            if active.state == "paused":
                await self._write_no_run_row("skipped", window, "previous_paused")
            elif active.state == "stopping":
                # Stopping as the window opens: it won't do the window's work, so the window is
                # decided once it has ended (by the rules below).
                self._stopping_at_open.setdefault(window.start, set()).add(active.run_id)
            return  # a run is going, forced or not: nothing starts beside it
        if await self._ran_in_window(window):
            return
        if services.runs.closing:
            return  # the controller is stopping: no run starts now
        held = await self._hold_reason()
        if held is not None:
            await self._write_no_run_row("held", window, held)
            return
        playlists, albums = await self._counts()
        if playlists == 0 and albums == 0:
            if self._idle_logged != window.start:
                self._idle_logged = window.start
                log.info("schedule: nothing is tracked; the window %s has no run", window.start)
            return
        log.info("schedule: starting a %s run for the window from %s", trigger, window.start)
        await services.runs.start_scheduled(window, trigger=trigger)

    async def _hold_reason(self) -> HeldReason | None:
        """Why a scheduled run can't start now (before any run is going), or None. The client
        holds it only when it isn't installed or runs logged out, as createRun's quick checks
        and the pre-run check have it: one that isn't running (yet: a reboot, a restart) is
        started again by s6, and the pre-run check waits for its device."""
        services = self.services
        if not await services.setup.is_complete():
            return "setup_incomplete"
        connection = await services.connection.held_reason()
        if connection is not None:
            return connection
        status = await services.client.status()
        if not status.installed or (status.running and not status.logged_in):
            return "client_logged_out"
        return None

    async def _counts(self) -> tuple[int, int]:
        """(tracked playlists with Liked Songs, Queued and Partial albums)."""
        services = self.services
        row = await services.store.fetchone(
            "SELECT COUNT(*) AS n FROM items WHERE kind <> 'album' AND tracked = 1 "
            "AND removed_at IS NULL AND unavailable_at IS NULL"
        )
        playlists = int(row["n"]) if row is not None else 0
        summary = (await services.albums.list_albums()).summary
        return playlists, summary.queued + summary.partial

    # --- Rows ----------------------------------------------------------------------------------

    async def _has_window_row(self, window: Window) -> bool:
        """A `runs` row for this window: a run, or a no-run row. A run a restart cut off doesn't
        count (its window is restarted)."""
        row = await self.services.store.fetchone(
            f"SELECT 1 FROM runs WHERE window_start = ? AND {NOT_RESTART_CUT} LIMIT 1",
            (iso_ms(window.start),),
        )
        return row is not None

    async def _ran_in_window(self, window: Window) -> bool:
        """A run covered the window: it overlapped it and has ended, didn't fail (a run that
        failed did none of the window's work), and wasn't already stopping when the window
        opened. A forced run that ran into the window, say: the scheduler doesn't start a second
        run for it."""
        end = NEVER if window.end is None else iso_ms(window.end)
        rows = await self.services.store.fetchall(
            "SELECT id FROM runs WHERE kind = 'run' AND started_at < ? "
            "AND (ended_at IS NULL OR ended_at > ?) AND outcome IS NOT 'failed'",
            (end, iso_ms(window.start)),
        )
        stopping = self._stopping_at_open.get(window.start, set())
        return any(row["id"] not in stopping for row in rows)

    async def _seen_at(self) -> datetime | None:
        """When the tick last ran, or None (a fresh install, or a value that doesn't parse)."""
        row = await self.services.store.fetchone(
            "SELECT value FROM meta WHERE key = ?", (SEEN_AT_KEY,)
        )
        if row is None:
            return None
        try:
            return parse_iso(row["value"])
        except ValueError:
            log.warning("schedule: %s isn't a time; no missed windows are written", SEEN_AT_KEY)
            return None

    async def _write_missed(
        self, hours: Mapping[str, list[int]], seen: datetime, now: datetime
    ) -> None:
        """A `missed` row for each window that started after the tick last ran and ended before
        now, with no row yet. At most MISSED_HORIZON_DAYS back."""
        base = max(seen, now - timedelta(days=MISSED_HORIZON_DAYS))
        zone = self.services.config.zone
        for window in window_instances(hours, zone, base, horizon_days=MISSED_HORIZON_DAYS + 7):
            if window.end is None or window.start <= base or window.end > now:
                continue
            if await self._any_row_starts(window):
                continue
            await self._write_no_run_row("missed", window, "not_running")

    async def _any_row_starts(self, window: Window) -> bool:
        row = await self.services.store.fetchone(
            "SELECT 1 FROM runs WHERE window_start = ? LIMIT 1", (iso_ms(window.start),)
        )
        return row is not None

    async def _write_no_run_row(self, kind: NoRunKind, window: Window, reason: str) -> None:
        """Writes a missed, skipped or held row for the window, then publishes `run.finished`
        with its HistoryRow (after the commit)."""
        services = self.services
        start = iso_ms(window.start)
        end = None if window.end is None else iso_ms(window.end)
        result = await services.store.execute(
            "INSERT INTO runs (kind, trigger, reason, started_at, window_start, window_end) "
            "VALUES (?, 'scheduled', ?, ?, ?, ?)",
            (kind, reason, start, start, end),
        )
        if result.lastrowid is None:
            raise RuntimeError("schedule: the insert gave no row id")
        log.info("schedule: %s row for the window from %s (%s)", kind, start, reason)
        row = await services.history.history_row(result.lastrowid)
        services.bus.publish("run.finished", {"run": row})
