"""Which items a run covers, and in what order (web-ui.md § Schedule › Run order).

Owner: **engine-run**. `order_queue` is a pure function over plain rows, so the order rules are
plain unit tests; `load_candidates` reads those rows.

- **What's due** (Run now, a scheduled run): every tracked playlist (owned, collaborative,
  followed, linked; Liked Songs) and every Queued or Partial album (albums.py's statuses), not
  removed and not unavailable (the run's own catalog refresh clears `unavailable_at` once a
  playlist answers again). With createRun's `items`: just those, whatever their tracking.
- **Order:** the settings' `run_order` (default carried_over, liked, playlists, albums). Carried
  over: the items with carried_over_out 1 in the last run of kind run that ended window_ended,
  unless a later run already ran them. Inside a group the order is fixed: playlists most
  recently changed first (items.changed_at, NULLs last), albums oldest added first
  (items.added_at). Carried-over items keep the other groups' order among themselves.
- **Forced items** go right after the current item, in the order given; an item already waiting
  moves there instead of being added twice (run.py, `_force_items`).
- **Interrupted** items go to the end, once (attempt 2) (run.py, `_apply_report`).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from spotivault.services import Services

type RunOrderGroup = Literal["carried_over", "liked", "playlists", "albums"]
DEFAULT_RUN_ORDER: tuple[RunOrderGroup, ...] = ("carried_over", "liked", "playlists", "albums")

# The album statuses (catalog/albums.py) a run records.
DUE_ALBUM_STATUSES = frozenset({"queued", "partial"})


@dataclass(frozen=True, slots=True)
class Candidate:
    """An item that may go in a run's queue."""

    item_id: str
    kind: Literal["owned", "liked", "followed", "linked", "album"]
    changed_at: str | None  # items.changed_at
    added_at: str  # items.added_at
    carried_over: bool  # cut off by the last window's end


def run_order_groups(value: Any) -> tuple[RunOrderGroup, ...]:
    """The stored `run_order` setting as a full list of the four groups. Unknown names are
    dropped and missing groups are added in the default order, so a damaged setting can't lose
    a group of items."""
    groups: list[RunOrderGroup] = []
    if isinstance(value, list):
        for name in value:
            if name in DEFAULT_RUN_ORDER and name not in groups:
                groups.append(name)
    for name in DEFAULT_RUN_ORDER:
        if name not in groups:
            groups.append(name)
    return tuple(groups)


def _group(candidate: Candidate) -> RunOrderGroup:
    """The group an item belongs to, leaving carried-over aside."""
    if candidate.kind == "liked":
        return "liked"
    if candidate.kind == "album":
        return "albums"
    return "playlists"


def _sorted_group(items: list[Candidate], group: RunOrderGroup) -> list[Candidate]:
    """One group's fixed order: albums oldest added first; playlists most recently changed
    first, then the ones never changed. The id breaks ties, so the order never depends on how
    the rows came back."""
    if group == "albums":
        return sorted(items, key=lambda c: (c.added_at, c.item_id))
    by_id = sorted(items, key=lambda c: c.item_id)
    changed = [c for c in by_id if c.changed_at is not None]
    never = [c for c in by_id if c.changed_at is None]
    # A stable sort keeps the id order among equal times. ISO times compare as text.
    changed.sort(key=lambda c: c.changed_at or "", reverse=True)
    return changed + never


def _by_groups(items: list[Candidate], groups: Sequence[RunOrderGroup]) -> list[Candidate]:
    """Items of several groups: each group in `groups`' order, each in its fixed order."""
    ordered: list[Candidate] = []
    for group in groups:
        if group != "carried_over":
            ordered += _sorted_group([c for c in items if _group(c) == group], group)
    return ordered


def order_queue(
    candidates: Sequence[Candidate], run_order: Sequence[RunOrderGroup]
) -> list[Candidate]:
    """The candidates in run order (module docstring). Each item appears once."""
    groups = run_order_groups(list(run_order))
    unique: dict[str, Candidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.item_id, candidate)
    carried = [c for c in unique.values() if c.carried_over]
    others = [c for c in unique.values() if not c.carried_over]
    ordered: list[Candidate] = []
    for group in groups:
        if group == "carried_over":
            ordered += _by_groups(carried, groups)  # among themselves, the other groups' order
        else:
            ordered += _sorted_group([c for c in others if _group(c) == group], group)
    return ordered


# --- Reading the candidates --------------------------------------------------------------------

_ITEM_COLUMNS = "id, kind, changed_at, added_at"

# Tracked playlists and Liked Songs that a run covers.
_DUE_PLAYLISTS = (
    f"SELECT {_ITEM_COLUMNS} FROM items WHERE kind IN ('owned', 'liked', 'followed', 'linked') "
    "AND tracked = 1 AND removed_at IS NULL AND unavailable_at IS NULL"
)

# The items cut off by the end of the last window, unless a later run already ran them.
_CARRIED_OVER = (
    "SELECT ri.item_id FROM run_items ri "
    "WHERE ri.carried_over_out = 1 AND ri.run_id = ("
    "  SELECT id FROM runs WHERE kind = 'run' AND state = 'ended' AND outcome = 'window_ended' "
    "  ORDER BY started_at DESC, id DESC LIMIT 1) "
    "AND NOT EXISTS (SELECT 1 FROM run_items later WHERE later.item_id = ri.item_id "
    "  AND later.run_id > ri.run_id AND later.ran_order IS NOT NULL)"
)


async def carried_over_ids(services: "Services") -> frozenset[str]:
    """The items the last window's end cut off, still waiting for their turn."""
    rows = await services.store.fetchall(_CARRIED_OVER)
    return frozenset(row["item_id"] for row in rows)


async def load_candidates(
    services: "Services", item_ids: Sequence[str] | None = None
) -> list[Candidate]:
    """The items a run covers: everything due (`item_ids` None), or just those items (they must
    exist and not be removed: createRun checked). Not ordered yet."""
    store = services.store
    carried = await carried_over_ids(services)
    if item_ids is not None:
        rows = await store.fetchall(
            f"SELECT {_ITEM_COLUMNS} FROM items WHERE removed_at IS NULL "
            "AND id IN (SELECT value FROM json_each(?))",
            (_json_list(item_ids),),
        )
    else:
        rows = list(await store.fetchall(_DUE_PLAYLISTS))
        albums = await services.albums.list_albums()
        due_albums = [album.id for album in albums.items if album.status in DUE_ALBUM_STATUSES]
        if due_albums:
            rows += await store.fetchall(
                f"SELECT {_ITEM_COLUMNS} FROM items WHERE kind = 'album' "
                "AND id IN (SELECT value FROM json_each(?))",
                (_json_list(due_albums),),
            )
    return [
        Candidate(
            item_id=row["id"],
            kind=row["kind"],
            changed_at=row["changed_at"],
            added_at=row["added_at"],
            carried_over=row["id"] in carried,
        )
        for row in rows
    ]


def _json_list(values: Sequence[str]) -> str:
    return json.dumps(list(values))
