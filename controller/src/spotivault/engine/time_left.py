"""A run's own time left: the run header's "about 9 min left in this run" (RunSummary.time_left).

Owner: **engine-run**. run.py keeps the figure and sends it; this module works it out. Specs:
openapi.yaml `RunTimeLeft` (the rules), web-ui.md § Run header, and
contracts/vectors/run-time-left.json (every case must pass through `work_out`). The web mock does
the same sum (web/mock/time-left.ts).

**What's summed,** all from what's stored, with no Web API request:
- **The current item** (`ItemLeft`, from the item engine once it's planned): the rest of the
  planned take recording now, and its planned tracks that haven't started. Before its plan is
  known, its missing tracks as stored (`item_estimates`), with take_ms 0.
- **Each waiting item** (Up next, and interrupted ones that will retry; removed ones aren't
  waiting): its missing tracks as stored, plus the backlog estimate's 35 s for each item with a
  track to record (backlog.ITEM_OVERHEAD_S: a few seconds to start, and the Finishing tail).
- **Each key once:** a track two items share is recorded once (Spytify skips it as a duplicate
  after), so it counts the first time it comes, in queue order. The backlog counts each track
  once too.
- **Recorded in this run:** a key this run has already recorded (the current item's takes so
  far, `ItemLeft.done_keys`, and the items that ended) doesn't count again, though a waiting
  item's list, read before, still has it.
- **Unknown:** an item that plays whole has no planned length: it's counted in `unknown_items`,
  not summed.
- **Stops:** after this track, only the take; Stop now, nothing.
- **The window:** a scheduled or start-up run stops at its window's end (after the track playing
  then), so without a stop the sum is capped at the time left in the window, and nothing of
  unknown length is left past it (`unknown_items` 0).

**`item_estimates`** gives what planning.py would plan for each item if it ran now, by the same
rules, in two queries for all of them (as the backlog reads its lists). Walking the lists touches
every track of the queue (most of the library for Run now), so that part runs on a worker thread,
as the backlog's does (design.md § Stack):
- removed, or unavailable (`items.unavailable_at`): nothing to record, `()`;
- no item access: `()` when Up to date by D13 (unless this run's refresh couldn't read its
  snapshot_id), else None: it plays whole;
- item access, but no track list this run can trust (`catalog_fetched_at` NULL, or not tracked):
  None, it plays whole;
- else its playable entries whose key isn't in Spytify's index, in list order.
"""

import asyncio
import json
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spotivault.backlog import ITEM_OVERHEAD_S
from spotivault.engine.types import ItemLeft, MissingTrack, StopMode

if TYPE_CHECKING:
    from spotivault.services import Services

ITEM_OVERHEAD_MS = ITEM_OVERHEAD_S * 1000

# An item's missing tracks, in the order they'd play; None: it plays whole, its length unknown.
type Missing = tuple[MissingTrack, ...] | None


@dataclass(frozen=True, slots=True)
class TimeLeft:
    """The sum: milliseconds of the items whose length is known, and how many items aren't."""

    ms: int
    unknown_items: int

    @property
    def seconds(self) -> int:
        """Whole seconds, rounding half up (1,500 ms is 2 s), as the backlog rounds."""
        return (self.ms + 500) // 1000


def work_out(
    current: ItemLeft | None,
    waiting: Sequence[Missing],
    *,
    stop_mode: StopMode | None,
    recorded: Collection[str] = (),
    window_ms: int | None = None,
) -> TimeLeft:
    """The run's time left (module docstring). `current` is None with no current item;
    `waiting` is every waiting item in queue order; `recorded`, the keys this run has recorded
    so far; `window_ms`, what's left of the run's window (None: no window). Pure; checked
    against run-time-left.json."""
    if stop_mode == "now":
        return TimeLeft(ms=0, unknown_items=0)
    ms = 0
    unknown = 0
    seen: set[str] = set(recorded)
    if current is not None:
        ms += current.take_ms
        if current.take_key is not None:
            seen.add(current.take_key)
    if stop_mode is not None:  # after this track: nothing else plays
        return TimeLeft(ms=ms, unknown_items=0)
    if current is not None:
        if current.tracks is None:
            unknown += 1
        else:
            ms += _new_ms(current.tracks, seen)[0]
    for tracks in waiting:
        if tracks is None:
            unknown += 1
            continue
        item_ms, any_new = _new_ms(tracks, seen)
        if any_new:
            ms += item_ms + ITEM_OVERHEAD_MS
    if window_ms is not None and ms >= window_ms:  # the run stops at the window's end
        return TimeLeft(ms=max(0, window_ms), unknown_items=0)
    return TimeLeft(ms=ms, unknown_items=unknown)


def _new_ms(tracks: Sequence[MissingTrack], seen: set[str]) -> tuple[int, bool]:
    """The tracks whose key hasn't come yet (each once): their summed length, and whether there
    was one. Adds their keys to `seen`."""
    total = 0
    any_new = False
    for track in tracks:
        if track.key in seen:
            continue
        seen.add(track.key)
        total += track.duration_ms
        any_new = True
    return total, any_new


async def item_estimates(
    services: "Services", items: Sequence[tuple[str, bool]]
) -> dict[str, Missing]:
    """Each item's missing tracks, as planning.py would plan them now (module docstring).
    `items` is (item id, snapshot_unread) pairs. An id with no `items` row is left out."""
    if not items:
        return {}
    store = services.store
    ids = json.dumps([item_id for item_id, _ in items])
    rows = await store.fetchall(
        "SELECT id, item_access, tracked, removed_at, unavailable_at, catalog_fetched_at "
        "FROM items WHERE id IN (SELECT value FROM json_each(?))",
        (ids,),
    )
    entries = await store.fetchall(
        "SELECT it.item_id, it.playable, t.duration_ms, t.spytify_key "
        "FROM item_tracks it LEFT JOIN tracks t ON t.id = it.track_id "
        "WHERE it.item_id IN (SELECT value FROM json_each(?)) "
        "ORDER BY it.item_id, it.position",
        (ids,),
    )
    index = await services.matching.index()
    # D13, as planning.py: an item without item access is skipped while unchanged since its
    # last clean full pass (unless this run's refresh couldn't read its snapshot_id).
    d13: dict[str, bool] = {}
    by_id = {row["id"]: row for row in rows}
    for item_id, snapshot_unread in items:
        row = by_id.get(item_id)
        if row is None or row["removed_at"] is not None or row["unavailable_at"] is not None:
            continue
        if row["item_access"] != 1:
            d13[item_id] = not snapshot_unread and await services.matching.d13_up_to_date(item_id)
    return await asyncio.to_thread(
        _estimates_from_rows, [item_id for item_id, _ in items], rows, entries, index.paths, d13
    )


def _estimates_from_rows(
    item_ids: Sequence[str],
    rows: Sequence[sqlite3.Row],
    entries: Sequence[sqlite3.Row],
    recorded: Mapping[str, str],
    d13: Mapping[str, bool],
) -> dict[str, Missing]:
    """`item_estimates`' answer from its two queries, the index's keys (`recorded`) and D13 for
    the items without item access. Pure; item_estimates runs it on a worker thread."""
    lists: dict[str, list[MissingTrack]] = {}
    for entry in entries:
        key = entry["spytify_key"]
        if entry["playable"] != 1 or key is None or key in recorded:
            continue
        track = MissingTrack(key=key, duration_ms=entry["duration_ms"] or 0)
        lists.setdefault(entry["item_id"], []).append(track)
    by_id = {row["id"]: row for row in rows}
    estimates: dict[str, Missing] = {}
    for item_id in item_ids:
        row = by_id.get(item_id)
        if row is None:
            continue
        if row["removed_at"] is not None or row["unavailable_at"] is not None:
            estimates[item_id] = ()  # it ends unavailable: nothing plays
        elif row["item_access"] != 1:
            estimates[item_id] = () if d13[item_id] else None  # D13: Up to date, else whole
        elif row["catalog_fetched_at"] is None or not row["tracked"]:
            estimates[item_id] = None  # no list this run can trust: it plays whole
        else:
            estimates[item_id] = tuple(lists.get(item_id, ()))
    return estimates
