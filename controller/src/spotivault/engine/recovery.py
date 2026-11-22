"""Start-up recovery (plan § Run states: "unfinished runs become failed 'container restarted'.
Then orphan recorders are killed, sockets and WAVs are cleaned up, and the player is paused.").

Owner: **engine-run**. Called by RunEngine.recover(), a start-up hook that runs before the
scheduler's, and `fail_unfinished_run` also by RunEngine.shutdown() when a run can't be ended
within the SIGTERM bound.

- Every `runs` row with kind run and state <> 'ended': state ended, outcome failed, reason
  container_restarted, counters summed from its run_items, Web API counts from the usage log,
  and ended_at the last thing it did (the latest of its track_results' started_at/finished_at
  and run_items' started_at/ended_at, else its own started_at), not now: a restart hours later
  mustn't make it look hours long. This is a repair, not a transition: the states are written
  directly. Its current item (an active phase) → interrupted (interrupted_by shutdown); its
  waiting items → stopped; a take still recording (track_results.result NULL) → failed
  `interrupted`, since nobody else will ever finish it. Nothing is published (no client can be
  connected yet); one log line each.
- `ports.recorder.kill_orphans()`, then remove `config.runtime_dir/spytify-*.sock` (to_thread).
- `services.files.cleanup_stale()` (the whole music folder). When orphans were killed, an encode
  of theirs may have left a `.part` too fresh for it: `services.files.recorder_killed()`, so the
  first cleanup before an item a minute later walks the folder again.
- `ports.mpris.pause()` when `playback_status()` is Playing; MprisUnavailable is fine.
- `services.client.set_run_active(False)`.

Each step is on its own: one that fails is logged, and the others still run (a start-up hook
that raises would stop the controller).
"""

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spotivault.engine.states import ACTIVE_STATES, WAITING_STATES
from spotivault.ports import ApiScope, MprisUnavailable

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    runs_failed: int
    orphans_killed: int
    sockets_removed: int
    files_removed: int
    player_paused: bool


async def recover(services: "Services") -> RecoveryResult:
    """Start-up recovery, as the module docstring says."""
    runs_failed = 0
    try:
        rows = await services.store.fetchall(
            "SELECT id FROM runs WHERE kind = 'run' AND state <> 'ended' ORDER BY id"
        )
        for row in rows:
            await fail_unfinished_run(services, row["id"])
            runs_failed += 1
    except Exception:
        log.exception("runs: recovery couldn't end the unfinished runs")

    orphans = 0
    try:
        orphans = await services.ports.recorder.kill_orphans()
    except Exception:
        log.exception("runs: recovery couldn't look for orphan recorders")

    sockets = 0
    try:
        sockets = await asyncio.to_thread(remove_sockets, services.config.runtime_dir)
    except Exception:
        log.exception("runs: recovery couldn't remove old recorder sockets")

    files = 0
    try:
        cleaned = await services.files.cleanup_stale()
        files = cleaned.wavs_removed + cleaned.parts_removed
        if orphans:
            services.files.recorder_killed()
    except Exception:
        log.exception("runs: recovery couldn't clean up stale recordings")

    paused = await _pause_player(services)

    try:
        await services.client.set_run_active(False)
    except Exception:
        log.exception("runs: recovery couldn't clear the client's run flag")

    if runs_failed or orphans or sockets or files or paused:
        log.info(
            "runs: recovery: %d run(s) failed (container restarted), %d orphan recorder(s) "
            "killed, %d socket(s) and %d stale file(s) removed%s",
            runs_failed,
            orphans,
            sockets,
            files,
            ", the player paused" if paused else "",
        )
    return RecoveryResult(
        runs_failed=runs_failed,
        orphans_killed=orphans,
        sockets_removed=sockets,
        files_removed=files,
        player_paused=paused,
    )


async def fail_unfinished_run(services: "Services", run_id: int) -> None:
    """Ends one unfinished run as failed (container_restarted), as the module docstring says.
    Does nothing to a run that has ended already."""
    try:
        api = await services.webapi_usage.finish_scope(ApiScope("run", run_id))
        api_counts: tuple[int | None, int | None, int | None] = (
            api.requests,
            api.retried,
            api.rate_limited,
        )
    except Exception:
        log.exception("runs: run %d's Web API counts can't be read", run_id)
        api_counts = (None, None, None)

    active = tuple(ACTIVE_STATES)
    waiting = tuple(WAITING_STATES)

    def repair(conn: sqlite3.Connection) -> str | None:
        run = conn.execute(
            "SELECT started_at FROM runs WHERE id = ? AND kind = 'run' AND state <> 'ended'",
            (run_id,),
        ).fetchone()
        if run is None:
            return None
        last = conn.execute(_LAST_ACTIVITY, (run_id,) * 4).fetchone()[0] or run["started_at"]
        conn.execute(
            "UPDATE track_results SET result = 'failed', reason = 'interrupted', "
            "finished_at = coalesce(finished_at, ?) WHERE result IS NULL AND run_item_id IN "
            "(SELECT id FROM run_items WHERE run_id = ?)",
            (last, run_id),
        )
        # Waiting items first, so the current one, interrupted below, stays interrupted.
        conn.execute(
            f"UPDATE run_items SET state = 'stopped' WHERE run_id = ? "
            f"AND state IN ({_marks(waiting)})",
            (run_id, *waiting),
        )
        conn.execute(
            "UPDATE run_items SET state = 'interrupted', interrupted_by = 'shutdown', "
            "interrupted_count = min(2, interrupted_count + 1), ended_at = coalesce(ended_at, ?) "
            f"WHERE run_id = ? AND state IN ({_marks(active)})",
            (last, run_id, *active),
        )
        counts = conn.execute(
            "SELECT coalesce(sum(recorded), 0), coalesce(sum(skipped - skipped_other), 0), "
            "coalesce(sum(skipped_other), 0), coalesce(sum(failed), 0), coalesce(sum(bytes), 0) "
            "FROM run_items WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        conn.execute(
            "UPDATE runs SET state = 'ended', outcome = 'failed', reason = 'container_restarted', "
            "ended_at = ?, recorded = ?, skipped_duplicate = ?, skipped_other = ?, failed = ?, "
            "bytes_added = ?, api_requests = ?, api_retried = ?, api_rate_limited = ? "
            "WHERE id = ?",
            (last, *tuple(counts), *api_counts, run_id),
        )
        return str(last)

    ended_at = await services.store.transaction(repair)
    if ended_at is not None:
        log.warning(
            "runs: run %d didn't finish (the container restarted); ended failed, as of %s",
            run_id,
            ended_at,
        )


# The latest moment a run did anything: its items' and takes' times. ISO times compare as text.
_LAST_ACTIVITY = (
    "SELECT max(t) FROM ("
    " SELECT started_at AS t FROM run_items WHERE run_id = ?"
    " UNION ALL SELECT ended_at FROM run_items WHERE run_id = ?"
    " UNION ALL SELECT tr.started_at FROM track_results tr"
    "  JOIN run_items ri ON ri.id = tr.run_item_id WHERE ri.run_id = ?"
    " UNION ALL SELECT tr.finished_at FROM track_results tr"
    "  JOIN run_items ri ON ri.id = tr.run_item_id WHERE ri.run_id = ?"
    ")"
)


def _marks(values: tuple[str, ...]) -> str:
    return ", ".join("?" for _ in values)


def remove_sockets(runtime_dir: Path) -> int:
    """Removes leftover recorder sockets (`spytify-*.sock`). Blocking: run it in a thread."""
    removed = 0
    if not runtime_dir.is_dir():
        return 0
    for path in runtime_dir.glob("spytify-*.sock"):
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            pass
    return removed


async def _pause_player(services: "Services") -> bool:
    """Pauses the client if it's playing (a crash mid-item leaves it playing). True if paused."""
    mpris = services.ports.mpris
    try:
        if await mpris.playback_status() != "Playing":
            return False
        await mpris.pause()
        return True
    except MprisUnavailable:
        return False  # the client isn't up yet: nothing plays
    except Exception:
        log.exception("runs: recovery couldn't pause the player")
        return False
