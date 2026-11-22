"""History: the run list, a run's page, an item's tracks in a run, and the Dashboard's Last run.

Owner: **history-files-metrics** (controller/ARCHITECTURE.md § S6's parts). Built by
services.py as `services.history`. Frozen interface: the HistoryService methods below;
`history_row` is shared (the run engine and the scheduler publish `run.finished` with it). The
router is api/routers/history.py, this builder's too.

Specs: web-ui.md § History (Runs tab, Run page, endpoints) and § Dashboard (Last run);
openapi.yaml listRuns, getLastRun, getRun, getRunItemTracks and `HistoryRow`, `RunDetail`,
`RunItem`, `TrackResult`, `LastRun`; contracts/schema.sql `runs`, `run_items`, `track_results`,
`files`; engine/states.py `item_badges` (frozen).

- **listRuns:** newest first (started_at, then id), the missed, skipped and held rows and a run
  still going included. `cursor` is opaque: encode the last row's (started_at, id), and refuse a
  cursor that doesn't decode (422 validation_failed, field cursor). Filters: `with_issues` =
  outcome completed_with_issues or failed, and every no-run row; `scheduled` = trigger scheduled
  or startup; `run_now` = trigger run_now.
- **HistoryRow:** `duration_s` from started_at to ended_at (null while going), `counters` only
  for kind run (null otherwise), `window` when window_start is set.
- **getRun:** RunItem per run_items row, in the order they ran (ran_order), then the ones that
  never ran (queue_pos), numbered on from there (`order` ≥ 1). `cover` is the item's thumbnail
  URL (`/api/library/{id}/cover?size=thumb` or `/api/albums/{id}/cover?size=thumb`) when the item
  has one. `can_retry`: it has failed tracks and its item isn't removed. 404 not_found for an
  unknown run id; a no-run row is a run page with no items.
- **getRunItemTracks:** one TrackResult per take (track_results, in started_at order), joined to
  `files` (size, path relative to the music folder) and `tracks` (artists, when matched).
  `position` is item_tracks' 0-based position + 1. 404 when the run or the item isn't there.
- **getLastRun:** the newest ended run of kind run, and up to three items with problems
  (partial, failed or unavailable, or with failed tracks), most failed tracks first, with a
  one-line message such as "2 tracks failed: low volume". `run` null before the first run.

Choices where the specs are silent (reported to the user):
- A take still recording (`track_results.result` NULL) is left out of getRunItemTracks: the
  contract's `result` has no value for it. The live track table comes from the WebSocket.
- A failed item's message in getLastRun, when no track failed, is the engine's own English
  reason (`run_items.reason`); with neither, a fixed phrase for the state.
"""

import base64
import json
import sqlite3
from typing import TYPE_CHECKING, Any, Literal

from spotivault.api.models import (
    Counters,
    GetRunItemTracksResponse,
    HistoryRow,
    HistoryRowWindow,
    LastRun,
    LastRunIssue,
    ListRunsResponse,
    RunDetail,
    RunItem,
    RunItemCounts,
    TrackResult,
)
from spotivault.catalog.covers import cover_url
from spotivault.clock import parse_iso
from spotivault.engine.states import ISSUE_STATES, item_badges
from spotivault.errors import not_found, validation_failed

if TYPE_CHECKING:
    from spotivault.services import Services

type RunFilter = Literal["all", "with_issues", "scheduled", "run_now"]

# The filter chips as SQL over `runs` (constant text; the values are never interpolated).
_FILTER_SQL: dict[RunFilter, str] = {
    "all": "1 = 1",
    "with_issues": "(kind <> 'run' OR outcome IN ('completed_with_issues', 'failed'))",
    "scheduled": "trigger IN ('scheduled', 'startup')",
    "run_now": "trigger = 'run_now'",
}

# Spytify's failure reasons, in words for the one-line messages (openapi.yaml TrackResult.reason).
# A failed `discarded` with a file is a partial take. `discarded_by_stop` isn't a stored reason:
# _issues gives it to a failed `discarded` with no file, a take Stop now cut in an older run, from
# before such a take was skipped.
_FAILED_REASON_WORDS: dict[str, str] = {
    "low_volume": "low volume",
    "recorder_error": "recorder error",
    "unavailable": "track unavailable",
    "interrupted": "interrupted",
    "discarded": "partial take",
    "discarded_by_stop": "discarded by Stop now",
}


# --- The cursor


def encode_cursor(started_at: str, run_id: int) -> str:
    """An opaque cursor for the row after (started_at, run_id): URL-safe base64 of a JSON pair."""
    raw = json.dumps([started_at, run_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, int]:
    """(started_at, run_id) of a cursor from `encode_cursor`. Anything else is a 422."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        started_at, run_id = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        if not isinstance(started_at, str) or not isinstance(run_id, int):
            raise ValueError("not a (time, id) pair")
        if isinstance(run_id, bool) or run_id < 1:
            raise ValueError("the id isn't a run id")
        parse_iso(started_at)
    except (ValueError, TypeError):  # binascii.Error and UnicodeError are ValueErrors too
        raise validation_failed("cursor", "The cursor isn't one from a runs list.") from None
    return started_at, run_id


# --- Message text


def issue_message(state: str, failed: int, failed_reasons: list[str], reason: str | None) -> str:
    """One line for a Last run issue: "2 tracks failed: low volume". `failed_reasons` are the
    failed takes' Spytify reasons, most common first (and `discarded_by_stop`, see _issues)."""
    if failed > 0:
        words = [_FAILED_REASON_WORDS.get(r, r.replace("_", " ")) for r in failed_reasons]
        message = f"{failed} {'track' if failed == 1 else 'tracks'} failed"
        return message + (": " + ", ".join(words) if words else "")
    if reason:
        return " ".join(reason.split())
    if state == "unavailable":
        return "The playlist can't be found any more"
    if state == "partial":
        return "Ended partial"
    return "Failed"


# --- The service


class HistoryService:
    """Reads History. Built by services.py as `services.history`."""

    def __init__(self, services: "Services") -> None:
        self.services = services

    async def list_runs(
        self, *, cursor: str | None = None, filter: RunFilter = "all", limit: int = 50
    ) -> ListRunsResponse:
        """GET /api/runs."""
        clauses = [_FILTER_SQL[filter]]
        params: list[Any] = []
        if cursor is not None:
            started_at, run_id = decode_cursor(cursor)
            clauses.append("(started_at < ? OR (started_at = ? AND id < ?))")
            params += [started_at, started_at, run_id]
        sql = (
            "SELECT * FROM runs WHERE "
            + " AND ".join(clauses)
            + " ORDER BY started_at DESC, id DESC LIMIT ?"
        )
        # One row more than the page, to know whether there's a next page.
        rows = await self.services.store.fetchall(sql, (*params, limit + 1))
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = page[-1]
            next_cursor = encode_cursor(last["started_at"], last["id"])
        return ListRunsResponse(runs=[_history_row(row) for row in page], next_cursor=next_cursor)

    async def last_run(self) -> LastRun:
        """GET /api/runs/last."""
        row = await self.services.store.fetchone(
            "SELECT * FROM runs WHERE kind = 'run' AND state = 'ended' "
            "ORDER BY started_at DESC, id DESC LIMIT 1"
        )
        if row is None:
            return LastRun(run=None, issues=[])
        return LastRun(run=_history_row(row), issues=await self._issues(row["id"]))

    async def run(self, run_id: int) -> RunDetail:
        """GET /api/runs/{id}. Raises ApiError 404 not_found."""
        try:
            header = await self.history_row(run_id)
        except LookupError:
            raise not_found("No such run.") from None
        # Items in the order they ran; the ones that never ran follow, in queue order.
        rows = await self.services.store.fetchall(
            "SELECT ri.*, i.kind AS item_kind, i.name AS item_name, i.thumb_path, i.image_id, "
            "i.removed_at AS item_removed_at "
            "FROM run_items ri JOIN items i ON i.id = ri.item_id "
            "WHERE ri.run_id = ? "
            "ORDER BY ri.ran_order IS NULL, ri.ran_order, ri.queue_pos, ri.id",
            (run_id,),
        )
        items = [_run_item(order, row) for order, row in enumerate(rows, start=1)]
        return RunDetail(run=header, items=items)

    async def run_item_tracks(self, run_id: int, item_id: str) -> GetRunItemTracksResponse:
        """GET /api/runs/{id}/items/{item}/tracks. Raises ApiError 404 not_found."""
        store = self.services.store
        if await store.fetchone("SELECT 1 FROM runs WHERE id = ?", (run_id,)) is None:
            raise not_found("No such run.")
        run_item = await store.fetchone(
            "SELECT id FROM run_items WHERE run_id = ? AND item_id = ?", (run_id, item_id)
        )
        if run_item is None:
            raise not_found("The item isn't in this run.")
        # A take still recording has no result yet, so it isn't listed (see the module docstring).
        rows = await store.fetchall(
            "SELECT tr.position, tr.track_id, tr.title, tr.artist, tr.result, tr.reason, "
            "tr.take_id, tr.started_at, tr.finished_at, f.bytes AS size_bytes, f.path, "
            "t.artists AS track_artists "
            "FROM track_results tr "
            "LEFT JOIN files f ON f.id = tr.file_id "
            "LEFT JOIN tracks t ON t.id = tr.track_id "
            "WHERE tr.run_item_id = ? AND tr.result IS NOT NULL "
            "ORDER BY tr.started_at, tr.id",
            (run_item["id"],),
        )
        return GetRunItemTracksResponse(tracks=[_track_result(row) for row in rows])

    async def history_row(self, run_id: int) -> HistoryRow:
        """One `runs` row as a HistoryRow, for `run.finished` (the run engine, the scheduler)
        and listRuns. Raises LookupError when there's no such row."""
        row = await self.services.store.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
        if row is None:
            raise LookupError(f"no run {run_id}")
        return _history_row(row)

    async def _issues(self, run_id: int) -> list[LastRunIssue]:
        """Up to three items of a run with problems: most failed tracks first."""
        store = self.services.store
        states = sorted(ISSUE_STATES)
        marks = ", ".join("?" for _ in states)
        rows = await store.fetchall(
            "SELECT ri.id, ri.item_id, ri.state, ri.failed, ri.reason, i.name "
            "FROM run_items ri JOIN items i ON i.id = ri.item_id "
            f"WHERE ri.run_id = ? AND (ri.state IN ({marks}) OR ri.failed > 0) "
            "ORDER BY ri.failed DESC, coalesce(ri.ran_order, ri.queue_pos), ri.id LIMIT 3",
            (run_id, *states),
        )
        issues: list[LastRunIssue] = []
        for row in rows:
            # A failed `discarded` with no file is an older run's Stop now (_FAILED_REASON_WORDS).
            reasons = await store.fetchall(
                "SELECT CASE WHEN reason = 'discarded' AND file_id IS NULL "
                "THEN 'discarded_by_stop' ELSE reason END AS failure "
                "FROM track_results WHERE run_item_id = ? AND result = 'failed' "
                "GROUP BY failure ORDER BY count(*) DESC, failure",
                (row["id"],),
            )
            message = issue_message(
                row["state"],
                row["failed"],
                [r["failure"] for r in reasons if r["failure"]],
                row["reason"],
            )
            issues.append(LastRunIssue(item_id=row["item_id"], name=row["name"], message=message))
        return issues


# --- Row mapping (pure)


def _duration_s(started_at: str, ended_at: str | None) -> int | None:
    if ended_at is None:
        return None
    seconds = (parse_iso(ended_at) - parse_iso(started_at)).total_seconds()
    return max(0, int(seconds))


def _history_row(row: sqlite3.Row) -> HistoryRow:
    """A `runs` row as the contract's HistoryRow. Counters for kind run only, coalesced to 0 for
    a run whose counters haven't been written yet."""
    counters = None
    if row["kind"] == "run":
        counters = Counters(
            recorded=row["recorded"] or 0,
            skipped_duplicate=row["skipped_duplicate"] or 0,
            skipped_other=row["skipped_other"] or 0,
            failed=row["failed"] or 0,
            bytes_added=row["bytes_added"] or 0,
        )
    window = None
    if row["window_start"] is not None and row["window_end"] is not None:
        window = HistoryRowWindow(start=row["window_start"], end=row["window_end"])
    return HistoryRow(
        id=row["id"],
        kind=row["kind"],
        trigger=row["trigger"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        duration_s=_duration_s(row["started_at"], row["ended_at"]),
        outcome=row["outcome"],
        counters=counters,
        reason=row["reason"],
        window=window,
    )


def _run_item(order: int, row: sqlite3.Row) -> RunItem:
    """One run_items row (joined to its item) as the contract's RunItem."""
    kind = row["item_kind"]
    path_kind: Literal["library", "albums"] = "albums" if kind == "album" else "library"
    badges = item_badges(
        row["state"],
        interrupted_count=row["interrupted_count"],
        carried_over_in=bool(row["carried_over_in"]),
        carried_over_out=bool(row["carried_over_out"]),
    )
    return RunItem(
        item_id=row["item_id"],
        kind=kind,
        name=row["item_name"],
        cover=cover_url(path_kind, row["item_id"], row["thumb_path"], row["image_id"]),
        order=order,
        state=row["state"],
        badges=badges,
        counts=RunItemCounts(
            recorded=row["recorded"], skipped=row["skipped"], failed=row["failed"]
        ),
        bytes=row["bytes"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        reason=row["reason"],
        can_retry=row["failed"] > 0 and row["item_removed_at"] is None,
    )


def _track_result(row: sqlite3.Row) -> TrackResult:
    """One track_results row (joined to its file and its track) as the contract's TrackResult."""
    artists = [row["artist"]]
    if row["track_artists"] is not None:
        artists = json.loads(row["track_artists"])
    return TrackResult(
        position=None if row["position"] is None else row["position"] + 1,
        track_id=row["track_id"],
        title=row["title"],
        artists=artists,
        result=row["result"],
        reason=row["reason"],
        size_bytes=row["size_bytes"],
        path=row["path"],
        take_id=row["take_id"],
        at=row["finished_at"] or row["started_at"],
    )
