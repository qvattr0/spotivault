"""What passes between the run engine and the item engine (plan § Item states, § Run states).

**Frozen (S6 foundation).** engine-run builds an `ItemJob` and an `ItemControl`, and implements
`ItemHost`; engine-item runs the item and returns an `ItemReport`. Neither reaches into the
other's objects otherwise.

    control = ItemControl()
    engine = ItemEngine(services, job, host=self, control=control)   # engine/item.py
    report = await engine.run()        # meanwhile: control.request_stop(...), engine.live()

Who writes what:
- **engine-item** writes `track_results` and `files` rows for its takes, `observed_tracks` and
  `items.last_full_pass_*` after a clean whole pass (D13), `items.last_backup_at` and
  `items.completed_at` (albums), relays Spytify's events (`track.*`, `session.state`, `level`,
  Spytify's `error`s and the controller's item-level ones), and writes the item's `.m3u` through
  `services.files`.
- **engine-run** writes `runs` and `run_items` (state, queue, counts, timings), and publishes
  `run.state`, `run.queue`, `item.state`, `run.finished`, `device.moved` and run-level `error`s.
  It learns about the current item only through ItemHost calls and the final ItemReport.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from spotivault.api.models import NowPlaying, RunTrack
from spotivault.clock import iso_ms
from spotivault.engine.states import ItemState
from spotivault.ports import Device

type PlayMode = Literal["missing_only", "whole"]  # D1 (settings.PlayMode)
type ItemKind = Literal["owned", "liked", "followed", "linked", "album"]
type StopMode = Literal["after_track", "now"]
type StopCause = Literal[
    "user",  # Stop after this track / Stop now (POST /api/runs/current/stop)
    "window_end",  # the scheduler: the window ended or its hour was turned off
    "shutdown",  # SIGTERM: Stop now, the current item ends `interrupted`
]
type SessionState = Literal["idle", "waiting", "recording", "ad", "paused", "stopping"]

# The controller's own `error` codes (contracts/events.md, `error.code` for source controller).
type ControllerErrorCode = Literal[
    "recorder_exit",
    "recorder_timeout",
    "steering_guard",
    "loop_guard",
    "context_changed",
    "webapi",
    "storage",
    "client_restarted",
]

# Machine reasons for a failed run (contracts/schema.sql runs.reason; HistoryRow.reason).
type RunFailureReason = Literal[
    "container_restarted",
    "setting_drifted",
    "client_logged_out",
    "connection_expired",
    "not_connected",
    "setup_incomplete",
    "storage",
    "device_missing",
    "recorder",
    "webapi",
]


# --- Timeouts (plan § Item states) -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Timeouts:
    """Every timeout of one item, in seconds. Tests pass shorter ones; the defaults are the
    plan's. All waits run on services.clock."""

    socket_s: float = 15.0  # the recorder's socket appears (RecorderSpec.socket_timeout_s)
    idle_exit_s: int = 20  # spytifyd --idle-exit
    wait_target_s: int = 60  # spytifyd --wait-target
    first_track_replay_s: float = 30.0  # no track.started yet: issue the play again
    first_track_give_up_s: float = 90.0  # still none: give up (SIGTERM, the item fails)
    finishing_extra_s: float = 40.0  # finishing may last idle_exit_s + this, then SIGTERM
    item_max_factor: float = 1.25  # the whole item: factor × planned length …
    item_max_extra_s: float = 600.0  # … + 10 min (a whole item: no planned length, see item.py)
    sigterm_first_grace_s: float = 45.0  # SIGTERM → this → SIGTERM again
    sigterm_second_grace_s: float = 15.0  # → this → SIGKILL
    stall_s: float = 20.0  # paused by someone else this long mid-item: interrupted
    webapi_check_s: float = 60.0  # D10: GET /me/player at track start, on pause and this often


# --- Run engine → item engine ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ItemJob:
    """One attempt at one item: everything the item engine needs that the run engine knows.

    The item engine reads the rest itself: the item's `items` row and track list, the matching
    index, settings.recorder_settings(mode), the player."""

    run_id: int
    run_item_id: int  # run_items.id
    item_id: str  # items.id: a playlist or album id, or "liked"
    kind: ItemKind
    name: str
    context_uri: str  # what to play: items.uri; Liked Songs: spotify:user:<id>:collection
    attempt: int  # 1, or 2 after an interruption
    snapshot_unread: bool  # D13 can't skip it: this run's refresh didn't read its snapshot_id
    device_id: str  # our Connect device's id, from the pre-run check
    log_file: Path  # /config/logs/spytify/<run>-<item>.log
    events_file: Path  # /config/logs/spytify/<run>-<item>.events.jsonl
    socket_path: Path  # <runtime_dir>/spytify-<run>-<n>.sock: short (107 bytes at most)
    work_dir: Path  # an empty folder for spytifyd's cwd
    timeouts: Timeouts = field(default_factory=Timeouts)


@dataclass(frozen=True, slots=True)
class StopRequest:
    """A stop the run engine passes to the current item. `mode` only ever goes up, from
    after_track to now (openapi.yaml stopCurrentRun: "Sending now after after_track upgrades")."""

    mode: StopMode
    cause: StopCause


class ItemControl:
    """The run engine's line to the running item. The item engine waits on `changed()` next to
    its other waits (asyncio.wait with FIRST_COMPLETED), and reads `stop` when it fires.

    - after_track: let the current take finish (session.stop {now: false} or one SIGTERM), then
      end the item; before the recorder started, end at once. Outcome: stopped (cause user),
      carried_over (window_end).
    - now: the current take is discarded (session.stop {now: true}; its track result is
      `skipped`, reason `discarded`: not a failure). Outcome: stopped, carried_over, or
      interrupted (shutdown).
    """

    def __init__(self) -> None:
        self.stop: StopRequest | None = None
        self._changed = asyncio.Event()

    def request_stop(self, request: StopRequest) -> None:
        """Asks the item to stop. A later `now` upgrades an `after_track`; the cause of a
        shutdown wins over the others (the item must end `interrupted`)."""
        current = self.stop
        if current is None:
            self.stop = request
        else:
            mode: StopMode = "now" if "now" in (current.mode, request.mode) else "after_track"
            cause = "shutdown" if "shutdown" in (current.cause, request.cause) else current.cause
            self.stop = StopRequest(mode=mode, cause=cause)
        self._changed.set()

    async def changed(self) -> StopRequest:
        """Waits until a stop is requested (returns at once if one already was)."""
        await self._changed.wait()
        assert self.stop is not None
        return self.stop


# --- Item engine → run engine, while the item runs ---------------------------------------------


@dataclass(frozen=True, slots=True)
class TrackCounts:
    """An item's distinct-track counts, not raw events (FINDINGS: one run counted 10 skips for a
    5-track album). A track is counted once, under its last result in this attempt."""

    recorded: int = 0
    skipped_duplicate: int = 0
    skipped_other: int = 0  # ads and Spytify's other skip reasons
    failed: int = 0
    bytes: int = 0  # of counted files

    @property
    def skipped(self) -> int:
        return self.skipped_duplicate + self.skipped_other


class ItemHost(Protocol):
    """What the item engine tells the run engine while it runs. The run engine implements it;
    item tests use a recording stub. Both are awaited in order and must return quickly."""

    async def item_phase(
        self,
        job: ItemJob,
        phase: ItemState,
        *,
        mode: PlayMode | None = None,
        planned: int | None = None,
    ) -> None:
        """The item entered `phase` (one of states.ACTIVE_STATES, in order; `mode` and
        `planned` are known from `preflight` on: planned None for a whole item). The run engine
        checks the transition, stores run_items.state (and mode, planned, started_at), publishes
        `item.state`, and moves the run between running and finishing."""
        ...

    async def item_counts(self, job: ItemJob, counts: TrackCounts) -> None:
        """The item's counts changed (a take finished, was skipped or failed). The run engine
        stores them, updates the run's counters (`run.state` at most once a second for counters
        alone) and publishes `library.item` / `album.item`."""
        ...

    async def item_take_started(self, job: ItemJob) -> None:
        """A planned take started (one the item plays on: a whole item's, or a planned track).
        The run engine works its time left out again, so the take counts from its start; it
        stores nothing."""
        ...


@dataclass(frozen=True, slots=True)
class MissingTrack:
    """A track still to record, for the run's time left (engine/time_left.py)."""

    key: str  # Spytify's track key: a track two items share is recorded once
    duration_ms: int  # tracks.duration_ms, as stored


@dataclass(frozen=True, slots=True)
class ItemLeft:
    """What's left of the current item to play, from its plan, for the run's time left
    (RunSummary.time_left; engine/time_left.py sums it)."""

    take_ms: int  # the rest of the take recording now, if it plays on (a planned one); else 0
    take_key: str | None  # that take's Spytify key
    tracks: tuple[MissingTrack, ...] | None  # planned and not started yet; None: it plays whole
    # The Spytify keys this attempt has recorded so far, counting a planned take that played
    # and waits for its result (TakeBook.done_keys): a waiting item that lists them won't
    # record them again.
    done_keys: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ItemLive:
    """The current item, live, for GET /api/status and GET /api/runs/current. Built by the
    item engine from what it has; never touches the database."""

    phase: ItemState
    session_state: SessionState | None  # Spytify's, relayed; None before the recorder started
    now_playing: NowPlaying | None  # the take being recorded
    tracks: tuple[RunTrack, ...]  # the live track table (CurrentRun.current_tracks)
    left: ItemLeft | None = None  # what's left to play; None until it's planned


# --- Item engine → run engine, at the end ------------------------------------------------------

# How an attempt ended. The run engine turns it into the item's state (states.py):
# interrupted on attempt 2 → partial; device_busy → back to up_next with the run paused (D6).
type ItemOutcome = Literal[
    "done",
    "up_to_date",
    "partial",
    "stopped",
    "carried_over",
    "failed",
    "unavailable",
    "interrupted",
    "device_busy",
]

type InterruptedBy = Literal["stall", "takeover", "shutdown"]


@dataclass(frozen=True, slots=True)
class Takeover:
    """Playback moved to another device mid-item: the run pauses (`device.moved`)."""

    device: Device
    discarded_take_id: str | None  # the take cut short, if one was recording


@dataclass(frozen=True, slots=True)
class RunFailure:
    """The whole run must end `failed` (a recorder exit 2 or 1 with fail_run, our device gone,
    no space). The item itself ends `failed`."""

    reason: RunFailureReason
    message: str  # English, for the log and the `error` event


@dataclass(frozen=True, slots=True)
class ItemTimings:
    """Where an attempt's time went, for S10's long-run analysis (run_items.timings, JSON) and
    the backlog estimate's 35 s per item. Times are UTC from services.clock."""

    started_at: datetime  # planning began
    ended_at: datetime
    phase_s: Mapping[ItemState, float]  # seconds spent in each active phase
    recorder_started_at: datetime | None = None
    first_track_at: datetime | None = None  # the first track.started
    finishing_at: datetime | None = None
    recorder_exit_at: datetime | None = None
    planned_ms: int | None = None  # the planned tracks' length; None for a whole item

    def to_json(self) -> dict[str, object]:
        """For run_items.timings (migration 003): seconds and RFC 3339 strings."""

        def at(moment: datetime | None) -> str | None:
            return iso_ms(moment) if moment is not None else None

        return {
            "started_at": at(self.started_at),
            "ended_at": at(self.ended_at),
            "phase_s": {phase: round(seconds, 3) for phase, seconds in self.phase_s.items()},
            "recorder_started_at": at(self.recorder_started_at),
            "first_track_at": at(self.first_track_at),
            "finishing_at": at(self.finishing_at),
            "recorder_exit_at": at(self.recorder_exit_at),
            "planned_ms": self.planned_ms,
        }


@dataclass(frozen=True, slots=True)
class ItemReport:
    """How one attempt ended. Everything the run engine needs to set the item's final row, the
    run's counters, and what happens to the run next."""

    outcome: ItemOutcome
    counts: TrackCounts
    timings: ItemTimings
    mode: PlayMode | None = None  # None when planning didn't get that far
    planned: int | None = None  # tracks planned (missing_only); None for whole or unknown
    up_to_date_by: Literal["nothing_missing", "d13_unchanged"] | None = None
    still_missing: int | None = None  # planned tracks still not in the index afterwards
    reason: str | None = None  # English, for QueueItem.reason ("2 tracks failed: low volume")
    error_code: ControllerErrorCode | None = None  # set when the controller stepped in
    run_failure: RunFailure | None = None
    interrupted_by: InterruptedBy | None = None  # with outcome interrupted
    takeover: Takeover | None = None  # with interrupted_by takeover
    device_busy: Device | None = None  # with outcome device_busy (D6)
    recorder_exit_code: int | None = None
    clean_full_pass: bool = False  # a whole item played through cleanly: D13 rows were written
