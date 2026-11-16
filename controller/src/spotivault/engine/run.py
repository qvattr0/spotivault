"""The run engine: one run at a time, its queue, and the hello's `status` (plan § Run states).

Owner: **engine-run** (controller/ARCHITECTURE.md § S6's parts). Built by services.py as
`services.runs`. Frozen interface: everything public on RunEngine and ActiveRun below (the
routers, the scheduler and the metrics call them). engine/types.py and engine/states.py are the
shared types; queue.py, precheck.py and recovery.py are this builder's too, as are the routers
api/routers/status.py and runs.py.

Specs: design.md § Run flow (the end: "The scheduler queues items. An item forced from the UI goes
right after the current item. One item records at a time."), § Container (Shutdown); web-ui.md §
Dashboard (Idle, Running, Warnings during a run, endpoints), § Schedule (Run order), § Player
(During a run: view-only); openapi.yaml tags `runs` (getStatus, createRun, getCurrentRun,
stopCurrentRun, resumeCurrentRun, removeQueuedItem); events.md (`run.*`, `item.state`,
`device.moved`, `error`, `library.item`, `album.item`, `backlog`).

**A run, step by step:**
1. **Create** (createRun, or the scheduler): quick checks first, answered with 409 at once:
   `setup_incomplete`, `connection_expired` / `not_connected` (`expiring` doesn't refuse),
   `client_not_installed`, `client_logged_out` (a running client that isn't logged in),
   `run_active` for Run now while a run is going. The `runs` row goes in (kind run, state
   starting, trigger; window_start/window_end for scheduled and start-up runs),
   `services.client.set_run_active(True)`, a `run.state`, and the answer is 202 `RunCreated`.
   The rest runs in `serve()`'s task.
2. **starting** (precheck.py): the pre-run check and the catalog refresh. A failed check ends the
   run `failed` with its reason. A stop meanwhile cancels the check (the client restart, the 60 s
   device wait and the refresh included) and ends the run by the stop. Then the queue (queue.py)
   and its `run_items` rows, and `run.queue`. D6: another device is playing → the run goes
   `paused` (`device_busy`), with a `device.moved` event (item_id and discarded_take_id null); it
   never takes playback.
3. **running ⇄ finishing:** the first waiting item, in queue order, runs as an ItemEngine
   (engine/item.py) with an ItemJob and an ItemControl. This class is its ItemHost: each phase
   is checked (states.check_item_transition), stored, and published (`item.state`); the run
   follows the item's `finishing` phase; counters are stored as they change, with at most one
   `run.state` a second for counters alone; `library.item` / `album.item` follow.
4. **After each item** (its ItemReport), `_apply_report`: the item's state. An interruption on
   attempt 2 → partial. The first one: by a stall → re-queued at the end with attempt 2; by a
   takeover → the run pauses (`device_moved`, a `device.moved` event) and Resume restarts the
   same item first, with attempt 2; by a shutdown → it stays `interrupted`. device_busy → back
   to up_next and the run pauses. Then `services.matching.invalidate()` and
   `services.backlog.update()`. A RunFailure ends the run `failed`.
5. **Forced items** (createRun with items during a run): right after the current item, in the
   given order; items already waiting move there (`forced` 1). `run.queue` whenever the queue's
   order or membership changes.
6. **Stopping** (stop(), end_window(), shutdown()): `stopping` with stop_mode; the current item's
   ItemControl gets the StopRequest; waiting items end per states.waiting_item_outcome.
7. **Ending:** outcome by states.run_outcome; counters from the items; Web API counts from
   `services.webapi_usage.finish_scope(ApiScope("run", run_id))` (which logs its line);
   `services.client.set_run_active(False)`, failures included; the last `run.state` with state
   idle, then `run.finished` with `services.history.history_row(run_id)`.
8. **Run now** covers every tracked playlist (Liked Songs included) plus Queued and Partial
   albums; with `items`, just those.

**Start-up recovery** (recovery.py) is the start-up hook `runs.recover`, before the scheduler's.

**The window** of a scheduled or start-up run follows the grid: the scheduler moves its end
(`set_window_end`) when a PUT changes the window in progress, so `runs.window_end` and
RunSummary.window_end show where it really stops.

**SIGTERM** (the `runs` shutdown hook; docker gives 60 s, s6 50): from its start no new run is
created (`closing`: the scheduler's tick may still wake before the tasks are cancelled). Stop now
with cause shutdown:
the current item ends `interrupted` (interrupted_by shutdown), the run ends `failed` with reason
container_restarted (cautious: it's an issue to see, and crash recovery says the same). Bounded
to 40 s on services.clock: past that, the run's rows are repaired as recovery would, any
recorder is killed, and the serve task is cancelled by the shutdown that follows.

**Concurrency:** the API calls, the ItemHost callbacks and the driver all change the run under
one asyncio.Lock, never held across an item or a Web API call. Every change is written to the
database before its event is published (events.md: publish after commit).

**Tests** swap `make_item_engine` for a scripted item engine (tests/test_engine_run.py).
"""

import asyncio
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from spotivault.api.models import (
    Counters,
    CurrentRun,
    QueueItem,
    QueueItemCounts,
    QueueItemExpect,
    RunCreated,
    RunSummary,
    Status,
)
from spotivault.catalog.covers import cover_url
from spotivault.clock import iso_ms
from spotivault.engine import queue as run_queue
from spotivault.engine.item import ItemEngine
from spotivault.engine.precheck import PreRunResult, pre_run_check
from spotivault.engine.recovery import fail_unfinished_run
from spotivault.engine.recovery import recover as recover_runs
from spotivault.engine.states import (
    WAITING_STATES,
    ItemState,
    RunEnd,
    RunState,
    StoredRunState,
    api_run_state,
    check_item_transition,
    check_run_transition,
    is_final,
    item_badges,
    run_outcome,
    waiting_item_outcome,
)
from spotivault.engine.types import (
    InterruptedBy,
    ItemControl,
    ItemJob,
    ItemKind,
    ItemLive,
    ItemReport,
    ItemTimings,
    PlayMode,
    RunFailure,
    StopMode,
    StopRequest,
    TrackCounts,
)
from spotivault.errors import ApiError, not_found, run_active
from spotivault.ports import ApiScope, Device, WebApiError
from spotivault.windows import Window

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

type Trigger = Literal["scheduled", "run_now", "startup"]
type PausedReason = Literal["device_moved", "device_busy"]

IDLE_STATUS = Status(
    state="idle", run=None, item=None, track=None, session_state=None, view_only=False
)

SHUTDOWN_BOUND_S = 40.0  # SIGTERM: the run must be ended by then (docker's grace is 60 s)
COUNTERS_INTERVAL_S = 1.0  # at most one `run.state` a second for counters alone (events.md)


@dataclass(frozen=True, slots=True)
class ActiveRun:
    """The run that's going, as the scheduler and the metrics see it."""

    run_id: int
    trigger: Trigger
    state: StoredRunState  # never "ended"
    paused_reason: PausedReason | None
    window: Window | None  # scheduled and start-up runs


class ItemRunner(Protocol):
    """What the run engine needs of an item engine (engine/item.py's ItemEngine)."""

    async def run(self) -> ItemReport: ...

    def live(self) -> ItemLive: ...

    @property
    def recorder_pid(self) -> int | None: ...


# ItemEngine's constructor: (services, job, *, host, control). Tests pass a scripted one.
type ItemRunnerFactory = Callable[..., ItemRunner]


def merge_attempts(earlier: TrackCounts, latest: TrackCounts) -> TrackCounts:
    """An item's counts over its attempts in one run. The retry skips what the earlier attempt
    recorded, as duplicates, so those aren't counted twice; its failures replace the earlier
    ones, since it tried those tracks again."""
    if earlier == TrackCounts():
        return latest
    return TrackCounts(
        recorded=earlier.recorded + latest.recorded,
        skipped_duplicate=earlier.skipped_duplicate
        + max(0, latest.skipped_duplicate - earlier.recorded),
        skipped_other=earlier.skipped_other + latest.skipped_other,
        failed=latest.failed,
        bytes=earlier.bytes + latest.bytes,
    )


@dataclass(slots=True)
class _Entry:
    """One item of the run's queue: its `run_items` row, kept in memory."""

    run_item_id: int
    item_id: str
    kind: ItemKind
    name: str
    context_uri: str  # items.uri: Liked Songs' is spotify:user:<id>:collection
    cover: str | None
    item_access: bool
    expect_count: int | None  # tracks still missing when it was queued; None when unknown
    changed_at: str | None  # items.changed_at and added_at: the order inside a group
    added_at: str
    state: ItemState = "up_next"
    attempt: int = 1
    mode: PlayMode | None = None
    planned: int | None = None
    earlier: TrackCounts = field(default_factory=TrackCounts)  # the earlier attempts' counts
    counts: TrackCounts = field(default_factory=TrackCounts)  # this attempt's
    reason: str | None = None
    interrupted_count: int = 0
    interrupted_by: InterruptedBy | None = None
    carried_over_in: bool = False
    carried_over_out: bool = False
    forced: bool = False
    ran_order: int | None = None
    final: bool = False  # done with in this run (an item interrupted by a shutdown included)

    @property
    def total(self) -> TrackCounts:
        return merge_attempts(self.earlier, self.counts)


@dataclass(slots=True)
class _Run:
    """The run that's going, in memory. The `runs` row follows every change."""

    run_id: int
    trigger: Trigger
    started_at: datetime
    window: Window | None
    requested: list[str] | None  # createRun's items: just those; None: everything due
    state: StoredRunState = "starting"
    paused_reason: PausedReason | None = None
    stop: StopRequest | None = None
    stop_requested: asyncio.Event = field(default_factory=asyncio.Event)  # set with `stop`
    queue: list[_Entry] = field(default_factory=list)  # every item, in queue order
    queue_built: bool = False
    run_order: tuple[run_queue.RunOrderGroup, ...] = run_queue.DEFAULT_RUN_ORDER
    pending_forced: list[str] = field(default_factory=list)  # forced while still starting
    current: _Entry | None = None  # the item running, or the one Resume restarts
    engine: ItemRunner | None = None
    control: ItemControl | None = None
    device: Device | None = None  # ours, from the pre-run check
    snapshots_unread: frozenset[str] = frozenset()
    refresh_failed: bool = False
    attempts: int = 0  # items started so far: numbers the recorder sockets
    ran: int = 0  # items that ran so far: ran_order
    counters_sent_at: float | None = None
    counters_dirty: bool = False
    ended: bool = False


class RunEngine:
    """Runs, one at a time. Built by services.py as `services.runs`; owns the hello's `status`.
    It's the ItemHost (engine/types.py) of the item that runs."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        self.make_item_engine: ItemRunnerFactory = ItemEngine
        self._run: _Run | None = None
        self._lock = asyncio.Lock()  # every change to the run (module docstring)
        self._created = asyncio.Event()  # a run was created: serve() picks it up
        self._idle = asyncio.Event()  # no run is going
        self._idle.set()
        self._wake = asyncio.Event()  # Resume or a stop while the driver waits on a pause
        self._counters_due = asyncio.Event()  # counters changed within the last second
        self._closing = False  # the controller is stopping: no new run (shutdown())
        services.bus.add_snapshot("status", self.status)
        services.add_startup("runs.recover", self.recover)
        services.add_background("runs", self.serve)
        services.add_shutdown("runs", self.shutdown)

    # --- Reading (sync ones never touch the store) ---------------------------------------------

    async def status(self) -> Status:
        """GET /api/status and the hello's `status`: the run, the current item, the take
        recording now, Spytify's session state, and view_only (any state but idle). Never
        raises (the hello must work): a part that can't be built is left out and logged."""
        run = self._run
        if run is None:
            return IDLE_STATUS
        try:
            live = self._live(run)
            current = run.current
            return Status(
                state=api_run_state(run.state),
                run=self._summary(run),
                item=self._queue_item(current) if current is not None else None,
                track=live.now_playing if live is not None else None,
                session_state=live.session_state if live is not None else None,
                view_only=True,
            )
        except Exception:
            log.exception("runs: run %d's status can't be built", run.run_id)
            return Status(
                state=api_run_state(run.state),
                run=None,
                item=None,
                track=None,
                session_state=None,
                view_only=True,
            )

    @property
    def closing(self) -> bool:
        """The controller is stopping (SIGTERM): no new run starts."""
        return self._closing

    def active(self) -> ActiveRun | None:
        """The run that's going, or None. Synchronous: from memory."""
        run = self._run
        if run is None:
            return None
        return ActiveRun(
            run_id=run.run_id,
            trigger=run.trigger,
            state=run.state,
            paused_reason=run.paused_reason,
            window=run.window,
        )

    def recorder_pid(self) -> int | None:
        """spytifyd's pid while an item records, for the run metrics."""
        run = self._run
        if run is None or run.engine is None:
            return None
        try:
            return run.engine.recorder_pid
        except Exception:
            return None

    async def current(self) -> CurrentRun:
        """GET /api/runs/current: the run, every item in display order (finished ones first,
        then the current one, then Up next and interrupted ones), and the current item's live
        track table (ItemEngine.live().tracks)."""
        run = self._run
        if run is None:
            return CurrentRun(run=None, queue=[], current_tracks=[])
        live = self._live(run)
        return CurrentRun(
            run=self._summary(run),
            queue=self._display_queue(run),
            current_tracks=list(live.tracks) if live is not None else [],
        )

    # --- Changing (the runs endpoints) ---------------------------------------------------------

    async def create_run(self, items: Sequence[str] | None) -> RunCreated:
        """POST /api/runs (trigger run_now). See the module docstring, step 1 and 5. Raises
        ApiError: 404 not_found (with details.ids) for an unknown item id, 409 for the quick
        checks."""
        ids = list(dict.fromkeys(items)) if items else None
        async with self._lock:
            if self._closing:
                raise ApiError(409, "run_active", "The controller is stopping: no backup starts.")
            if ids is not None:
                await self._check_items_exist(ids)
            run = self._run
            if run is not None and (ids is None or run.state == "stopping"):
                raise run_active()  # a stopping run takes nothing new
            await self._quick_checks()
            if run is not None:
                assert ids is not None
                added = await self._force_items(run, ids)
                return RunCreated(run_id=run.run_id, started=False, added=added)
            run = await self._insert_run("run_now", window=None, requested=ids)
            return RunCreated(run_id=run.run_id, started=True, added=ids or [])

    async def stop(self, mode: StopMode) -> RunSummary:
        """POST /api/runs/current/stop: cause user. `now` after `after_track` upgrades it.
        409 no_run when idle."""
        async with self._lock:
            run = self._require_run()
            await self._request_stop(run, StopRequest(mode=mode, cause="user"))
            return self._summary(run)

    async def resume(self) -> RunSummary:
        """POST /api/runs/current/resume: only while paused (409 not_paused, no_run). Takes
        playback back on our device and restarts the current item (its recorded tracks are
        skipped as duplicates)."""
        async with self._lock:
            run = self._require_run()
            if run.state != "paused":
                raise ApiError(409, "not_paused", "The backup isn't paused.")
        await self._take_playback_back(run)
        async with self._lock:
            if run is self._run and run.state == "paused" and run.stop is None:
                log.info("runs: run %d resumed", run.run_id)
                await self._set_run_state(run, "running")
                self._wake.set()
            return self._summary(run)

    async def remove_queued(self, item_id: str) -> None:
        """DELETE /api/runs/current/items/{id}: a waiting item → removed. 404 not_found when
        it isn't waiting, 409 item_is_current or no_run."""
        async with self._lock:
            run = self._require_run()
            if item_id in run.pending_forced:
                run.pending_forced.remove(item_id)
                return
            entry = _find(run, item_id)
            if entry is not None and entry is run.current and not entry.final:
                raise ApiError(
                    409,
                    "item_is_current",
                    "The current item can't be removed; stop the run instead.",
                )
            if entry is None or entry.final or entry.state not in WAITING_STATES:
                raise not_found("The item isn't waiting in this run.")
            previous = entry.state
            check_item_transition(previous, "removed")
            entry.state = "removed"
            entry.final = True
            await self.services.store.execute(
                "UPDATE run_items SET state = 'removed' WHERE id = ?", (entry.run_item_id,)
            )
            log.info("runs: run %d: %s removed from the queue", run.run_id, entry.name)
            self._publish_item_state(run, entry, previous)
            self._publish_queue(run)
        await self._publish_library(entry)

    # --- The scheduler -------------------------------------------------------------------------

    async def start_scheduled(
        self, window: Window, *, trigger: Literal["scheduled", "startup"]
    ) -> int:
        """Starts a run for this window and returns its id. The scheduler has already written
        held or skipped rows where they apply and checked that no run is going; the pre-run
        check still runs (a failure ends this run `failed`). Raises RuntimeError if a run is
        going after all, or while the controller is stopping."""
        async with self._lock:
            if self._closing:
                raise RuntimeError("the controller is stopping: no run starts")
            if self._run is not None:
                raise RuntimeError(f"run {self._run.run_id} is going: no second run starts")
            run = await self._insert_run(trigger, window=window, requested=None)
            return run.run_id

    async def end_window(self) -> None:
        """The window of the scheduled or start-up run that's going has ended (or its hour was
        turned off): stop after this track, the current item ends carried_over, and the run
        ends window_ended. Does nothing for a run_now run or when idle."""
        async with self._lock:
            run = self._run
            if run is None or run.trigger == "run_now" or run.window is None:
                return
            log.info("runs: run %d: the window ended; stopping after this track", run.run_id)
            await self._request_stop(run, StopRequest(mode="after_track", cause="window_end"))

    async def set_window_end(self, end: datetime | None) -> None:
        """The scheduler moved the end of the running run's window (a PUT changed the window in
        progress): stored in `runs.window_end`, and published with the run's state. Does nothing
        for a run_now run, when idle, or when the end is the same."""
        async with self._lock:
            run = self._run
            if run is None or run.window is None or run.trigger == "run_now":
                return
            if run.window.end == end:
                return
            run.window = Window(start=run.window.start, end=end)
            await self.services.store.execute(
                "UPDATE runs SET window_end = ? WHERE id = ?",
                (iso_ms(end) if end is not None else None, run.run_id),
            )
            log.info(
                "runs: run %d: its window now ends at %s",
                run.run_id,
                iso_ms(end) if end is not None else "never",
            )
            self._publish_run_state(run, run.state)

    # --- Lifecycle (registered in __init__) ----------------------------------------------------

    async def recover(self) -> None:
        """Start-up recovery (recovery.py). Runs before the scheduler's start-up hook."""
        await recover_runs(self.services)

    async def serve(self) -> None:
        """Background task: waits for a run to be created and runs it, one at a time, until
        shutdown. An exception escaping a run is caught here, logged, and that run ends failed:
        escaping this task would stop the controller."""
        while True:
            await self._created.wait()
            self._created.clear()
            run = self._run
            if run is None or run.ended:
                continue
            try:
                await self._drive(run)
            except Exception:
                log.exception("runs: run %d stopped on an unexpected error", run.run_id)
                await self._end_after_error(run)

    async def shutdown(self) -> None:
        """SIGTERM: Stop now, the current item interrupted, the run failed (container_restarted),
        within 40 s. From here on no run starts (`closing`)."""
        self._closing = True
        async with self._lock:
            run = self._run
            if run is None:
                return
            log.info("runs: the controller is stopping: stopping run %d now", run.run_id)
            await self._request_stop(run, StopRequest(mode="now", cause="shutdown"))
        if await self._wait_until_idle(SHUTDOWN_BOUND_S):
            return
        log.warning(
            "runs: run %d didn't end within %.0f s of the stop; ending it as recovery would",
            run.run_id,
            SHUTDOWN_BOUND_S,
        )
        await self._force_end(run)

    # --- ItemHost (engine/types.py): the item engine's calls -----------------------------------

    async def item_phase(
        self,
        job: ItemJob,
        phase: ItemState,
        *,
        mode: PlayMode | None = None,
        planned: int | None = None,
    ) -> None:
        """The current item entered `phase`: stored, published, and the run follows it."""
        async with self._lock:
            found = self._current_for(job)
            if found is None:
                return  # a run ended under it (the SIGTERM bound): nothing to show any more
            run, entry = found
            previous = entry.state
            check_item_transition(previous, phase)
            entry.state = phase
            if mode is not None:
                entry.mode = mode
                entry.planned = planned
            if entry.ran_order is None:
                run.ran += 1
                entry.ran_order = run.ran
            await self.services.store.execute(
                "UPDATE run_items SET state = ?, mode = ?, planned = ?, ran_order = ?, "
                "started_at = coalesce(started_at, ?) WHERE id = ?",
                (
                    phase,
                    entry.mode,
                    entry.planned,
                    entry.ran_order,
                    iso_ms(self.services.clock.now()),
                    entry.run_item_id,
                ),
            )
            self._publish_item_state(run, entry, previous)
            # The run is `finishing` while its item is (the ~25–30 s while the recorder saves the
            # last track), and `running` otherwise; a paused or stopping run stays as it is.
            if phase == "finishing" and run.state == "running":
                await self._set_run_state(run, "finishing")
            elif phase != "finishing" and run.state == "finishing":
                await self._set_run_state(run, "running")
        await self._publish_library(entry)

    async def item_counts(self, job: ItemJob, counts: TrackCounts) -> None:
        """The current item's counts changed: stored, with the run's counters."""
        async with self._lock:
            found = self._current_for(job)
            if found is None:
                return
            run, entry = found
            entry.counts = counts
            await self._store_counts(run, entry)
            self._counters_changed(run)
        await self._publish_library(entry)

    # --- Driving a run (serve's task) ----------------------------------------------------------

    async def _drive(self, run: _Run) -> None:
        """One run, from its pre-run check to its end."""
        pre = await self._pre_run_check(run)
        stop_end, stop_failure = _end_for_stop(run.stop)
        if stop_end == "failed":  # the controller is stopping: that says it all
            await self._finish(run, stop_end, stop_failure)
            return
        if pre is None:  # a stop cut the check short
            assert stop_end is not None
            await self._finish(run, stop_end, stop_failure)
            return
        if pre.failure is not None:
            await self._finish(run, "failed", pre.failure)
            return
        if stop_end is not None:
            await self._finish(run, stop_end, stop_failure)
            return
        await self._build_queue(run, pre)
        end, failure = await self._run_queue(run)
        await self._finish(run, end, failure)

    async def _pre_run_check(self, run: _Run) -> PreRunResult | None:
        """The pre-run check, or None when a stop came first: the check is then cancelled where
        it is (a client restart, the 60 s device wait, the catalog refresh), so a Stop or a
        SIGTERM in `starting` doesn't wait for it."""
        async with asyncio.TaskGroup() as group:
            check = group.create_task(pre_run_check(self.services, run.run_id))
            stopped = group.create_task(run.stop_requested.wait())
            await asyncio.wait({check, stopped}, return_when=asyncio.FIRST_COMPLETED)
            # Cancelling a task the group owns isn't an error for the group.
            stopped.cancel()
            if not check.done():
                log.info("runs: run %d: stopped during its pre-run check", run.run_id)
                check.cancel()
        if check.cancelled():
            return None
        return check.result()

    async def _run_queue(self, run: _Run) -> tuple[RunEnd, RunFailure | None]:
        """Runs the waiting items one after the other, until the queue is done, a stop, or a
        failure that ends the run. Waits while the run is paused."""
        while True:
            end, failure = _end_for_stop(run.stop)
            if end is not None:
                return end, failure
            if run.state == "paused":
                # Nothing runs until Resume or a stop sets `_wake` (no await between the check
                # and the clear, so a wake can't be lost).
                self._wake.clear()
                await self._wake.wait()
                continue
            report = await self._run_next_item(run)
            if report == "empty":
                return "queue_done", None
            if report == "not_now":
                continue  # a stop or a pause came in first: the checks above see it
            if report.run_failure is not None:
                end, failure = _end_for_stop(run.stop)
                if end == "failed":
                    return end, failure
                return "failed", report.run_failure

    async def _run_next_item(self, run: _Run) -> ItemReport | Literal["empty", "not_now"]:
        """Runs the first waiting item once and returns its report: "empty" when nothing is
        waiting, "not_now" when a stop or a pause came in since the driver last looked."""
        groups = run_queue.run_order_groups(await self.services.settings.get_value("run_order"))
        async with self._lock:
            if run.stop is not None or run.state == "paused":
                return "not_now"
            if groups != run.run_order:
                await self._reorder_waiting(run, groups)
            entry = _next_waiting(run)
            if entry is None:
                return "empty"
            run.attempts += 1
            job = self._job(run, entry)
            control = ItemControl()
            engine = self.make_item_engine(self.services, job, host=self, control=control)
            run.current, run.engine, run.control = entry, engine, control
            entry.earlier = entry.total  # an earlier attempt's counts stay counted
            entry.counts = TrackCounts()
            entry.reason = None
            await self.services.store.execute(
                "UPDATE run_items SET attempt = ?, log_file = ?, events_file = ? WHERE id = ?",
                (entry.attempt, str(job.log_file), str(job.events_file), entry.run_item_id),
            )
        log.info(
            "runs: run %d: %s (%s), attempt %d", run.run_id, entry.name, entry.kind, job.attempt
        )
        started = self.services.clock.now()
        report = await self._run_engine(run, engine)
        async with self._lock:
            run.engine = None
            run.control = None
        crashed = report is None
        if report is None:  # the item engine raised: a bug, logged already
            await self._kill_orphans()
            report = _crash_report(started, self.services.clock.now())
        await self._apply_report(run, entry, report, crashed=crashed)
        return report

    async def _run_engine(self, run: _Run, engine: ItemRunner) -> ItemReport | None:
        """`engine.run()`, with the counters' once-a-second flush beside it. None if it raised.
        A cancellation (the controller stopping) goes through."""
        async with asyncio.TaskGroup() as group:
            flusher = group.create_task(self._flush_counters(run), name="runs.counters")
            try:
                return await engine.run()
            except Exception:
                log.exception("runs: run %d: the item engine failed", run.run_id)
                return None
            finally:
                flusher.cancel()

    async def _build_queue(self, run: _Run, pre: PreRunResult) -> None:
        """The run's queue and its run_items rows, after a passed pre-run check. Then the run
        goes running, or paused for D6."""
        services = self.services
        run.device = pre.device
        if pre.refresh is not None:
            run.snapshots_unread = frozenset(pre.refresh.snapshots_unread)
        run.refresh_failed = pre.refresh_failed
        candidates = await run_queue.load_candidates(services, run.requested)
        groups = run_queue.run_order_groups(await services.settings.get_value("run_order"))
        run.run_order = groups
        ordered = run_queue.order_queue(candidates, groups)
        carried = {c.item_id for c in candidates if c.carried_over}
        async with self._lock:
            forced = [item_id for item_id in run.pending_forced]
            run.pending_forced = []
            ids = forced + [c.item_id for c in ordered if c.item_id not in forced]
            infos = await self._item_infos(ids)
            entries = [
                _new_entry(
                    infos[item_id],
                    forced=item_id in forced,
                    carried_over_in=item_id in carried,
                )
                for item_id in ids
                if item_id in infos
            ]
            await self._insert_entries(run, entries)
            run.queue = entries
            run.queue_built = True
            log.info("runs: run %d: %d item(s) queued", run.run_id, len(entries))
            self._publish_queue(run)
            if run.stop is not None:
                pass  # stopped while starting: the run is `stopping`, and the driver ends it
            elif pre.device_busy is not None:
                log.info(
                    "runs: run %d: %s is playing; the run starts paused (D6)",
                    run.run_id,
                    pre.device_busy.name,
                )
                await self._set_run_state(run, "paused", paused_reason="device_busy")
                self._publish_device_moved(run, pre.device_busy, item_id=None, take_id=None)
            else:
                await self._set_run_state(run, "running")

    async def _apply_report(
        self, run: _Run, entry: _Entry, report: ItemReport, *, crashed: bool = False
    ) -> None:
        """The item's state from how its attempt ended (module docstring, step 4). `crashed`:
        the item engine raised, so its last phase may be anything; the item is set `failed`
        directly, as a repair (states.py's tables are for the engines' own moves)."""
        async with self._lock:
            if run.ended:
                return
            previous = entry.state
            entry.counts = report.counts
            if report.mode is not None:  # planning got that far; a whole item plans nothing
                entry.mode = report.mode
                entry.planned = report.planned if report.mode == "missing_only" else None
            pause: PausedReason | None = None
            pause_device: Device | None = None
            requeue = False
            new: ItemState
            if report.outcome == "device_busy":
                new = "up_next"  # D6: it runs again first, once Resume is pressed
                pause, pause_device = "device_busy", report.device_busy
            elif report.outcome == "interrupted":
                by: InterruptedBy = report.interrupted_by or "stall"
                entry.interrupted_count = min(2, entry.interrupted_count + 1)
                entry.interrupted_by = by
                if by == "shutdown":
                    new = "interrupted"  # its outcome in this run: the controller stopped
                    entry.final = True
                elif entry.attempt >= 2:
                    new = "partial"  # the second interruption in this run
                else:
                    new = "interrupted"
                    entry.attempt = 2
                    requeue = by == "stall"  # a takeover's item runs again first, on Resume
                if by == "takeover":
                    pause = "device_moved"
                    pause_device = report.takeover.device if report.takeover else None
            else:
                new = report.outcome
            if crashed:
                log.error("runs: run %d: %s set failed from %s", run.run_id, entry.name, previous)
            else:
                check_item_transition(previous, new)
            entry.state = new
            entry.final = entry.final or is_final(new)
            if new == "carried_over":
                entry.carried_over_out = True
            entry.reason = report.reason or _default_reason(entry, report)
            if requeue:
                run.queue.remove(entry)
                run.queue.append(entry)
            await self._store_report(run, entry, report, requeue=requeue)
            log.info(
                "runs: run %d: %s ended %s: %d recorded, %d skipped, %d failed%s",
                run.run_id,
                entry.name,
                new,
                entry.total.recorded,
                entry.total.skipped,
                entry.total.failed,
                f" ({entry.reason})" if entry.reason else "",
            )
            pausing = (
                pause is not None and run.stop is None and run.state in ("running", "finishing")
            )
            # While paused, an item that will run again stays the current one: Resume restarts
            # it first, and the Dashboard shows it as the interrupted current item.
            run.current = entry if pausing and not entry.final else None
            self._publish_item_state(run, entry, previous)
            if requeue:
                self._publish_queue(run)
            if pausing:
                if pause_device is None:
                    pause_device = await self._active_device(run)
                await self._set_run_state(run, "paused", paused_reason=pause)
                if pause == "device_moved":
                    take_id = report.takeover.discarded_take_id if report.takeover else None
                    self._publish_device_moved(
                        run, pause_device, item_id=entry.item_id, take_id=take_id
                    )
                else:
                    self._publish_device_moved(run, pause_device, item_id=None, take_id=None)
            elif run.state == "finishing":
                await self._set_run_state(run, "running")
        await self._publish_library(entry)
        self.services.matching.invalidate()
        try:
            await self.services.backlog.update()
        except Exception:
            log.exception("runs: the backlog update after %s failed", entry.item_id)

    async def _finish(self, run: _Run, end: RunEnd, failure: RunFailure | None) -> None:
        """Ends the run (module docstring, step 7)."""
        services = self.services
        changed: list[tuple[_Entry, ItemState]] = []
        async with self._lock:
            if run.ended:
                return
            for entry in run.queue:
                if entry.final:
                    continue
                previous = entry.state
                if entry.state in WAITING_STATES:
                    new = waiting_item_outcome(end, entry.state)
                    check_item_transition(entry.state, new)
                else:
                    # An item still in a phase: its engine failed under it. A repair, as
                    # recovery's: written directly.
                    log.error("runs: run %d: %s was left %s", run.run_id, entry.name, previous)
                    new = "failed"
                entry.state = new
                entry.final = True
                if new == "carried_over":
                    entry.carried_over_out = True
                changed.append((entry, previous))
            counters = self._counters(run)
            outcome = run_outcome(end, [e.state for e in run.queue], counters.failed)
            reason = failure.reason if failure is not None else None
            try:
                api = await services.webapi_usage.finish_scope(ApiScope("run", run.run_id))
                api_counts: tuple[int | None, ...] = (api.requests, api.retried, api.rate_limited)
            except Exception:
                log.exception("runs: run %d's Web API counts can't be read", run.run_id)
                api_counts = (None, None, None)
            if run.state == "paused":
                await self._set_run_state(run, "stopping")  # a paused run ends through stopping
            check_run_transition(run.state, "ended")
            now = services.clock.now()

            def write(conn: Any) -> None:
                for entry, _ in changed:
                    conn.execute(
                        "UPDATE run_items SET state = ?, carried_over_out = ? WHERE id = ?",
                        (entry.state, int(entry.carried_over_out), entry.run_item_id),
                    )
                conn.execute(
                    "UPDATE runs SET state = 'ended', outcome = ?, reason = ?, ended_at = ?, "
                    "paused_reason = NULL, recorded = ?, skipped_duplicate = ?, "
                    "skipped_other = ?, failed = ?, bytes_added = ?, api_requests = ?, "
                    "api_retried = ?, api_rate_limited = ? WHERE id = ?",
                    (
                        outcome,
                        reason,
                        iso_ms(now),
                        counters.recorded,
                        counters.skipped_duplicate,
                        counters.skipped_other,
                        counters.failed,
                        counters.bytes_added,
                        *api_counts,
                        run.run_id,
                    ),
                )

            await services.store.transaction(write)
            previous_state = run.state
            run.state = "ended"
            run.paused_reason = None
            run.ended = True
            run.current = None
            self._run = None
            log.info(
                "runs: run %d ended %s%s: %d recorded, %d skipped, %d failed",
                run.run_id,
                outcome,
                f" ({reason}: {failure.message})" if failure is not None else "",
                counters.recorded,
                counters.skipped_duplicate + counters.skipped_other,
                counters.failed,
            )
            await self._set_run_active(False)
            for entry, previous in changed:
                self._publish_item_state(run, entry, previous)
            self._publish_run_state(run, previous_state)
            await self._publish_finished(run.run_id)
            self._idle.set()
        for entry, _ in changed:
            await self._publish_library(entry)

    async def _end_after_error(self, run: _Run) -> None:
        """A run whose driver raised: end it failed, by the book if possible, else as recovery
        would. Never raises (serve() must go on)."""
        await self._kill_orphans()
        try:
            await self._finish(run, "failed", None)
            return
        except Exception:
            log.exception("runs: run %d can't be ended normally; repairing its rows", run.run_id)
        await self._force_end(run)

    async def _force_end(self, run: _Run) -> None:
        """Ends the run as start-up recovery would (failed, container_restarted), without the
        driver: the SIGTERM bound passed, or the normal end failed. Never raises."""
        async with self._lock:
            if run.ended:
                return
            run.ended = True
            if self._run is run:
                self._run = None
        try:
            await fail_unfinished_run(self.services, run.run_id)
        except Exception:
            log.exception("runs: run %d's rows can't be repaired", run.run_id)
        await self._kill_orphans()
        await self._set_run_active(False)
        previous = run.state
        run.state = "ended"
        run.current = None
        self._publish_run_state(run, previous)
        await self._publish_finished(run.run_id)
        self._idle.set()

    # --- Changing the run (under the lock) -----------------------------------------------------

    async def _insert_run(
        self, trigger: Trigger, *, window: Window | None, requested: list[str] | None
    ) -> _Run:
        """The `runs` row of a new run, in state starting; serve() picks it up."""
        now = self.services.clock.now()
        now = now.replace(microsecond=now.microsecond // 1000 * 1000)  # as stored (iso_ms)
        window_start = iso_ms(window.start) if window is not None else None
        window_end = iso_ms(window.end) if window is not None and window.end is not None else None
        result = await self.services.store.execute(
            "INSERT INTO runs (kind, trigger, state, started_at, window_start, window_end, "
            "recorded, skipped_duplicate, skipped_other, failed, bytes_added) "
            "VALUES ('run', ?, 'starting', ?, ?, ?, 0, 0, 0, 0, 0)",
            (trigger, iso_ms(now), window_start, window_end),
        )
        assert result.lastrowid is not None
        run = _Run(
            run_id=result.lastrowid,
            trigger=trigger,
            started_at=now,
            window=window,
            requested=requested,
        )
        self._run = run
        self._idle.clear()
        log.info(
            "runs: run %d started (%s%s)",
            run.run_id,
            trigger,
            f", {len(requested)} item(s)" if requested else "",
        )
        await self._set_run_active(True)
        self._publish_run_state(run, None)
        self._created.set()
        return run

    async def _request_stop(self, run: _Run, request: StopRequest) -> None:
        """A stop: the run goes `stopping`, the current item hears of it, a waiting driver
        wakes. A later `now` upgrades an `after_track`; a shutdown's cause wins."""
        run.stop = _merge_stop(run.stop, request)
        run.stop_requested.set()
        if run.control is not None:
            run.control.request_stop(request)
        if run.state != "stopping":
            await self._set_run_state(run, "stopping")
        else:
            await self.services.store.execute(
                "UPDATE runs SET stop_mode = ? WHERE id = ?", (run.stop.mode, run.run_id)
            )
            self._publish_run_state(run, run.state)
        self._wake.set()

    async def _set_run_state(
        self, run: _Run, new: StoredRunState, *, paused_reason: PausedReason | None = None
    ) -> None:
        """Moves the run to `new` (states.RUN_TRANSITIONS), stores it and publishes it. Memory
        follows the database, so `active()` never shows a state that isn't stored yet."""
        previous = run.state
        check_run_transition(previous, new)
        reason = paused_reason if new == "paused" else None
        await self.services.store.execute(
            "UPDATE runs SET state = ?, paused_reason = ?, stop_mode = ? WHERE id = ?",
            (new, reason, run.stop.mode if run.stop else None, run.run_id),
        )
        run.state = new
        run.paused_reason = reason
        self._publish_run_state(run, previous)

    async def _force_items(self, run: _Run, ids: list[str]) -> list[str]:
        """createRun's items during a run: right after the current item, in the given order.
        Items already waiting move there; the current item, and items that already ended in
        this run (one row per item per run), are left as they are."""
        if not run.queue_built:
            # Still starting: they go first once the queue is built.
            added = [item_id for item_id in ids if item_id not in run.pending_forced]
            run.pending_forced += added
            return added
        chosen: list[_Entry] = []
        new_ids: list[str] = []
        for item_id in ids:
            entry = _find(run, item_id)
            if entry is None:
                new_ids.append(item_id)
            elif entry is not run.current and not entry.final and entry.state in WAITING_STATES:
                chosen.append(entry)
        carried = await run_queue.carried_over_ids(self.services)
        infos = await self._item_infos(new_ids)
        fresh = [
            _new_entry(infos[item_id], forced=True, carried_over_in=item_id in carried)
            for item_id in new_ids
            if item_id in infos
        ]
        await self._insert_entries(run, fresh)
        by_id = {entry.item_id: entry for entry in chosen + fresh}
        forced = [by_id[item_id] for item_id in ids if item_id in by_id]
        if not forced:
            return []
        for entry in forced:
            entry.forced = True
        # Right after the current item; with none, ahead of everything waiting.
        rest = [entry for entry in run.queue if entry not in forced]
        if run.current is not None and run.current in rest:
            at = rest.index(run.current) + 1
        else:
            at = next((i for i, e in enumerate(rest) if not e.final), len(rest))
        run.queue = rest[:at] + forced + rest[at:]
        await self._store_queue_order(run)
        log.info(
            "runs: run %d: %s added after the current item",
            run.run_id,
            ", ".join(entry.name for entry in forced),
        )
        self._publish_queue(run)
        return [entry.item_id for entry in forced]

    async def _reorder_waiting(
        self, run: _Run, groups: tuple[run_queue.RunOrderGroup, ...]
    ) -> None:
        """The run order setting changed during the run: it applies from the next item
        (web-ui.md § Run order). A paused run's item still goes first, forced items stay right
        after it, and re-queued interrupted items stay at the end; the rest is ordered again."""
        run.run_order = groups
        waiting = [entry for entry in run.queue if not entry.final]
        head = [run.current] if run.current is not None and run.current in waiting else []
        rest = [entry for entry in waiting if entry not in head]
        forced = [entry for entry in rest if entry.forced and entry.state == "up_next"]
        retries = [entry for entry in rest if entry.state == "interrupted"]
        plain = [entry for entry in rest if entry not in forced and entry not in retries]
        by_id = {entry.item_id: entry for entry in plain}
        ordered = run_queue.order_queue([_candidate(entry) for entry in plain], groups)
        plain = [by_id[candidate.item_id] for candidate in ordered]
        finished = [entry for entry in run.queue if entry.final]
        new_queue = finished + head + forced + plain + retries
        if new_queue == run.queue:
            return
        run.queue = new_queue
        await self._store_queue_order(run)
        log.info("runs: run %d: the run order changed; the queue follows it", run.run_id)
        self._publish_queue(run)

    # --- The database --------------------------------------------------------------------------

    async def _insert_entries(self, run: _Run, entries: list[_Entry]) -> None:
        """Inserts run_items rows for new entries and fills in their ids. queue_pos is set by
        `_store_queue_order` when they join the queue; until then they go last."""
        if not entries:
            return
        start = len(run.queue)

        def insert(conn: Any) -> list[int]:
            ids = []
            for offset, entry in enumerate(entries, start=1):
                cursor = conn.execute(
                    "INSERT INTO run_items (run_id, item_id, queue_pos, state, attempt, "
                    "carried_over_in, forced) VALUES (?, ?, ?, 'up_next', 1, ?, ?)",
                    (
                        run.run_id,
                        entry.item_id,
                        start + offset,
                        int(entry.carried_over_in),
                        int(entry.forced),
                    ),
                )
                ids.append(cursor.lastrowid)
            return ids

        for entry, row_id in zip(
            entries, await self.services.store.transaction(insert), strict=True
        ):
            entry.run_item_id = row_id

    async def _store_queue_order(self, run: _Run) -> None:
        def write(conn: Any) -> None:
            for position, entry in enumerate(run.queue, start=1):
                conn.execute(
                    "UPDATE run_items SET queue_pos = ?, forced = ? WHERE id = ?",
                    (position, int(entry.forced), entry.run_item_id),
                )

        await self.services.store.transaction(write)

    async def _store_counts(self, run: _Run, entry: _Entry) -> None:
        total = entry.total
        counters = self._counters(run)

        def write(conn: Any) -> None:
            conn.execute(
                "UPDATE run_items SET recorded = ?, skipped = ?, skipped_other = ?, failed = ?, "
                "bytes = ? WHERE id = ?",
                (
                    total.recorded,
                    total.skipped,
                    total.skipped_other,
                    total.failed,
                    total.bytes,
                    entry.run_item_id,
                ),
            )
            _write_run_counters(conn, run.run_id, counters)

        await self.services.store.transaction(write)

    async def _store_report(
        self, run: _Run, entry: _Entry, report: ItemReport, *, requeue: bool
    ) -> None:
        total = entry.total
        counters = self._counters(run)
        ended = report.outcome not in ("device_busy",)
        timings = json.dumps(report.timings.to_json())

        def write(conn: Any) -> None:
            conn.execute(
                "UPDATE run_items SET state = ?, attempt = ?, mode = ?, planned = ?, "
                "up_to_date_by = ?, interrupted_count = ?, interrupted_by = ?, "
                "carried_over_out = ?, recorded = ?, skipped = ?, skipped_other = ?, "
                "failed = ?, bytes = ?, ended_at = coalesce(?, ended_at), reason = ?, "
                "recorder_exit_code = ?, error_code = ?, timings = ? WHERE id = ?",
                (
                    entry.state,
                    entry.attempt,
                    entry.mode,
                    entry.planned,
                    report.up_to_date_by,
                    entry.interrupted_count,
                    entry.interrupted_by,
                    int(entry.carried_over_out),
                    total.recorded,
                    total.skipped,
                    total.skipped_other,
                    total.failed,
                    total.bytes,
                    iso_ms(report.timings.ended_at) if ended else None,
                    entry.reason,
                    report.recorder_exit_code,
                    report.error_code,
                    timings,
                    entry.run_item_id,
                ),
            )
            if requeue:
                for position, other in enumerate(run.queue, start=1):
                    conn.execute(
                        "UPDATE run_items SET queue_pos = ? WHERE id = ?",
                        (position, other.run_item_id),
                    )
            _write_run_counters(conn, run.run_id, counters)

        await self.services.store.transaction(write)

    async def _item_infos(self, ids: list[str]) -> dict[str, "_ItemInfo"]:
        """What the queue shows of these items: name, kind, cover, and what to expect."""
        if not ids:
            return {}
        rows = await self.services.store.fetchall(
            "SELECT id, kind, uri, name, item_access, thumb_path, image_id, changed_at, "
            "added_at FROM items "
            "WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(ids),),
        )
        try:
            counts = await self.services.matching.item_counts(ids)
        except Exception:
            log.exception("runs: the queue's track counts can't be read")
            counts = {}
        infos: dict[str, _ItemInfo] = {}
        for row in rows:
            item_id = row["id"]
            kind = row["kind"]
            item_counts = counts.get(item_id)
            infos[item_id] = _ItemInfo(
                item_id=item_id,
                kind=kind,
                name=row["name"],
                uri=row["uri"],
                cover=cover_url(
                    "albums" if kind == "album" else "library",
                    item_id,
                    row["thumb_path"],
                    row["image_id"],
                ),
                item_access=bool(row["item_access"]),
                missing=(
                    item_counts.total - item_counts.recorded if item_counts is not None else None
                ),
                changed_at=row["changed_at"],
                added_at=row["added_at"],
            )
        return infos

    async def _check_items_exist(self, ids: list[str]) -> None:
        rows = await self.services.store.fetchall(
            "SELECT id FROM items WHERE removed_at IS NULL "
            "AND id IN (SELECT value FROM json_each(?))",
            (json.dumps(ids),),
        )
        found = {row["id"] for row in rows}
        unknown = [item_id for item_id in ids if item_id not in found]
        if unknown:
            raise not_found("No such item in the Library or Albums.", {"ids": unknown})

    async def _quick_checks(self) -> None:
        """createRun's 409s, answered at once (openapi.yaml createRun)."""
        services = self.services
        if not await services.setup.is_complete():
            raise ApiError(409, "setup_incomplete", "Finish setup before running a backup.")
        held = await services.connection.held_reason()
        if held == "connection_expired":
            raise ApiError(
                409, "connection_expired", "The Spotify connection expired. Reconnect to run."
            )
        if held == "not_connected":
            raise ApiError(409, "not_connected", "The Spotify Web API isn't connected.")
        status = await services.client.status()
        if not status.installed:
            raise ApiError(409, "client_not_installed", "The Spotify client isn't installed.")
        if status.running and not status.logged_in:
            raise ApiError(409, "client_logged_out", "The Spotify client is logged out.")

    # --- Helpers -------------------------------------------------------------------------------

    def _require_run(self) -> _Run:
        run = self._run
        if run is None:
            raise ApiError(409, "no_run", "No backup is running.")
        return run

    def _current_for(self, job: ItemJob) -> tuple[_Run, _Entry] | None:
        """The run and entry an item engine's call is about, if it's still the current one."""
        run = self._run
        if run is None or run.run_id != job.run_id or run.engine is None:
            return None
        entry = run.current
        if entry is None or entry.run_item_id != job.run_item_id:
            return None
        return run, entry

    def _job(self, run: _Run, entry: _Entry) -> ItemJob:
        """The ItemJob of an entry's next attempt. Attempt 2 gets its own log and events files:
        spytifyd appends to them, and the item engine reads the events file back."""
        config = self.services.config
        assert run.device is not None and run.device.id is not None
        stem = f"{run.run_id}-{entry.item_id}"
        if entry.attempt > 1:
            stem += f"-{entry.attempt}"
        if entry.kind in ("followed", "linked"):
            snapshot_unread = run.refresh_failed or entry.item_id in run.snapshots_unread
        else:
            snapshot_unread = False
        return ItemJob(
            run_id=run.run_id,
            run_item_id=entry.run_item_id,
            item_id=entry.item_id,
            kind=entry.kind,
            name=entry.name,
            context_uri=entry.context_uri,
            attempt=entry.attempt,
            snapshot_unread=snapshot_unread,
            device_id=run.device.id,
            log_file=config.spytify_logs_dir / f"{stem}.log",
            events_file=config.spytify_logs_dir / f"{stem}.events.jsonl",
            socket_path=config.runtime_dir / f"spytify-{run.run_id}-{run.attempts}.sock",
            work_dir=config.runtime_dir / "spytify-cwd",
        )

    def _live(self, run: _Run) -> ItemLive | None:
        engine = run.engine
        if engine is None:
            return None
        try:
            return engine.live()
        except Exception:
            log.debug("runs: the item engine's live view failed", exc_info=True)
            return None

    def _counters(self, run: _Run) -> Counters:
        recorded = skipped_duplicate = skipped_other = failed = size = 0
        for entry in run.queue:
            total = entry.total
            recorded += total.recorded
            skipped_duplicate += total.skipped_duplicate
            skipped_other += total.skipped_other
            failed += total.failed
            size += total.bytes
        return Counters(
            recorded=recorded,
            skipped_duplicate=skipped_duplicate,
            skipped_other=skipped_other,
            failed=failed,
            bytes_added=size,
        )

    def _summary(self, run: _Run, state: RunState | None = None) -> RunSummary:
        return RunSummary(
            id=run.run_id,
            trigger=run.trigger,
            state=state if state is not None else api_run_state(run.state),
            started_at=run.started_at,
            window_end=run.window.end if run.window is not None else None,
            paused_reason=run.paused_reason,
            stop_mode=run.stop.mode if run.stop is not None else None,
            counters=self._counters(run),
        )

    def _queue_item(self, entry: _Entry) -> QueueItem:
        total = entry.total
        return QueueItem(
            item_id=entry.item_id,
            kind=entry.kind,
            name=entry.name,
            cover=entry.cover,
            state=entry.state,
            attempt=entry.attempt,
            planned=entry.planned,
            expect=_expect(entry),
            counts=QueueItemCounts(
                recorded=total.recorded, skipped=total.skipped, failed=total.failed
            ),
            badges=item_badges(
                entry.state,
                interrupted_count=entry.interrupted_count,
                carried_over_in=entry.carried_over_in,
                carried_over_out=entry.carried_over_out,
            ),
            reason=entry.reason,
        )

    def _display_queue(self, run: _Run) -> list[QueueItem]:
        """Finished items first (in the order they ran, then the ones that never ran), then the
        current one, then Up next and interrupted ones in queue order."""
        current = run.current
        finished = [e for e in run.queue if e.final and e is not current]
        ran = sorted((e for e in finished if e.ran_order is not None), key=_ran_order)
        never_ran = [e for e in finished if e.ran_order is None]
        waiting = [e for e in run.queue if not e.final and e is not current]
        shown = ran + never_ran + ([current] if current is not None else []) + waiting
        return [self._queue_item(entry) for entry in shown]

    def _counters_changed(self, run: _Run) -> None:
        """A `run.state` for new counters now, or within the second (events.md)."""
        now = self.services.clock.monotonic()
        sent = run.counters_sent_at
        if sent is None or now - sent >= COUNTERS_INTERVAL_S:
            self._publish_run_state(run, run.state)
        else:
            run.counters_dirty = True
            self._counters_due.set()

    async def _flush_counters(self, run: _Run) -> None:
        """Sends the held-back counters once their second is over. Runs beside each item."""
        clock = self.services.clock
        while True:
            await self._counters_due.wait()
            self._counters_due.clear()
            sent = run.counters_sent_at or clock.monotonic()
            await clock.sleep(max(0.0, sent + COUNTERS_INTERVAL_S - clock.monotonic()))
            async with self._lock:
                if run.counters_dirty and not run.ended:
                    self._publish_run_state(run, run.state)

    async def _take_playback_back(self, run: _Run) -> None:
        """Resume: pauses another device that's playing, so the item's own D6 check lets it
        start, and its play moves playback to our device. A Web API failure is logged: the item
        then finds the device busy, and the run pauses again."""
        scope = ApiScope("run", run.run_id)
        webapi = self.services.ports.webapi
        ours = run.device.id if run.device is not None else None
        try:
            state = await webapi.player_state(scope=scope)
            if state is None or not state.is_playing or state.device is None:
                return
            if state.device.id is None or state.device.id == ours:
                return
            log.info("runs: run %d: pausing %s to resume", run.run_id, state.device.name)
            await webapi.pause(device_id=state.device.id, scope=scope)
        except WebApiError as exc:
            log.warning("runs: run %d: taking playback back failed: %s", run.run_id, exc)

    async def _active_device(self, run: _Run) -> Device | None:
        """The device playing now, for a device.moved the item engine named no device for."""
        try:
            state = await self.services.ports.webapi.player_state(scope=ApiScope("run", run.run_id))
        except WebApiError:
            return None
        return state.device if state is not None else None

    async def _wait_until_idle(self, seconds: float) -> bool:
        """Waits until no run is going, at most `seconds`: of services.clock, or of real time,
        whichever passes first. docker's grace is real time; services.clock lets tests (and a
        faster fake world) see the bound, and the real-time one keeps a fake clock nobody moves
        from waiting forever. True if idle."""
        if self._idle.is_set():
            return True
        async with asyncio.TaskGroup() as group:
            waits = [
                group.create_task(self._idle.wait()),
                group.create_task(self.services.clock.sleep(seconds)),
                group.create_task(asyncio.sleep(seconds)),
            ]
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            for task in waits:
                task.cancel()  # the ones still waiting: the group awaits them
        return self._idle.is_set()

    async def _kill_orphans(self) -> None:
        try:
            killed = await self.services.ports.recorder.kill_orphans()
        except Exception:
            log.exception("runs: looking for leftover recorders failed")
            return
        if killed:
            log.warning("runs: killed %d leftover recorder(s)", killed)

    async def _set_run_active(self, active: bool) -> None:
        try:
            await self.services.client.set_run_active(active)
        except Exception:
            log.exception("runs: the client's run flag couldn't be set to %s", active)

    # --- Events --------------------------------------------------------------------------------

    def _publish_run_state(self, run: _Run, previous: StoredRunState | None) -> None:
        """`run.state`: the RunSummary plus previous_state (idle before the first one)."""
        data = self._summary(run).model_dump(mode="json")
        data["previous_state"] = api_run_state(previous) if previous is not None else "idle"
        self.services.bus.publish("run.state", data)
        run.counters_sent_at = self.services.clock.monotonic()
        run.counters_dirty = False

    def _publish_item_state(self, run: _Run, entry: _Entry, previous: ItemState) -> None:
        self.services.bus.publish(
            "item.state",
            {"run_id": run.run_id, "item": self._queue_item(entry), "previous_state": previous},
        )

    def _publish_queue(self, run: _Run) -> None:
        self.services.bus.publish(
            "run.queue", {"run_id": run.run_id, "queue": self._display_queue(run)}
        )

    def _publish_device_moved(
        self, run: _Run, device: Device | None, *, item_id: str | None, take_id: str | None
    ) -> None:
        shown = (
            {"id": device.id, "name": device.name, "type": device.type}
            if device is not None
            else {"id": None, "name": "another device", "type": "Unknown"}
        )
        self.services.bus.publish(
            "device.moved",
            {
                "run_id": run.run_id,
                "item_id": item_id,
                "device": shown,
                "discarded_take_id": take_id,
            },
        )

    async def _publish_finished(self, run_id: int) -> None:
        """`run.finished` with History's row. A failure is logged: the run has ended anyway."""
        try:
            row = await self.services.history.history_row(run_id)
        except Exception:
            log.exception("runs: run %d's History row can't be read for run.finished", run_id)
            return
        self.services.bus.publish("run.finished", {"run": row})

    async def _publish_library(self, entry: _Entry) -> None:
        """`library.item` or `album.item` (throttled by those modules; they never raise)."""
        if entry.kind == "album":
            await self.services.albums.publish(entry.item_id)
        else:
            await self.services.library.publish(entry.item_id)


# --- Plain helpers ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ItemInfo:
    item_id: str
    kind: ItemKind
    name: str
    uri: str
    cover: str | None
    item_access: bool
    missing: int | None  # tracks not in the index yet; None without a track list
    changed_at: str | None
    added_at: str


def _new_entry(info: _ItemInfo, *, forced: bool, carried_over_in: bool) -> _Entry:
    return _Entry(
        run_item_id=0,  # set once its row is in
        item_id=info.item_id,
        kind=info.kind,
        name=info.name,
        context_uri=info.uri,
        cover=info.cover,
        item_access=info.item_access,
        expect_count=info.missing,
        changed_at=info.changed_at,
        added_at=info.added_at,
        forced=forced,
        carried_over_in=carried_over_in,
    )


def _candidate(entry: _Entry) -> run_queue.Candidate:
    return run_queue.Candidate(
        item_id=entry.item_id,
        kind=entry.kind,
        changed_at=entry.changed_at,
        added_at=entry.added_at,
        carried_over=entry.carried_over_in,
    )


def _find(run: _Run, item_id: str) -> _Entry | None:
    return next((entry for entry in run.queue if entry.item_id == item_id), None)


def _next_waiting(run: _Run) -> _Entry | None:
    """The next item to run: the first waiting one in queue order (a takeover's item kept its
    place at the head, so Resume restarts it first)."""
    return next(
        (e for e in run.queue if not e.final and e.state in WAITING_STATES),
        None,
    )


def _ran_order(entry: _Entry) -> int:
    return entry.ran_order or 0


def _expect(entry: _Entry) -> QueueItemExpect:
    """The Up next row's "84 new" (playlists), "11 tracks" (albums) or "checking" (no track
    list: followed and linked playlists)."""
    count = entry.planned if entry.planned is not None else entry.expect_count
    if not entry.item_access or entry.mode == "whole" or count is None:
        return QueueItemExpect(kind="checking", count=None)
    kind: Literal["tracks", "new_tracks"] = "tracks" if entry.kind == "album" else "new_tracks"
    return QueueItemExpect(kind=kind, count=count)


def _merge_stop(current: StopRequest | None, new: StopRequest) -> StopRequest:
    """As ItemControl.request_stop: the mode only goes up, and a shutdown's cause wins."""
    if current is None:
        return new
    mode: StopMode = "now" if "now" in (current.mode, new.mode) else "after_track"
    cause = "shutdown" if "shutdown" in (current.cause, new.cause) else current.cause
    return StopRequest(mode=mode, cause=cause)


def _end_for_stop(stop: StopRequest | None) -> tuple[RunEnd | None, RunFailure | None]:
    """How a stop ends the run: a user's stop → stopped, a window's end → window_ended, the
    controller stopping → failed (container_restarted). (None, None) without a stop."""
    if stop is None:
        return None, None
    if stop.cause == "shutdown":
        return "failed", RunFailure("container_restarted", "The container is stopping.")
    if stop.cause == "window_end":
        return "window_ended", None
    return "stopped", None


def _default_reason(entry: _Entry, report: ItemReport) -> str | None:
    """A reason in English when the item engine gave none, for the outcomes that need one."""
    if report.outcome == "interrupted":
        if report.interrupted_by == "takeover":
            name = report.takeover.device.name if report.takeover else "another device"
            return f"Playback moved to {name}."
        if report.interrupted_by == "shutdown":
            return "The container stopped."
        if entry.state == "partial":
            return "Interrupted twice."
        return "Playback paused for more than 20 s."
    if report.run_failure is not None:
        return report.run_failure.message
    return None


def _crash_report(started: datetime, ended: datetime) -> ItemReport:
    """The report of an item whose engine raised: failed, with what's known."""
    return ItemReport(
        outcome="failed",
        counts=TrackCounts(),
        timings=ItemTimings(started_at=started, ended_at=ended, phase_s={}),
        reason="The controller hit an internal error; see its log.",
    )


def _write_run_counters(conn: Any, run_id: int, counters: Counters) -> None:
    conn.execute(
        "UPDATE runs SET recorded = ?, skipped_duplicate = ?, skipped_other = ?, failed = ?, "
        "bytes_added = ? WHERE id = ?",
        (
            counters.recorded,
            counters.skipped_duplicate,
            counters.skipped_other,
            counters.failed,
            counters.bytes_added,
            run_id,
        ),
    )
