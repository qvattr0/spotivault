"""One item, from planning to its outcome (plan § Item states; design.md § Run flow).

Owner: **engine-item** (controller/ARCHITECTURE.md § S6's parts). Frozen interface: the
`ItemEngine` constructor, `run()`, `live()` and `recorder_pid`; engine/types.py and
engine/states.py are the shared types. planning.py, steering.py and item_takes.py are this
builder's too.

Specs, in order of authority: design.md § Run flow (all of it) and § Container (Spytify
defaults); docs/upstream/spytify-bugs.md (the workarounds: skip-forward off, seek to 0, pause after
the exit, distinct-track counts, the loop guard); web-ui.md § Dashboard (Running, Warnings during
a run); contracts/events.md (`track.*`, `session.state`, `level`, `error`); prototype/FINDINGS.md
and probe.py `cmd_record` (`steer`, `loaded_positions`, `handle`, the poll loop, `still_missing`).

**The phases** (each reported to `host.item_phase` as it starts):

1. `planning` (planning.py): the stored track list and the matching index decide what's missing.
   Nothing missing (or D13 unchanged) → up_to_date, no recorder. Removed or gone → unavailable.
2. `preflight`: our Connect device must be listed (else failed, RunFailure device_missing);
   another device playing → `device_busy` (D6: never take playback; the run engine pauses the
   run); /music must pass the storage check (else failed, RunFailure storage).
3. `preparing`: pause our device if preflight's GET /me/player said something plays (with nothing
   playing, Spotify answers a pause 403 "Restriction violated"), then seek to 0, shuffle off,
   repeat off (Spytify bug 2: no track may be "already playing" past 300 ms). "Player command
   failed" answers (403, 404) are harmless.
4. `starting`: stale WAVs in `.spytify/` cleaned up (bug 4; the whole music folder after a
   recorder was killed, for bug 5's .part files), then spytifyd started with
   `settings.recorder_settings(mode)` (skip-forward off for missing_only, on for whole). A start
   error goes through `protocol.classify_exit`: fail_run fails the run, retry_once kills orphans
   and starts once more, fail_item fails the item. Then `player.control full_volume`.
5. `playing`: one play of the context, at the first missing track by URI (S0 row 19). Then one
   loop reacts, one input at a time, to the recorder's notifications, MPRIS changes, a stop from
   the run engine, and the timers (see "The play loop" below).
6. `finishing`: playback is over (the plan is done, the context ended, a stop, a guard): the
   player is paused and the recorder's idle exit comes 20–27 s later. Then every notification is
   read, the --events file fills in what the socket lost, the player is paused again if bug 1's
   Next restarted it, the index is read again (`still_missing`), the item's rows are written
   (last_backup_at, an album's completed_at, D13's rows after a clean whole pass), and the .m3u.
7. **Outcome** (`_decide`, in this order): unavailable or failed during the play; done when
   nothing planned is missing any more; failed on an unexpected recorder exit; stopped,
   carried_over or interrupted (shutdown) by the stop's cause; interrupted by a takeover or a
   stall; partial for a capture problem, a fatal Spytify error, the time limit, failed takes or
   tracks still missing (whole items also: the context moved on, or the loop guard paused before
   the context went round); else done.

**The play loop.** Three watcher tasks feed one inbox: the recorder's notifications (read all the
time: spytifyd drops a client 512 lines behind), MPRIS changes, and the run engine's stop. The
loop takes one input at a time, so steering decisions never race each other. Timers are
deadlines in `_deadlines` (monotonic seconds on services.clock); the loop wakes for the earliest:

| Deadline | Armed | When it passes |
|---|---|---|
| first_track_replay | the play | no track.started yet: play again |
| first_track_give_up | the play | still none: SIGTERM, failed `recorder_timeout` |
| item_max | the play | 1.25 × planned length + 10 min: session.stop after the take, partial |
| item_max_stop | item_max | the take's end + 30 s, and still running: SIGTERM |
| webapi_check | the play, then every 60 s | GET /me/player: takeover or context moved on (D10) |
| player_recheck | a mismatch before the state caught up | GET /me/player again (2 s, 3 times) |
| stall_exit | an unexplained pause | the recorder should have exited by now: SIGTERM |
| finishing | playback over | idle exit + 40 s and still running: SIGTERM |

D10's other checks: GET /me/player at a track's start (at most every 5 s) and on a pause.

`terminate()` itself escalates: SIGTERM → 45 s → SIGTERM → 15 s → SIGKILL. When signals stand in
for `session.stop {now: false}` (no answer, or the socket is gone), the first wait is at least
the take's end + 30 s, so the take playing is finished as asked.

**Pauses nobody here asked for:** GET /me/player tells a takeover (another device is active:
`session.stop {now}`, outcome interrupted) from the rest. Spotify's end of the context is a pause
within 1.5 s of the start of the context's first track (it loads track 1 and pauses at 0): the
item's first playable entry (missing_only) or the first track heard (whole), by MPRIS's metadata,
read again when it arrives late. That's finishing, and a whole item's pass was heard to its end.
Any other pause is a stall: outcome interrupted if the recorder's idle exit ends the session while
still paused. While GET /me/player is read again (below), a pause is judged only after the reads.

**GET /me/player lags a play.** For a moment after our play, Spotify can still report the player
as it was before: the context played last (a real run read the album of two runs before, 1.3 s
after the play answered), or the device that was active then. So until a read has shown our
device on the item's context (`_caught_up`), a takeover by the device the pre-flight's read
reported, or that read's context, isn't acted on at once. Any other device or context can't be
the old state, so it's acted on at once, as before. For the old state:
- **MPRIS vouches** at a track's start and at the 60 s check: when the take playing is one of the
  item's tracks by MPRIS's id (D10), the context hasn't moved on. Never at a pause: a takeover
  pauses our player, and the old state could hide it.
- **Otherwise it's read again** (`player_recheck`): 2 s later, 3 times at most. A read that
  agrees ends it, and a new device or context is acted on at once. One that still reports the
  old state after the last is taken as true (the state had 6 s to catch up) and acted on, but a
  context change MPRIS vouches against is let go.
- **A pause during the re-reads** isn't taken for the end of the context until they're over
  (`_judge_pause`): a takeover in the first 1.5 s of the first track looks just like it.
- **Liked Songs' own alias,** when it was the context before the play, is learned from a read
  naming the take playing now, which isn't the track loaded before the play: that read is new.
- **The take** stays as steering marked it while the check waits.
Once the state has caught up, a mismatch is acted on at once, as before. So real autoplay is
still stopped at the radio's first track, its context being new; only the context that was
playing before the play waits for the re-reads, 6 s at most.

**Stops:** after this track is `session.stop {now: false}`. Stop now is `{now: true}` (the take is
discarded: skipped, not failed), except while finishing: playback is over, and the take waiting
for the idle exit (often the last track, played in full) would be rejected by a stop now, so it's
`{now: false}` too and the recorder saves it at the idle exit (20–27 s after the pause, inside the
40 s bound). That stop cuts nothing, so a take lost after it still fails as with no stop.

**Late inputs:** Web API calls and database writes take time, so an input can be handled after
the player moved on. Whether a take really played is read from Spytify's own `session.state`
before it (stream order), never from the player's state now; a track is identified by MPRIS only
once its title agrees, else by its title.

**Never touched after a takeover:** the player. Pausing our client then could pause the phone.

**D13's clean full pass** (design.md step 1): a whole item without item access that ended
`done`, whose context was heard to its end (Steering.wrapped), with no failed take and no take
skipped for a reason a later pass could fix (seeked, low quality, silent, incomplete, or
discarded by a stop). Skips by Spytify's policy (too short, ad) don't spoil it; they aren't in
observed_tracks either.

Cautious choices (open points, reported): a whole item's time limit uses a stand-in length
(planning.py); a context change ends a whole item partial and never counts as a clean full pass;
the client leaving the bus mid-item is an interruption like a stall; a pause at the start of a
first entry that isn't a playable track (an episode) is taken for a stall; a GET /me/player that
never catches up with the play is taken as true after the re-reads, unless MPRIS vouches; a
takeover or context change can be the old state when its device or context is the pre-flight's,
whatever the read's other fields say (only Liked Songs' alias is learned from a read's track).
"""

import asyncio
import contextlib
import logging
import sqlite3
from collections.abc import Awaitable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from spotivault.clock import iso_ms
from spotivault.connection import our_device
from spotivault.engine.item_outcome import AttemptFacts, Ending, decide, stop_ending
from spotivault.engine.item_takes import CutReason, Take, TakeBook, is_file_error
from spotivault.engine.planning import ItemPlan, plan_item
from spotivault.engine.states import ItemState
from spotivault.engine.steering import ContextCheck, SteerDecision, Steering
from spotivault.engine.types import (
    ControllerErrorCode,
    ItemControl,
    ItemHost,
    ItemJob,
    ItemLeft,
    ItemLive,
    ItemOutcome,
    ItemReport,
    ItemTimings,
    MissingTrack,
    RunFailure,
    SessionState,
    StopRequest,
    Takeover,
    TrackCounts,
)
from spotivault.matching import go_lower, go_trim, track_key
from spotivault.ports import (
    ApiScope,
    ConnectionExpired,
    Device,
    MprisChange,
    MprisNoClient,
    MprisUnavailable,
    NoAccess,
    NotConnected,
    NotFound,
    PlaybackStatus,
    PlayerState,
    PortError,
    RecorderGone,
    RecorderNotification,
    RecorderRpcError,
    RecorderSession,
    RecorderSpec,
    RecorderStartError,
    TrackMetadata,
    WebApiError,
)
from spotivault.recorder import protocol as sp
from spotivault.storage import storage_problem

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

IDENTIFY_STEP_S = 0.5  # D10: look at MPRIS's title this often …
IDENTIFY_TRIES = 7  # … up to 3 s, until it agrees with track.started's
END_POSITION_MS = 1500  # paused this close to a track's start: Spotify's end of a context
TRACK_CHECK_MIN_S = 5.0  # D10's GET /me/player at a track's start, at most this often: a whole
# item's duplicates go by every half second, and 30 requests in 30 s is a burst (webapi/usage.py)
AFTER_EXIT_CHECK_S = 2.0  # bug 1's Next can land just after the exit (probe.py waits 2 s too)
RECHECK_S = 2.0  # GET /me/player disagreed before it caught up with the play: read it again …
RECHECK_TRIES = 3  # … this many times at most, so a real change waits 6 s (module docstring)
CONTROL_POLL_S = 1.0  # after a stop, how often to look for an upgrade to "now"
STOP_RPC_TIMEOUT_S = 10.0  # session.stop's answer
QUICK_FIRST_GRACE_S = 10.0  # Stop now when session.stop fails: SIGTERM → this → SIGTERM
QUICK_SECOND_GRACE_S = 5.0  # → this → SIGKILL (the shutdown must end within 40 s)
TAKE_END_MARGIN_S = 30.0  # a stop after the take: its end + this, then signals (or the next)
# Skips a later pass could fix: a whole pass that has one isn't a clean full pass (D13).
# `discarded` is a take a Stop now cut, the user's or a shutdown's.
_UNCLEAN_SKIPS = frozenset({"seeked", "low_quality", "silent", "incomplete", "discarded"})
_TAKE_EVENTS = frozenset({sp.TRACK_STARTED, sp.TRACK_FINISHED, sp.TRACK_SKIPPED})

type _Check = Literal["ok", "takeover", "context_changed"]

_UNAVAILABLE_TEXT = {
    "removed": "Removed from the Library.",
    "deleted": "The playlist was deleted.",
    "private": "The playlist is private now.",
    "unfollowed": "You no longer follow the playlist.",
    "not_offered": "Not available in your country.",
}


class _RecorderEnded:
    """The recorder's notifications ended: it has exited."""


_RECORDER_ENDED = _RecorderEnded()

type _Input = RecorderNotification | MprisChange | StopRequest | _RecorderEnded


class ItemEngine:
    """Runs one attempt at one item. Made by the run engine for each attempt; used once."""

    def __init__(
        self, services: "Services", job: ItemJob, *, host: ItemHost, control: ItemControl
    ) -> None:
        self.services = services
        self.job = job
        self.host = host
        self.control = control
        clock = services.clock
        self._scope = ApiScope("run", job.run_id)
        self._device_id = job.device_id
        self._something_plays = True  # preflight's GET /me/player; until read, the cautious answer
        # Phases and timings.
        self._phase: ItemState = "planning"
        self._reported: set[ItemState] = set()
        self._phase_since = clock.monotonic()
        self._phase_s: dict[ItemState, float] = {}
        self._started_at = clock.now()
        self._recorder_started_at: datetime | None = None
        self._first_track_at: datetime | None = None
        self._finishing_at: datetime | None = None
        self._recorder_exit_at: datetime | None = None
        # What's played.
        self._plan: ItemPlan | None = None
        self._settings: list[tuple[str, str]] = []  # the recorder's --set pairs
        self._takes: TakeBook | None = None
        self._steering: Steering | None = None
        self._context = ContextCheck(job.context_uri, liked=job.kind == "liked")
        self._counts_sent = TrackCounts()
        # The recorder.
        self._session: RecorderSession | None = None
        self._session_state: SessionState | None = None
        self._session_active = False  # Spytify's session left idle at least once
        self._session_stop: Literal["after_track", "now"] | None = None
        self._terminating = False
        self._exit_code: int | None = None
        # The play loop.
        self._inbox: asyncio.Queue[_Input] = asyncio.Queue()
        self._next_get: asyncio.Task[_Input] | None = None
        self._group: asyncio.TaskGroup | None = None
        self._mpris_ready = asyncio.Event()
        self._deadlines: dict[str, float] = {}
        self._recorder_ended = False
        self._played = False  # the first play was sent
        self._first_offset_uri: str | None = None
        self._finishing = False
        self._paused_since: float | None = None  # an unexplained pause began (monotonic)
        self._checked_at = -TRACK_CHECK_MIN_S  # the last GET /me/player (monotonic)
        self._before: PlayerState | None = None  # GET /me/player before the play (pre-flight)
        self._caught_up = False  # GET /me/player has shown our device on the item's context
        self._rechecks_left = 0  # player_recheck's reads left
        self._pause_unjudged = False  # a pause waits for the re-reads before it's judged
        # What happened: the outcome is decided from these (item_outcome.py).
        self._facts = AttemptFacts()
        self._cut_reason: CutReason | None = "interrupted"  # how a planned take cut short fails
        self._file_error = False  # a Spytify error lost a take's file
        self._error_code: ControllerErrorCode | None = None

    # --- The interface ---------------------------------------------------------------------------

    async def run(self) -> ItemReport:
        """Plays the item through its phases and returns how it ended. Never raises for an
        expected failure (the report says it); an unexpected exception is a bug: the run engine
        logs it and ends the item `failed`."""
        try:
            return await self._run()
        finally:
            await self._kill_leftover_recorder()

    def live(self) -> ItemLive:
        """The current phase, the session state, the take recording now, the live track table,
        and what's left to play. Cheap and synchronous: GET /api/status calls it."""
        takes = self._takes
        return ItemLive(
            phase=self._phase,
            session_state=self._session_state,
            now_playing=takes.now_playing if takes is not None else None,
            tracks=takes.rows() if takes is not None else (),
            left=self._left(),
        )

    def _left(self) -> ItemLeft | None:
        """What's left of this item to play, for the run's time left (engine/time_left.py):
        the rest of the planned take recording now, and the planned tracks that haven't
        started. None until it's planned. A take steering is about to jump over isn't counted;
        once playback is over, or after Stop now, nothing is left; after Stop after this track,
        only the take. Always with the keys it has recorded so far (`done_keys`), so a waiting
        item that lists them doesn't count them again."""
        plan = self._plan
        if plan is None:
            return None
        takes = self._takes
        done = takes.done_keys() if takes is not None else frozenset[str]()
        nothing = ItemLeft(take_ms=0, take_key=None, tracks=(), done_keys=done)
        if plan.unavailable or plan.up_to_date_by is not None or self._finishing:
            return nothing
        stop = self.control.stop
        if stop is not None and stop.mode == "now":
            return nothing
        take = takes.open_take() if takes is not None else None
        take_ms, take_key = 0, None
        if take is not None and take.planned:
            take_ms, take_key = round(self._take_left_s(take) * 1000), take.key
        if stop is not None:
            return ItemLeft(take_ms=take_ms, take_key=take_key, tracks=(), done_keys=done)
        if plan.mode == "whole":
            return ItemLeft(take_ms=take_ms, take_key=take_key, tracks=None, done_keys=done)
        started = self._steering.started if self._steering is not None else set()
        tracks = tuple(
            MissingTrack(key=track.key, duration_ms=track.duration_ms)
            for track in plan.missing
            if track.position not in started
        )
        return ItemLeft(take_ms=take_ms, take_key=take_key, tracks=tracks, done_keys=done)

    @property
    def recorder_pid(self) -> int | None:
        """spytifyd's pid while it runs, for the run metrics; None otherwise."""
        session = self._session
        if session is None or session.returncode is not None:
            return None
        return session.pid

    # --- The phases ------------------------------------------------------------------------------

    async def _run(self) -> ItemReport:
        await self._enter("planning")
        plan = await plan_item(self.services, self.job)
        self._plan = plan
        if plan.unavailable:
            return await self._unavailable_at_planning(plan)
        self._settings = await self.services.settings.recorder_settings(plan.mode)
        self._takes = _new_take_book(self.services, self.job, plan, self._settings)
        self._steering = Steering(plan)
        if plan.up_to_date_by is not None:
            await self._write_item_rows("up_to_date", clean_full_pass=False)
            await self._write_m3u()
            return self._report(
                "up_to_date",
                up_to_date_by=plan.up_to_date_by,
                still_missing=0 if plan.mode == "missing_only" else None,
            )

        # Before the recorder starts, a stop ends the item at once.
        early = self._stopped_before_recorder()
        if early is None:
            await self._enter("preflight")
            early = await self._preflight()
        if early is None:
            early = self._stopped_before_recorder()
        if early is None:
            await self._enter("preparing")
            early = await self._prepare()
        if early is None:
            early = self._stopped_before_recorder()
        if early is None:
            await self._enter("starting")
            early = await self._start_recorder()
        if early is not None:
            return early

        await self._play_and_finish()
        return await self._conclude()

    async def _unavailable_at_planning(self, plan: ItemPlan) -> ItemReport:
        reason = plan.unavailable_reason or "deleted"
        if reason == "not_offered":
            await self._mark_unavailable("not_offered")
        return self._report("unavailable", reason=_UNAVAILABLE_TEXT.get(reason))

    def _stopped_before_recorder(self) -> ItemReport | None:
        """A stop before the recorder started ends the item at once (ItemControl)."""
        stop = self.control.stop
        if stop is None:
            return None
        self._facts.stop = stop
        ending = stop_ending(stop)
        return self._report(ending.outcome, interrupted_by=ending.interrupted_by)

    async def _preflight(self) -> ItemReport | None:
        """Our device listed, nobody else playing (D6), and room in /music."""
        webapi = self.services.ports.webapi
        name = self.services.config.device_name
        try:
            ours = our_device(await webapi.devices(scope=self._scope), name)
            if ours is None or ours.id is None:
                message = f"The container's Spotify device ({name}) isn't in your device list."
                failure = RunFailure("device_missing", message)
                return self._report("failed", reason=message, run_failure=failure)
            self._device_id = ours.id
            state = await webapi.player_state(scope=self._scope)
        except WebApiError as exc:
            return await self._webapi_failed_early(exc, "checking the devices")
        self._before = state
        self._context.before_play = state.context_uri if state is not None else None
        self._something_plays = state is not None and state.is_playing  # None: 204, none active
        if (
            state is not None
            and state.is_playing
            and state.device is not None
            and state.device.id != self._device_id
        ):
            device = state.device
            reason = f"{device.name} is playing."
            return self._report("device_busy", device_busy=device, reason=reason)
        storage = await self.services.storage.check()
        if not storage.ok:
            message = storage_problem(storage) or "The music folder can't be recorded to."
            await self._controller_error("storage", message, fatal=True)
            return self._report(
                "failed",
                reason=message,
                error_code="storage",
                run_failure=RunFailure("storage", message),
            )
        return None

    async def _prepare(self) -> ItemReport | None:
        """Pause, seek to 0, shuffle and repeat off, on our device (design.md step 2). The pause
        only when preflight saw something playing: with nothing playing (204, or is_playing
        false), Spotify answers it 403 "Restriction violated", and five 4xx answers in a row
        raise the usage log's warning. Another device playing ended the item at preflight (D6)."""
        webapi = self.services.ports.webapi
        device, scope = self._device_id, self._scope
        failure: ItemReport | None = None
        if self._something_plays:
            failure = await self._player_step("pause", webapi.pause(device_id=device, scope=scope))
        if failure is None:
            failure = await self._player_step(
                "seek to 0", webapi.seek(0, device_id=device, scope=scope)
            )
        if failure is None:
            failure = await self._player_step(
                "shuffle off", webapi.set_shuffle(False, device_id=device, scope=scope)
            )
        if failure is None:
            failure = await self._player_step(
                "repeat off", webapi.set_repeat("off", device_id=device, scope=scope)
            )
        return failure

    async def _player_step(self, name: str, call: Awaitable[None]) -> ItemReport | None:
        try:
            await call
        except (NoAccess, NotFound) as exc:
            # "Player command failed" on a player already paused or with nothing loaded.
            log.info("item %s: %s answered %s; going on", self.job.item_id, name, exc)
        except WebApiError as exc:
            return await self._webapi_failed_early(exc, f"preparing the player ({name})")
        return None

    async def _start_recorder(self) -> ItemReport | None:
        """Cleans up stale files, starts spytifyd (retrying once on a socket in use), then
        `full_volume`. Returns a report when the item ends here."""
        plan = self._plan
        assert plan is not None
        await self._cleanup_stale()
        early = self._stopped_before_recorder()  # the cleanup can take a while
        if early is not None:
            return early
        timeouts = self.job.timeouts
        config = self.services.config
        spec = RecorderSpec(
            run_id=self.job.run_id,
            item_id=self.job.item_id,
            settings=self._settings,
            log_file=self.job.log_file,
            events_file=self.job.events_file,
            socket_path=self.job.socket_path,
            work_dir=self.job.work_dir,
            umask=config.umask_bits,
            idle_exit_s=timeouts.idle_exit_s,
            wait_target_s=timeouts.wait_target_s,
            socket_timeout_s=timeouts.socket_s,
        )
        await asyncio.to_thread(_make_folders, spec)
        recorder = self.services.ports.recorder
        for attempt in (1, 2):
            try:
                self._session = await recorder.start(spec)
                break
            except RecorderStartError as exc:
                verdict = sp.classify_exit(exc.exit_code, exc.log_tail)
                if verdict.action == "retry_once" and attempt == 1:
                    killed = await recorder.kill_orphans()
                    if killed:
                        self._note_if_killed(-9)  # an orphan may have been encoding
                    await asyncio.to_thread(self.job.socket_path.unlink, missing_ok=True)
                    log.warning(
                        "item %s: the recorder's socket was in use (%d orphans killed): "
                        "starting it once more",
                        self.job.item_id,
                        killed,
                    )
                    continue
                return await self._recorder_start_failed(exc, verdict)
        self._recorder_started_at = self.services.clock.now()
        await self._recorder_ready()
        return None

    async def _recorder_start_failed(
        self, exc: RecorderStartError, verdict: sp.ExitVerdict
    ) -> ItemReport:
        message = f"The recorder couldn't start: {exc}"
        failure = None
        if verdict.action == "fail_run":
            reason = "storage" if verdict.cause == "output_dir" else "recorder"
            failure = RunFailure(reason, message)
        facts = {"exit_code": str(exc.exit_code), "cause": verdict.cause}
        await self._controller_error("recorder_exit", message, fatal=True, facts=facts)
        return self._report(
            "failed",
            reason=message,
            error_code="recorder_exit",
            run_failure=failure,
            recorder_exit_code=exc.exit_code,
        )

    async def _recorder_ready(self) -> None:
        """Logs Spytify's failed checks, and raises the player's volume (FINDINGS row 10)."""
        session = self._session
        assert session is not None
        try:
            info = sp.CoreInfo.from_params(await session.call(sp.CORE_INFO))
            failed = info.failed_checks()
            if failed:
                details = ", ".join(f"{check.name} ({check.detail})" for check in failed)
                log.warning("item %s: Spytify's checks failed: %s", self.job.item_id, details)
        except (PortError, TimeoutError) as exc:
            log.warning("item %s: core.info failed: %s", self.job.item_id, exc)
        try:
            await session.call(sp.PLAYER_CONTROL, {"cmd": "full_volume"})
        except (PortError, TimeoutError) as exc:
            log.warning("item %s: full_volume failed: %s", self.job.item_id, exc)

    # --- Playing ---------------------------------------------------------------------------------

    async def _play_and_finish(self) -> None:
        """The play loop, until the recorder exits; then its leftovers and the player."""
        session = self._session
        assert session is not None
        async with asyncio.TaskGroup() as group:
            self._group = group
            watchers = [
                group.create_task(self._read_recorder(session)),
                group.create_task(self._watch_mpris()),
                group.create_task(self._watch_control()),
            ]
            try:
                await self._enter("playing")
                await self._mpris_ready.wait()  # subscribed first, so no change is missed
                if self.control.stop is None:
                    await self._play_first()
                while not self._recorder_ended:
                    await self._handle(await self._next_input())
            finally:
                for task in watchers:
                    task.cancel()
                if self._next_get is not None:
                    self._next_get.cancel()
                self._group = None
        self._exit_code = await self._wait_for_exit()
        self._recorder_exit_at = self.services.clock.now()
        self._note_if_killed(self._exit_code)
        await self._check_exit_code()
        await self._read_lost_events()
        await self._begin_finishing(pause=False)
        await self._settle_player()

    async def _play_first(self) -> None:
        """The first play, and the deadlines it starts."""
        plan, steering = self._plan, self._steering
        assert plan is not None and steering is not None
        offset = steering.first_offset()
        self._first_offset_uri = offset.uri if offset is not None else None
        timeouts = self.job.timeouts
        now = self.services.clock.monotonic()
        limit_s = timeouts.item_max_factor * plan.length_ms / 1000 + timeouts.item_max_extra_s
        self._deadlines["first_track_replay"] = now + timeouts.first_track_replay_s
        self._deadlines["first_track_give_up"] = now + timeouts.first_track_give_up_s
        self._deadlines["item_max"] = now + limit_s
        self._deadlines["webapi_check"] = now + timeouts.webapi_check_s
        self._played = True
        await self._play(self._first_offset_uri, first=True)

    async def _play(self, offset_uri: str | None, *, first: bool) -> bool:
        """PUT /me/player/play with the item's context, at `offset_uri` (by URI, never by
        position). A failure ends the item: on a 404 see `_play_not_found`; failed on the first
        play's other errors, partial on a jump's (the tracks it was for stay missing)."""
        webapi = self.services.ports.webapi
        try:
            await webapi.play(
                device_id=self._device_id,
                context_uri=self.job.context_uri,
                offset_uri=offset_uri,
                scope=self._scope,
            )
            return True
        except NotFound as exc:
            await self._play_not_found(exc, first=first)
        except WebApiError as exc:
            message = f"Spotify's Web API refused the play: {exc}"
            await self._controller_error("webapi", message, fatal=first)
            if first:
                failure = _run_failure_for(exc)
                self._facts.failure = self._facts.failure or Ending(
                    "failed", message, error_code="webapi", run_failure=failure
                )
        await self._pause_player()
        await self._stop_session(now=True)
        await self._begin_finishing(pause=False)
        return False

    async def _play_not_found(self, exc: NotFound, *, first: bool) -> None:
        """A 404 from the play. Spotify answers 404 for a device it doesn't know, too, so the
        device list is read: our device gone fails the run (device_missing), as the pre-flight
        does. Otherwise the first play's item is unavailable for this run only, and a jump's
        tracks stay missing (partial). `items` isn't changed: whether the item itself is gone
        is the catalog refresh's to decide."""
        item = self.job.item_id
        name = self.services.config.device_name
        try:
            devices = await self.services.ports.webapi.devices(scope=self._scope)
        except WebApiError as check:
            log.warning(
                "item %s: the play answered %s; the devices can't be read: %s", item, exc, check
            )
            message = f"Spotify's Web API refused the play: {exc}"
            await self._controller_error("webapi", message, fatal=first)
            if first:
                self._facts.failure = self._facts.failure or Ending(
                    "failed", message, error_code="webapi", run_failure=_run_failure_for(check)
                )
            return
        ours = our_device(devices, name)
        if ours is None or ours.id is None:
            message = f"The container's Spotify device ({name}) isn't in your device list."
            log.warning("item %s: the play answered %s: our device is gone", item, exc)
            self._facts.failure = self._facts.failure or Ending(
                "failed", message, run_failure=RunFailure("device_missing", message)
            )
            return
        if not first:
            message = f"Spotify couldn't find the track to jump to: {exc}"
            await self._controller_error("webapi", message, fatal=False)
            return
        log.warning("item %s: the play answered %s: unavailable in this run", item, exc)
        self._facts.failure = self._facts.failure or Ending(
            "unavailable", "Spotify couldn't find it to play (404)."
        )

    # --- The play loop: inputs -------------------------------------------------------------------

    async def _next_input(self) -> _Input | None:
        """The next input, or None when the earliest deadline passed first (on the clock)."""
        group = self._group
        assert group is not None
        if self._next_get is None:
            self._next_get = group.create_task(self._inbox.get())
        getter = self._next_get
        if not getter.done():
            if self._deadlines:
                delay = min(self._deadlines.values()) - self.services.clock.monotonic()
                if delay > 0:
                    await self._wait_at_most(getter, delay)
            else:
                await asyncio.wait({getter})
        if not getter.done():
            return None
        self._next_get = None
        return getter.result()

    async def _handle(self, event: _Input | None) -> None:
        if event is None:
            await self._on_deadlines()
        elif isinstance(event, _RecorderEnded):
            self._on_recorder_ended()
        elif isinstance(event, RecorderNotification):
            await self._on_notification(event)
        elif isinstance(event, MprisChange):
            await self._on_mpris(event)
        else:
            await self._on_stop(event)

    async def _read_recorder(self, session: RecorderSession) -> None:
        """Watcher: every notification into the inbox, then the end marker."""
        try:
            async for notification in session.notifications():
                self._inbox.put_nowait(notification)
        except PortError as exc:
            log.warning("item %s: reading the recorder failed: %s", self.job.item_id, exc)
        finally:
            self._inbox.put_nowait(_RECORDER_ENDED)

    async def _watch_mpris(self) -> None:
        """Watcher: MPRIS changes into the inbox. Without the bus, the item still runs on the
        recorder's events and the timers."""
        try:
            async with self.services.ports.mpris.subscribe() as changes:
                self._mpris_ready.set()
                async for change in changes:
                    self._inbox.put_nowait(change)
        except MprisUnavailable as exc:
            log.warning("item %s: MPRIS can't be watched: %s", self.job.item_id, exc)
        finally:
            self._mpris_ready.set()

    async def _watch_control(self) -> None:
        """Watcher: the run engine's stop into the inbox, and later an upgrade to "now".
        `changed()` returns at once after the first stop, so it's looked at every second."""
        seen: StopRequest | None = None
        while True:
            request = await self.control.changed()
            if request != seen:
                seen = request
                self._inbox.put_nowait(request)
            await self.services.clock.sleep(CONTROL_POLL_S)

    # --- The play loop: the recorder ----------------------------------------------------------

    def _on_recorder_ended(self) -> None:
        self._recorder_ended = True
        if not self._finishing and self._paused_since is not None:
            self._facts.stalled = True  # the idle exit ended a pause in the middle of the item

    async def _on_notification(self, notification: RecorderNotification) -> None:
        takes = self._takes
        assert takes is not None
        event = sp.parse_notification(notification.method, notification.params)
        if isinstance(event, sp.TrackStarted):
            await self._on_track_started(event, notification.received_at)
        elif isinstance(event, sp.TrackFinished):
            if await takes.finish(event):
                await self._counts_changed()
        elif isinstance(event, sp.TrackSkipped):
            if await takes.skip(event, cut_reason=self._cut_reason):
                await self._counts_changed()
                if event.reason == "duplicate":
                    await self._on_duplicate(event.id)
        elif isinstance(event, sp.SessionStateChanged):
            await self._on_session_state(event.state)
        elif isinstance(event, sp.Level):
            self._relay_level(event)
        elif isinstance(event, sp.SpytifyError):
            await self._on_spytify_error(event)
        elif isinstance(event, sp.LogLine):
            log.debug("spytifyd %s: %s", self.job.item_id, event.text())
        else:
            log.debug("spytifyd %s: %s %s", self.job.item_id, notification.method, event)

    async def _on_track_started(self, event: sp.TrackStarted, received_at: datetime) -> None:
        """Identify the loaded track (D10), steer, check the player, then record the take."""
        takes, steering = self._takes, self._steering
        assert takes is not None and steering is not None
        if self._first_track_at is None:
            self._first_track_at = self.services.clock.now()
            self._deadlines.pop("first_track_replay", None)
            self._deadlines.pop("first_track_give_up", None)
        # Spytify's own state before this event says whether the player was playing: paused,
        # it's the phantom take at the idle exit (Spotify's end of the context, forced). The
        # stream's order holds however late this is read; MPRIS's status now may not.
        playing = self._session_state != "paused"
        # Steering needs the entry only for a missing_only item that plays: only then is it
        # worth waiting for MPRIS, and asking GET /me/player. A whole item goes by the key.
        steered = playing and self._plan is not None and self._plan.mode == "missing_only"
        mpris_id = await self._identify(event.title, wait=steered)
        state: PlayerState | None = None
        fallback_id = None
        if mpris_id is None and steered:
            state = await self._player_state()  # D10's fallback; its id may be relinked
            fallback_id = self._fallback_id(state, event.title)
        decision = steering.on_track_started(
            track_id=mpris_id or fallback_id,
            title=event.title,
            playing=playing,
            artist=event.artist,
        )
        ending = self._finishing or self._facts.stop is not None
        if ending and decision.action != "stay":
            # The item is over or stopping: whatever starts now is paused, never jumped from,
            # and a guard that already fired doesn't raise its alert again.
            decision = SteerDecision("pause", decision.position, track=decision.track)
        take = Take(
            take_id=event.id,
            artist=event.artist,
            title=event.title,
            album=event.album,
            length_ms=event.length_ms,
            cover_url=event.cover_url,
            key=track_key(event.artist, event.title),
            started_at=received_at,
            track=decision.track,
            mpris_track_id=mpris_id,
            planned=decision.planned,
            phantom=not playing,
        )
        if self._facts.context_moved:
            take.planned = False  # the new context's track, not the item's
        await self._steer(decision)
        check: _Check = "ok"
        if playing and decision.action in ("stay", "jump") and not self._finishing:
            if state is None and self._may_check_now():
                state = await self._player_state()
            check = self._confirmed_check(state, mpris_id=mpris_id)
            if check == "context_changed":
                take.planned = False
        await takes.start(take)
        if take.planned and not take.phantom:
            await self.host.item_take_started(self.job)  # the run's time left counts it now
        if check != "ok":
            await self._act_on_check(check, state)

    async def _on_duplicate(self, take_id: str) -> None:
        """A missing_only item's planned take that Spytify skipped as a duplicate while playing:
        with skip-forward off it would play to its end unrecorded, so steering moves on."""
        takes, steering, plan = self._takes, self._steering, self._plan
        assert takes is not None and steering is not None and plan is not None
        take = takes.get(take_id)
        if (
            plan.mode != "missing_only"
            or take is None
            or not take.planned
            or take.phantom
            or self._finishing
            or self._facts.stop is not None
            or self._facts.takeover is not None
            or self._facts.context_moved
        ):
            return
        log.info("item %s: %r is already recorded: moving on", self.job.item_id, take.title)
        await self._steer(steering.on_planned_duplicate())

    async def _steer(self, decision: SteerDecision) -> None:
        if decision.action == "jump":
            assert decision.jump_to is not None
            log.info(
                "item %s: track %s isn't planned: jumping to %d",
                self.job.item_id,
                decision.position + 1 if decision.position is not None else "?",
                decision.jump_to.position + 1,
            )
            await self._play(decision.jump_to.uri, first=False)
        elif decision.action == "pause":
            log.info("item %s: nothing left to play: pausing", self.job.item_id)
            await self._pause_player()
            await self._begin_finishing(pause=False)
        elif decision.action in ("loop_guard", "steering_guard"):
            if decision.action == "loop_guard":
                message = "A track came round a second time, so the player was paused."
            else:
                message = "A planned track started a second time, so the player was paused."
            await self._controller_error(decision.action, message, fatal=False)
            await self._pause_player()
            await self._begin_finishing(pause=False)

    async def _on_session_state(self, state: SessionState) -> None:
        self._session_state = state
        self.services.bus.publish(
            "session.state",
            {"run_id": self.job.run_id, "item_id": self.job.item_id, "state": state},
        )
        if state != "idle":
            self._session_active = True
        elif self._session_active:
            # The session is over (the idle exit, a stop, the player gone): playback is too.
            if not self._finishing and self._paused_since is not None:
                self._facts.stalled = True
            await self._begin_finishing()

    def _relay_level(self, level: sp.Level) -> None:
        """The level meter, only while recording or stopping (events.md § Level throttling)."""
        if self._session_state not in ("recording", "stopping"):
            return
        self.services.bus.publish_level(
            {
                "peak_dbfs": level.peak_dbfs,
                "rms_dbfs": level.rms_dbfs,
                "channels": [
                    {"peak_dbfs": c.peak_dbfs, "rms_dbfs": c.rms_dbfs} for c in level.channels
                ],
            }
        )

    async def _on_spytify_error(self, error: sp.SpytifyError) -> None:
        """Relays Spytify's `error`. A silent or stalled capture ends the item partial (D12)."""
        self.services.bus.publish(
            "error",
            {
                "source": "spytify",
                "code": error.code,
                "message": error.msg,
                "fatal": error.fatal,
                "withdrawn": error.withdrawn,
                "run_id": self.job.run_id,
                "item_id": self.job.item_id,
                "facts": dict(error.facts) or None,
            },
        )
        if error.withdrawn:
            return
        log.warning("item %s: Spytify: %s %s", self.job.item_id, error.code, error.msg)
        if is_file_error(error.code):
            self._file_error = True
        if error.code in ("capture_silent", "capture_stalled"):
            if self._facts.capture_problem is None:
                self._facts.capture_problem = error.msg or error.code
                self._cut_as("interrupted")
                await self._stop_session(now=True)
                await self._begin_finishing()
        elif error.fatal and self._facts.spytify_fatal is None:
            self._facts.spytify_fatal = error.msg or error.code

    # --- The play loop: the player -------------------------------------------------------------

    async def _on_mpris(self, change: MprisChange) -> None:
        if change.owner_present is False:
            self._facts.client_gone = True  # Spytify ends the session: "player interface gone"
            return
        if change.playback_status == "Playing":
            self._paused_since = None
            self._pause_unjudged = False
            self._deadlines.pop("stall_exit", None)
            if self._finishing:
                await self._pause_player()  # nothing plays once the item is over (bug 1)
        elif change.playback_status == "Paused":
            if self._played and not self._finishing and self._paused_since is None:
                await self._on_unexpected_pause()
        if change.metadata is not None and self._paused_since is not None and not self._finishing:
            # MPRIS's metadata can come after the pause (it lags): the track Spotify loaded at
            # the end of the context is only known now. While GET /me/player is read again, the
            # pause may still be a takeover: it's judged once the re-reads are over.
            if "player_recheck" in self._deadlines:
                self._pause_unjudged = True
            elif await self._ended_at_context_start(change.metadata):
                await self._context_ended()

    async def _on_unexpected_pause(self) -> None:
        """A pause nobody here asked for: a takeover, the end of the context, or a stall.

        Spotify ends a context by loading its first track and pausing at 0 (FINDINGS § End-of-
        item handling); a stall or a takeover pauses where the track was. What's loaded is read
        now, and holds while the player stays paused, however late this runs. While GET
        /me/player is read again (`player_recheck`), it may still hide a takeover, so the end of
        the context waits for the re-reads (`_judge_pause`); a stall's deadline is armed now."""
        mpris = self.services.ports.mpris
        try:
            status = await mpris.playback_status()
            meta = await mpris.metadata()
        except MprisUnavailable:
            status, meta = None, None
        if status == "Playing":
            return  # playing again already: the change saying so comes next
        self._paused_since = self.services.clock.monotonic()
        state = await self._player_state()  # D10: checked on pause
        check = self._confirmed_check(state, mpris_id=None)  # MPRIS can't rule out a takeover
        if check != "ok":
            await self._act_on_check(check, state)
            return
        if "player_recheck" in self._deadlines:
            self._pause_unjudged = True
        elif await self._ended_at_context_start(meta):
            await self._context_ended()
            return
        timeouts = self.job.timeouts
        self._deadlines["stall_exit"] = (
            self._paused_since + timeouts.stall_s + timeouts.finishing_extra_s
        )

    async def _judge_pause(self) -> None:
        """A pause left unjudged while GET /me/player was read again, once the re-reads are over
        and found no takeover to act on: the end of the context, else the stall it was taken
        for. What's loaded holds while the player stays paused."""
        if (
            not self._pause_unjudged
            or "player_recheck" in self._deadlines
            or self._paused_since is None
            or self._finishing
        ):
            return
        self._pause_unjudged = False
        try:
            meta = await self.services.ports.mpris.metadata()
        except MprisUnavailable:
            return
        if await self._ended_at_context_start(meta):
            await self._context_ended()

    async def _ended_at_context_start(self, meta: TrackMetadata | None) -> bool:
        """Spotify's end of the context: paused within 1.5 s of the start of the context's first
        track (Steering.is_first_track), once a track has played. A pause anywhere else is a
        stall, even at a track's start: that track was never heard."""
        steering = self._steering
        assert steering is not None
        if meta is None or self._first_track_at is None:
            return False
        try:
            position = await self.services.ports.mpris.position_ms()
        except MprisUnavailable:
            return False
        if position is None or position > END_POSITION_MS:
            return False
        return steering.is_first_track(
            track_id=meta.track_id,
            title=meta.title or "",
            artist=meta.artists[0] if meta.artists else "",
        )

    async def _context_ended(self) -> None:
        steering = self._steering
        assert steering is not None
        log.info("item %s: the context ended (paused at its first track)", self.job.item_id)
        steering.context_ended()
        await self._begin_finishing(pause=False)

    def _check_player(self, state: PlayerState | None, *, settled: bool) -> _Check:
        """GET /me/player: another device active (a takeover), or another context (autoplay).
        `settled`: the read can't be the state from before the play any more (ContextCheck)."""
        if state is None:
            return "ok"
        device = state.device
        if device is not None and device.id != self._device_id and device.is_active:
            return "takeover"
        if not self._context.matches(state.context_uri, settled=settled):
            return "context_changed"
        return "ok"

    def _confirmed_check(self, state: PlayerState | None, *, mpris_id: str | None) -> _Check:
        """`_check_player`, but a mismatch read before the state caught up with the play, that
        can be the state from before the play, is "ok" for now (module docstring, "GET
        /me/player lags a play"): MPRIS vouches for the context when `mpris_id` (the take
        playing) is one of the item's tracks, else `player_recheck` reads it again."""
        check = self._check_player(state, settled=self._caught_up)
        if check == "ok":
            self._note_caught_up(state)
            return "ok"
        if self._caught_up:
            return check
        assert state is not None
        if not self._may_be_before_play(state, check):
            return check  # another device or context than before the play: it's new
        if self._learns_alias(state, check, mpris_id):
            return "ok"
        if check == "context_changed" and self._is_item_track(mpris_id):
            log.info(
                "item %s: GET /me/player still reports %s, but MPRIS shows the item's track: "
                "the state is behind",
                self.job.item_id,
                state.context_uri,
            )
            return "ok"
        if "player_recheck" not in self._deadlines:
            log.info(
                "item %s: GET /me/player reports %s just after the play: reading it again",
                self.job.item_id,
                _what_it_reports(state, check),
            )
            self._rechecks_left = RECHECK_TRIES
            self._deadlines["player_recheck"] = self.services.clock.monotonic() + RECHECK_S
        return "ok"

    async def _recheck_player(self) -> None:
        """`player_recheck`: GET /me/player again. Caught up: done. Another device or context
        than before the play: acted on at once. Still what it reported before the play: again
        2 s later, and after the last read it's acted on, unless MPRIS vouches for the context.
        A read that fails or reports nothing concludes nothing."""
        self._rechecks_left -= 1
        last = self._rechecks_left <= 0
        state = await self._player_state()
        check = self._check_player(state, settled=last)
        if check == "ok":
            if self._note_caught_up(state) or last:
                return
        else:
            assert state is not None
            if not self._may_be_before_play(state, check):
                await self._act_on_check(check, state)
                return
            mpris_id = self._playing_mpris_id()
            if self._learns_alias(state, check, mpris_id):
                return
            if last:
                await self._after_the_last_read(state, check, mpris_id)
                return
        self._deadlines["player_recheck"] = self.services.clock.monotonic() + RECHECK_S

    async def _after_the_last_read(
        self, state: PlayerState, check: _Check, mpris_id: str | None
    ) -> None:
        """The last re-read still reports what it did before the play: taken as true (the
        state had 6 s to catch up), unless MPRIS vouches for the context."""
        if check == "context_changed" and self._is_item_track(mpris_id):
            log.warning(
                "item %s: GET /me/player still reports %s, but MPRIS shows the item's track: "
                "going on",
                self.job.item_id,
                state.context_uri,
            )
            return
        log.warning(
            "item %s: GET /me/player still reports %s after %d reads: it's taken as true",
            self.job.item_id,
            _what_it_reports(state, check),
            RECHECK_TRIES + 1,
        )
        await self._act_on_check(check, state)

    def _may_be_before_play(self, state: PlayerState, check: _Check) -> bool:
        """Whether this mismatch can be the state from before the play, still reported: the
        other device is the one the pre-flight read reported, or the other context is. Field by
        field, so a read with only its other fields new is still taken as possibly old. Any
        other device or context is new: the state has moved on since the play."""
        if check == "takeover":
            before = self._before.device if self._before is not None else None
            return before is not None and state.device is not None and state.device.id == before.id
        return state.context_uri == self._context.before_play

    def _learns_alias(self, state: PlayerState, check: _Check, mpris_id: str | None) -> bool:
        """Liked Songs, with its own alias reported before the play: that context isn't learned
        as the alias from a read that can be stale (ContextCheck). A read naming the take
        playing now (`mpris_id`, one of the item's tracks), and not the track loaded before the
        play, isn't stale: the alias is learned from it, and the state has caught up. A track
        that was loaded before the play too proves nothing (a re-queued item starts where it
        stalled)."""
        before_track = self._before.track_id if self._before is not None else None
        if (
            check != "context_changed"
            or not self._context.liked
            or mpris_id is None
            or state.track_id != mpris_id
            or state.track_id == before_track
            or not self._is_item_track(mpris_id)
            or self._check_player(state, settled=True) != "ok"
        ):
            return False
        self._note_caught_up(state)
        return True

    def _note_caught_up(self, state: PlayerState | None) -> bool:
        """For a read `_check_player` found ok: whether it shows our device on the item's
        context. Then GET /me/player has caught up with the play, and from now on a mismatch is
        acted on at once."""
        if (
            state is None
            or state.context_uri is None
            or state.device is None
            or state.device.id != self._device_id
        ):
            return False
        self._caught_up = True
        self._deadlines.pop("player_recheck", None)
        return True

    def _is_item_track(self, mpris_id: str | None) -> bool:
        """MPRIS's id (D10) names one of the item's tracks. By id only: a title can be any
        context's. A whole item has no track list, so MPRIS never vouches for one."""
        plan = self._plan
        if mpris_id is None or plan is None:
            return False
        return any(track.track_id == mpris_id for track in plan.tracks)

    def _playing_mpris_id(self) -> str | None:
        """MPRIS's id of the take recording now, from its start (when the titles agreed)."""
        takes = self._takes
        take = takes.open_take() if takes is not None else None
        return take.mpris_track_id if take is not None else None

    async def _act_on_check(self, check: _Check, state: PlayerState | None) -> None:
        if check == "takeover" and state is not None and state.device is not None:
            await self._on_takeover(state.device)
        elif check == "context_changed" and state is not None:
            await self._on_context_changed(state.context_uri)

    async def _on_takeover(self, device: Device) -> None:
        """Playback moved to another device: the take is discarded, the item interrupted, and
        the player left alone (the run engine pauses the run)."""
        if self._facts.takeover is not None:
            return
        takes = self._takes
        assert takes is not None
        open_take = takes.open_take()
        self._facts.takeover = Takeover(
            device=device, discarded_take_id=open_take.take_id if open_take else None
        )
        log.warning("item %s: playback moved to %s", self.job.item_id, device.name)
        self._cut_as("interrupted")
        await self._stop_session(now=True)
        await self._begin_finishing(pause=False)

    async def _on_context_changed(self, uri: str | None) -> None:
        """The context moved on (autoplay): stop at once and end the item. The take cut now is
        the new context's, so it's skipped, not failed."""
        if self._facts.context_moved:
            return
        self._facts.context_moved = True
        self._cut_reason = None
        message = "Playback moved on to another context (autoplay?), so the item was stopped."
        facts = {"context_uri": uri or ""}
        await self._controller_error("context_changed", message, fatal=True, facts=facts)
        await self._pause_player()
        await self._stop_session(now=True)
        await self._begin_finishing(pause=False)

    # --- The play loop: stops and deadlines ----------------------------------------------------

    async def _on_stop(self, request: StopRequest) -> None:
        """The run engine's stop (ItemControl): after this track, or now. While finishing, now
        is after this track too (module docstring, "Stops"): nothing plays any more, and the
        take waiting for the idle exit is kept."""
        previous, self._facts.stop = self._facts.stop, request
        if request.mode == "now":
            if self._finishing:
                await self._stop_session(now=False)  # cuts nothing: the take waits for the exit
                return
            # Only a stop sent as {now: true} cuts the take: the user's or a shutdown's, skipped.
            self._cut_as("discarded")
            await self._stop_session(now=True, quick=True)
            await self._begin_finishing()
        elif previous is None:
            await self._stop_session(now=False)

    def _cut_as(self, reason: CutReason) -> None:
        """How a planned take cut from now on ends (item_takes.py). The first cut decides: once a
        `session.stop {now}` went out (a takeover, a capture problem, Stop now), a later stop
        doesn't change what the take it cut becomes. Nothing does once the context moved on."""
        if not self._facts.context_moved and self._session_stop != "now":
            self._cut_reason = reason

    async def _on_deadlines(self) -> None:
        now = self.services.clock.monotonic()
        for name, at in sorted(self._deadlines.items(), key=lambda item: item[1]):
            if at <= now and self._deadlines.get(name) == at:
                del self._deadlines[name]
                await self._deadline_passed(name)

    async def _deadline_passed(self, name: str) -> None:
        timeouts = self.job.timeouts
        item = self.job.item_id
        if name == "first_track_replay":
            log.warning("item %s: no track started yet: playing again", item)
            await self._play(self._first_offset_uri, first=True)
        elif name == "first_track_give_up":
            message = f"No track started within {timeouts.first_track_give_up_s:.0f} s of the play."
            await self._controller_error("recorder_timeout", message, fatal=True)
            self._facts.failure = self._facts.failure or Ending(
                "failed", message, error_code="recorder_timeout"
            )
            self._terminate()
        elif name == "item_max":
            log.warning(
                "item %s: past its time limit: the take playing finishes, then it ends", item
            )
            self._facts.hit_item_max = True
            await self._stop_session(now=False)  # the take playing is saved; the session ends
            self._deadlines["item_max_stop"] = (
                self.services.clock.monotonic() + self._open_take_left_s() + TAKE_END_MARGIN_S
            )
        elif name in ("finishing", "stall_exit", "item_max_stop"):
            log.warning("item %s: the recorder is still running: stopping it", item)
            self._terminate()
        elif name == "webapi_check":
            state = await self._player_state()
            check = self._confirmed_check(state, mpris_id=self._playing_mpris_id())
            await self._act_on_check(check, state)
            if not self._finishing:
                self._deadlines["webapi_check"] = (
                    self.services.clock.monotonic() + timeouts.webapi_check_s
                )
            await self._judge_pause()  # the read may have caught up, ending the re-reads
        elif name == "player_recheck":
            await self._recheck_player()
            await self._judge_pause()

    async def _begin_finishing(self, *, pause: bool = True) -> None:
        """Playback is over: the `finishing` phase, its deadline, and the player paused."""
        if self._finishing:
            return
        self._finishing = True
        self._finishing_at = self.services.clock.now()
        self._paused_since = None
        for name in (
            "first_track_replay",
            "item_max",
            "item_max_stop",
            "webapi_check",
            "player_recheck",
            "stall_exit",
        ):
            self._deadlines.pop(name, None)
        timeouts = self.job.timeouts
        self._deadlines["finishing"] = (
            self.services.clock.monotonic() + timeouts.idle_exit_s + timeouts.finishing_extra_s
        )
        await self._enter("finishing")
        if pause:
            await self._pause_if_playing()

    def _open_take_left_s(self) -> float:
        """How much of the take recording now is left to play, in seconds (0 when none is)."""
        takes = self._takes
        assert takes is not None
        take = takes.open_take()
        return self._take_left_s(take) if take is not None else 0.0

    def _take_left_s(self, take: Take) -> float:
        """How much of a take is left to play, in seconds: its length less the time since it
        started (0 past its end, or when its length is unknown)."""
        if take.length_ms <= 0:
            return 0.0
        played_s = (self.services.clock.now() - take.started_at).total_seconds()
        return max(0.0, take.length_ms / 1000 - played_s)

    # --- The recorder: stopping it ---------------------------------------------------------------

    async def _stop_session(self, *, now: bool, quick: bool = False) -> None:
        """`session.stop`: now (the take is discarded) or after the current take. When spytifyd
        doesn't answer, it gets SIGTERM instead."""
        session = self._session
        assert session is not None
        if self._session_stop == "now" or (not now and self._session_stop is not None):
            return
        self._session_stop = "now" if now else "after_track"
        if session.returncode is not None:
            return
        try:
            await session.call(sp.SESSION_STOP, {"now": now}, timeout_s=STOP_RPC_TIMEOUT_S)
        except RecorderRpcError as exc:
            if exc.code != sp.NO_SESSION:  # no session: it's already ending
                log.warning("item %s: session.stop failed: %s", self.job.item_id, exc)
                self._terminate_for_stop(now=now, quick=quick)
        except RecorderGone:
            # The socket is gone. Exiting, or spytifyd dropped us (512 lines behind) and records
            # on: then signals stop it (the first SIGTERM finishes the take, as {now: false}).
            if session.returncode is None:
                log.warning("item %s: the recorder's socket is gone: SIGTERM", self.job.item_id)
                self._terminate_for_stop(now=now, quick=quick)
        except TimeoutError as exc:
            log.warning("item %s: session.stop: %s", self.job.item_id, exc)
            self._terminate_for_stop(now=now, quick=quick)

    def _terminate_for_stop(self, *, now: bool, quick: bool) -> None:
        """Signals in place of a `session.stop` that didn't get through. After the take: the
        first SIGTERM's wait lasts at least until the take playing has ended."""
        if now:
            self._terminate(quick=quick)
            return
        grace = self.job.timeouts.sigterm_first_grace_s
        self._terminate(first_grace_s=max(grace, self._open_take_left_s() + TAKE_END_MARGIN_S))

    def _terminate(self, *, quick: bool = False, first_grace_s: float | None = None) -> None:
        """Starts terminate() once, in the item's task group (it can take up to a minute, or
        `first_grace_s` and 15 s)."""
        if self._terminating or self._group is None:
            return
        self._terminating = True
        timeouts = self.job.timeouts
        if quick:
            first, second = QUICK_FIRST_GRACE_S, QUICK_SECOND_GRACE_S
        else:
            first, second = timeouts.sigterm_first_grace_s, timeouts.sigterm_second_grace_s
        if first_grace_s is not None:
            first = first_grace_s
        self._group.create_task(self._terminate_session(first, second))

    async def _terminate_session(self, first_grace_s: float, second_grace_s: float) -> None:
        session = self._session
        assert session is not None
        try:
            code = await session.terminate(
                first_grace_s=first_grace_s, second_grace_s=second_grace_s
            )
            log.info("item %s: the recorder stopped with code %s", self.job.item_id, code)
        except PortError as exc:
            log.warning("item %s: stopping the recorder failed: %s", self.job.item_id, exc)

    async def _wait_for_exit(self) -> int:
        """The exit code. The notifications only end after the exit, but a recorder still
        running past the finishing time is killed."""
        session = self._session
        assert session is not None
        if session.returncode is None:
            timeouts = self.job.timeouts
            waiter = asyncio.ensure_future(session.wait())
            await self._wait_at_most(waiter, timeouts.idle_exit_s + timeouts.finishing_extra_s)
            if not waiter.done():
                waiter.cancel()
                log.warning("item %s: the recorder outlived its events: kill", self.job.item_id)
                self._terminating = True
                return await session.kill()
        return await session.wait()

    async def _check_exit_code(self) -> None:
        """An exit with an error that nobody here caused: error `recorder_exit`."""
        code = self._exit_code
        if code is None or code == 0 or self._terminating:
            return
        verdict = sp.classify_exit(code, [])
        self._facts.crashed = f"The recorder exited with code {code} ({verdict.cause})."
        await self._controller_error("recorder_exit", self._facts.crashed, fatal=True)

    async def _kill_leftover_recorder(self) -> None:
        """Never leaves a recorder running behind (an unexpected error, or a cancellation)."""
        session = self._session
        if session is None or session.returncode is not None:
            return
        log.warning("item %s: the recorder was still running: killing it", self.job.item_id)
        with contextlib.suppress(PortError):
            await session.kill()
        self._note_if_killed(-9)

    async def _read_lost_events(self) -> None:
        """The --events file holds what the socket may have lost as spytifyd exited (the last
        take's track.finished, the phantom take): results nobody has yet are taken from it."""
        session, takes = self._session, self._takes
        assert session is not None and takes is not None
        try:
            records = await session.events_file()
        except (PortError, OSError) as exc:
            log.warning("item %s: the --events file can't be read: %s", self.job.item_id, exc)
            return
        changed = False
        for record in records:
            if record.method not in _TAKE_EVENTS:
                continue  # only takes matter here; parsing the rest would hold up the loop
            event = sp.parse_notification(record.method, record.params)
            if isinstance(event, sp.TrackStarted) and takes.get(event.id) is None:
                await takes.start(self._lost_take(event, record.received_at))
            elif isinstance(event, sp.TrackFinished):
                take = takes.get(event.id)
                if take is not None and take.result is None:
                    changed = await takes.finish(event) or changed
            elif isinstance(event, sp.TrackSkipped):
                take = takes.get(event.id)
                if take is not None and take.result is None:
                    changed = await takes.skip(event, cut_reason=self._cut_reason) or changed
        if changed:
            await self._counts_changed()

    def _lost_take(self, event: sp.TrackStarted, at: datetime) -> Take:
        """A take whose start only the --events file has: one of the last moments of the
        session, so it's taken as a phantom (not counted). A whole item's steering hears of it
        too: the phantom of the first track heard means the context ended at its start."""
        steering, plan = self._steering, self._plan
        assert steering is not None and plan is not None
        if plan.mode == "whole":
            steering.on_track_started(
                track_id=None, title=event.title, artist=event.artist, playing=False
            )
        hits = steering.loaded_tracks(track_id=None, title=event.title)
        return Take(
            take_id=event.id,
            artist=event.artist,
            title=event.title,
            album=event.album,
            length_ms=event.length_ms,
            cover_url=event.cover_url,
            key=track_key(event.artist, event.title),
            started_at=at,
            track=hits[0] if hits else None,
            phantom=True,
        )

    async def _settle_player(self) -> None:
        """Bug 1's Next can restart the player as the recorder exits: pause it again."""
        if self._facts.takeover is not None:
            return
        await self.services.clock.sleep(AFTER_EXIT_CHECK_S)
        await self._pause_if_playing()

    # --- The end ---------------------------------------------------------------------------------

    async def _conclude(self) -> ItemReport:
        plan, takes, steering = self._plan, self._takes, self._steering
        assert plan is not None and takes is not None and steering is not None
        if await takes.close_unfinished(cut_reason=self._cut_reason, file_error=self._file_error):
            await self._counts_changed()
        facts = self._facts
        facts.mode = plan.mode
        facts.still_missing = await self._still_missing()
        facts.failed_reasons = takes.failed_reasons()
        facts.guard_cut_pass = steering.guarded and not steering.wrapped
        ending = decide(facts)
        clean = await self._write_item_rows(ending.outcome, clean_full_pass=self._clean(ending))
        await self._fix_modes()
        await self._write_m3u()
        return self._report(
            ending.outcome,
            still_missing=facts.still_missing,
            reason=ending.reason,
            error_code=ending.error_code or self._error_code,
            run_failure=ending.run_failure,
            interrupted_by=ending.interrupted_by,
            takeover=facts.takeover if ending.interrupted_by == "takeover" else None,
            recorder_exit_code=self._exit_code,
            clean_full_pass=clean,
        )

    def _clean(self, ending: Ending) -> bool:
        """D13: a whole pass of a playlist without item access, heard to its end, with every
        track it heard in Spytify's index (module docstring, "D13's clean full pass")."""
        plan, takes, steering = self._plan, self._takes, self._steering
        assert plan is not None and takes is not None and steering is not None
        return (
            plan.mode == "whole"
            and not plan.item_access
            and ending.outcome == "done"
            and steering.wrapped
            and takes.counts().failed == 0
            and not takes.skipped_for(_UNCLEAN_SKIPS)
            and bool(self._observed())
        )

    def _observed(self) -> list[Take]:
        """The tracks a whole pass heard, for observed_tracks: those Spytify's index has now
        (recorded, or skipped as already recorded); ads and other skips are left out."""
        takes = self._takes
        assert takes is not None
        return [
            take
            for take in takes.heard()
            if take.result == "recorded"
            or (take.result == "skipped" and take.reason == "duplicate")
        ]

    async def _still_missing(self) -> int | None:
        """Planned tracks still not in Spytify's index, read again now."""
        plan = self._plan
        assert plan is not None
        if plan.mode != "missing_only":
            return None
        self.services.matching.invalidate()
        index = await self.services.matching.index()
        return sum(1 for track in plan.missing if not index.has(track.key))

    async def _write_item_rows(self, outcome: ItemOutcome, *, clean_full_pass: bool) -> bool:
        """`items`: last_backup_at (done, up to date, partial), an album's completed_at once
        every track is recorded, and D13's rows after a clean full pass. Returns whether the
        D13 rows were written."""
        plan = self._plan
        assert plan is not None
        now = iso_ms(self.services.clock.now())
        item_id, run_id = self.job.item_id, self.job.run_id
        complete = False
        if self.job.kind == "album" and plan.mode == "missing_only" and plan.tracks:
            index = await self.services.matching.index()
            complete = all(index.has(track.key) for track in plan.tracks)
        observed = [
            (item_id, ordinal, take.key, take.artist, take.title, take.mpris_track_id,
             take.length_ms or None, run_id)
            for ordinal, take in enumerate(self._observed() if clean_full_pass else [], start=1)
        ]  # fmt: skip

        def write(conn: sqlite3.Connection) -> bool:
            if outcome in ("done", "up_to_date", "partial"):
                conn.execute("UPDATE items SET last_backup_at = ? WHERE id = ?", (now, item_id))
            if complete:
                conn.execute(
                    "UPDATE items SET completed_at = coalesce(completed_at, ?) "
                    "WHERE id = ? AND kind = 'album'",
                    (now, item_id),
                )
            if not observed:
                return False
            snapshot = conn.execute(
                "SELECT snapshot_id FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if snapshot is None or snapshot[0] is None:
                return False  # no snapshot_id to compare with next time
            conn.execute("DELETE FROM observed_tracks WHERE item_id = ?", (item_id,))
            conn.executemany(
                "INSERT INTO observed_tracks (item_id, ordinal, spytify_key, artist, title, "
                "track_id, length_ms, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                observed,
            )
            conn.execute(
                "UPDATE items SET last_full_pass_snapshot = ?, last_full_pass_at = ? WHERE id = ?",
                (snapshot[0], now, item_id),
            )
            return True

        return await self.services.store.transaction(write)

    async def _mark_unavailable(self, reason: str) -> None:
        await self.services.store.execute(
            "UPDATE items SET unavailable_at = ?, unavailable_reason = ? "
            "WHERE id = ? AND unavailable_at IS NULL",
            (iso_ms(self.services.clock.now()), reason, self.job.item_id),
        )

    async def _write_m3u(self) -> None:
        """The item's .m3u (services.files). A failure is logged: it never fails the item."""
        try:
            await self.services.files.write_m3u(self.job.item_id)
        except Exception:
            log.exception("item %s: writing its .m3u failed", self.job.item_id)

    async def _fix_modes(self) -> None:
        """The files this item saved get UMASK's mode: Spytify leaves tagged files at 0600
        (bug 7, files.py). A failure is logged: it never fails the item."""
        takes = self._takes
        assert takes is not None
        paths = [take.path for take in takes.takes.values() if take.path]
        if not paths:
            return
        try:
            await self.services.files.fix_modes(paths)
        except Exception:
            log.exception("item %s: setting its files' modes failed", self.job.item_id)

    async def _cleanup_stale(self) -> None:
        """Stale WAVs in `.spytify/` (bug 4), while no recorder runs: between items only that
        folder (files.py), the whole music folder only at start-up or after a recorder was
        killed (bug 5's .part files). Never fatal."""
        try:
            await self.services.files.cleanup_stale(folders=[])
        except Exception:
            log.exception("item %s: cleaning up stale files failed", self.job.item_id)

    def _note_if_killed(self, code: int | None) -> None:
        """A recorder ended by a signal may have left a .part where it was encoding (bug 5):
        the next cleanup that can see it stale walks the whole music folder."""
        if code is not None and code < 0:
            self.services.files.recorder_killed()

    # --- Small helpers ---------------------------------------------------------------------------

    async def _enter(self, phase: ItemState) -> None:
        """Moves to `phase` (once) and tells the run engine."""
        if phase in self._reported:
            return
        clock = self.services.clock
        now = clock.monotonic()
        if self._reported:
            spent = self._phase_s.get(self._phase, 0.0) + now - self._phase_since
            self._phase_s[self._phase] = spent
        self._phase, self._phase_since = phase, now
        self._reported.add(phase)
        plan = self._plan
        if phase == "planning" or plan is None:
            await self.host.item_phase(self.job, phase)
        else:
            await self.host.item_phase(self.job, phase, mode=plan.mode, planned=plan.planned)

    async def _counts_changed(self) -> None:
        takes = self._takes
        assert takes is not None
        counts = takes.counts()
        if counts != self._counts_sent:
            self._counts_sent = counts
            await self.host.item_counts(self.job, counts)

    async def _controller_error(
        self,
        code: ControllerErrorCode,
        message: str,
        *,
        fatal: bool,
        facts: dict[str, str] | None = None,
    ) -> None:
        """The controller's own `error` event (events.md, source controller)."""
        if self._error_code is None:
            self._error_code = code
        log.warning("item %s: %s: %s", self.job.item_id, code, message)
        self.services.bus.publish(
            "error",
            {
                "source": "controller",
                "code": code,
                "message": message,
                "fatal": fatal,
                "withdrawn": False,
                "run_id": self.job.run_id,
                "item_id": self.job.item_id,
                "facts": facts,
            },
        )

    async def _webapi_failed_early(self, exc: WebApiError, doing: str) -> ItemReport:
        message = f"Spotify's Web API failed while {doing}: {exc}"
        await self._controller_error("webapi", message, fatal=True)
        return self._report(
            "failed", reason=message, error_code="webapi", run_failure=_run_failure_for(exc)
        )

    async def _identify(self, title: str, *, wait: bool) -> str | None:
        """D10: the loaded track's id from MPRIS `mpris:trackid`, once MPRIS's title agrees
        with track.started's (its metadata can lag). None when it doesn't agree within 3 s, or
        at once without `wait`."""
        wanted = go_lower(go_trim(title))
        mpris = self.services.ports.mpris
        for attempt in range(IDENTIFY_TRIES if wait else 1):
            if attempt:
                await self.services.clock.sleep(IDENTIFY_STEP_S)
            try:
                meta = await mpris.metadata()
            except MprisUnavailable:
                return None
            if meta is not None and go_lower(go_trim(meta.title or "")) == wanted:
                return meta.track_id
        return None

    def _fallback_id(self, state: PlayerState | None, title: str) -> str | None:
        """GET /me/player's track id, only when it names an entry of the item with this title:
        it can be a relinked id, or already the next track's (D10)."""
        plan = self._plan
        if state is None or state.track_id is None or plan is None:
            return None
        wanted = go_lower(go_trim(title))
        for track in plan.tracks:
            if track.track_id == state.track_id and go_lower(go_trim(track.title)) == wanted:
                return state.track_id
        return None

    async def _player_status(self) -> PlaybackStatus | None:
        try:
            return await self.services.ports.mpris.playback_status()
        except MprisUnavailable:
            return None

    def _may_check_now(self) -> bool:
        """A track start's GET /me/player, unless one was sent under TRACK_CHECK_MIN_S ago."""
        return self.services.clock.monotonic() - self._checked_at >= TRACK_CHECK_MIN_S

    async def _player_state(self) -> PlayerState | None:
        """GET /me/player, or None when it fails (nothing is concluded from a failure)."""
        self._checked_at = self.services.clock.monotonic()
        try:
            return await self.services.ports.webapi.player_state(scope=self._scope)
        except WebApiError as exc:
            log.warning("item %s: GET /me/player failed: %s", self.job.item_id, exc)
            return None

    async def _pause_player(self) -> None:
        """Pauses our client over MPRIS (the Web API as the fallback). Never after a takeover:
        our client's controls could pause the other device."""
        if self._facts.takeover is not None:
            return
        try:
            await self.services.ports.mpris.pause()
            return
        except MprisNoClient:
            return  # no client: nothing plays
        except MprisUnavailable as exc:
            log.warning("item %s: MPRIS Pause failed: %s", self.job.item_id, exc)
        try:
            await self.services.ports.webapi.pause(device_id=self._device_id, scope=self._scope)
        except WebApiError as exc:
            log.warning("item %s: the Web API's pause failed: %s", self.job.item_id, exc)

    async def _pause_if_playing(self) -> None:
        if self._facts.takeover is None and await self._player_status() == "Playing":
            await self._pause_player()

    async def _wait_at_most(self, future: "asyncio.Future[object]", seconds: float) -> None:
        """Waits until `future` is done, or `seconds` of clock time passed."""
        sleeper = asyncio.ensure_future(self.services.clock.sleep(seconds))
        try:
            await asyncio.wait({future, sleeper}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sleeper

    def _timings(self) -> ItemTimings:
        clock = self.services.clock
        phase_s = dict(self._phase_s)
        phase_s[self._phase] = phase_s.get(self._phase, 0.0) + clock.monotonic() - self._phase_since
        plan = self._plan
        return ItemTimings(
            started_at=self._started_at,
            ended_at=clock.now(),
            phase_s=phase_s,
            recorder_started_at=self._recorder_started_at,
            first_track_at=self._first_track_at,
            finishing_at=self._finishing_at,
            recorder_exit_at=self._recorder_exit_at,
            planned_ms=plan.planned_ms if plan is not None else None,
        )

    def _report(self, outcome: ItemOutcome, **fields: Any) -> ItemReport:
        """The ItemReport: the counts, the timings, the plan's mode and size, and `fields`
        (any of ItemReport's other fields)."""
        plan, takes = self._plan, self._takes
        known = plan is not None and not plan.unavailable
        return ItemReport(
            outcome=outcome,
            counts=takes.counts() if takes is not None else TrackCounts(),
            timings=self._timings(),
            mode=plan.mode if plan is not None and known else None,
            planned=plan.planned if plan is not None and known else None,
            **fields,
        )


# --- Module helpers ------------------------------------------------------------------------------


def _run_failure_for(exc: WebApiError) -> RunFailure | None:
    """A Web API error that stops the whole run: no connection, or an expired one."""
    if isinstance(exc, NotConnected):
        return RunFailure("not_connected", "The Web API isn't connected.")
    if isinstance(exc, ConnectionExpired):
        return RunFailure("connection_expired", "The Web API connection has expired: reconnect.")
    return None


def _what_it_reports(state: PlayerState, check: _Check) -> str:
    """For the log: the other device, or the other context."""
    if check == "takeover" and state.device is not None:
        return f"{state.device.name} active"
    return f"the context {state.context_uri}"


def _new_take_book(
    services: "Services", job: ItemJob, plan: ItemPlan, settings: list[tuple[str, str]]
) -> TakeBook:
    """The take book, with the file format and bitrate the recorder is given (for `files`)."""
    values = dict(settings)
    bitrate = values.get("encode.bitrate_kbps")
    return TakeBook(
        services,
        job,
        plan,
        file_format=values.get("encode.format", "mp3"),
        bitrate=int(bitrate) if bitrate is not None else None,
    )


def _make_folders(spec: RecorderSpec) -> None:
    """The log folder and spytifyd's (empty) working folder. Blocking: run in a thread."""
    spec.log_file.parent.mkdir(parents=True, exist_ok=True)
    spec.events_file.parent.mkdir(parents=True, exist_ok=True)
    spec.work_dir.mkdir(parents=True, exist_ok=True)
