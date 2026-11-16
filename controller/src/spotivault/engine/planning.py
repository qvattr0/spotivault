"""Planning one item: what to play, and whether to play at all (design.md § Run flow step 1).

Owner: **engine-item**. Only engine/item.py calls this module.

- **missing_only** (item access: albums, owned and collaborative playlists, Liked Songs): the
  stored track list (`item_tracks` joined to `tracks`, Web API order) without unplayable entries,
  then the ones whose `tracks.spytify_key` isn't in `services.matching.index()`. Nothing missing:
  up to date (`nothing_missing`), and no recorder starts. `offset_uri` for a jump is `tracks.uri`.
- **whole** (no item access: followed and linked playlists): D13 via
  `services.matching.d13_up_to_date`, unless `job.snapshot_unread` (this run's refresh couldn't
  read its snapshot_id, so the stored one may be stale).
- **Unavailable:** the item was removed from the Library, or the run's catalog refresh found it
  gone (`items.unavailable_at`, set by catalog/refresh.py). An album whose every entry is
  unplayable in the account's market is unavailable too (`not_offered`, set here).
- **No track list this run can trust** (item access, but `catalog_fetched_at` is NULL: the refresh
  failed for it; or the item isn't tracked: the run's refresh doesn't fetch an untracked item's
  list, so the stored one may be from long ago): an empty or old list would look like "nothing
  missing", so the item plays whole instead, the cautious answer. D13 never applies to it (only
  playlists without item access get it). createRun with `items` runs untracked items.
- Liked Songs plays as `spotify:user:<user id>:collection` (Q9, S0 row 17); the run engine puts
  that in `job.context_uri`.

No Web API call happens here: the run's catalog refresh already stored everything.
"""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from spotivault.engine.types import ItemJob, PlayMode

if TYPE_CHECKING:
    from spotivault.services import Services

type UpToDateBy = Literal["nothing_missing", "d13_unchanged"]
type UnavailableReason = Literal["deleted", "private", "unfollowed", "not_offered", "removed"]

# A whole item has no planned length. The item time limit (types.Timeouts) needs one, so these
# stand in (an open point, reported): the last full pass's length, else this per track, else 6 h.
WHOLE_PER_TRACK_MS = 5 * 60 * 1000
WHOLE_FALLBACK_MS = 6 * 60 * 60 * 1000


@dataclass(frozen=True, slots=True)
class PlannedTrack:
    """One playable track of the item, as stored."""

    position: int  # item_tracks.position (0-based, unplayable entries counted)
    track_id: str
    uri: str  # what offset_uri takes
    title: str
    artists: tuple[str, ...]
    album: str | None
    duration_ms: int
    key: str  # tracks.spytify_key


@dataclass(frozen=True, slots=True)
class ItemPlan:
    """What planning decided."""

    mode: PlayMode
    tracks: tuple[PlannedTrack, ...]  # every playable track, Web API order (missing_only)
    missing: tuple[PlannedTrack, ...]  # the ones to record, in order (missing_only)
    up_to_date_by: UpToDateBy | None = None
    unavailable: bool = False
    unavailable_reason: UnavailableReason | None = None
    item_access: bool = True  # False: a playlist without item access (D13 applies to it)
    whole_estimate_ms: int | None = None  # whole items: the stand-in length for the time limit

    @property
    def planned_ms(self) -> int | None:
        return sum(t.duration_ms for t in self.missing) if self.mode == "missing_only" else None

    @property
    def planned(self) -> int | None:
        """How many tracks are planned (QueueItem.planned); None for a whole item."""
        return len(self.missing) if self.mode == "missing_only" else None

    @property
    def length_ms(self) -> int:
        """The length the item time limit is based on: the planned tracks, or the stand-in."""
        if self.mode == "missing_only":
            return self.planned_ms or 0
        return self.whole_estimate_ms or WHOLE_FALLBACK_MS


async def plan_item(services: "Services", job: ItemJob) -> ItemPlan:
    """The item's plan, from the store and the matching index (no Web API call)."""
    store = services.store
    row = await store.fetchone(
        "SELECT kind, item_access, tracked, removed_at, unavailable_at, unavailable_reason, "
        "catalog_fetched_at, total FROM items WHERE id = ?",
        (job.item_id,),
    )
    if row is None or row["removed_at"] is not None:
        return ItemPlan(
            mode="missing_only",
            tracks=(),
            missing=(),
            unavailable=True,
            unavailable_reason="removed",
        )
    item_access = row["item_access"] == 1
    if row["unavailable_at"] is not None:
        return ItemPlan(
            mode="missing_only" if item_access else "whole",
            tracks=(),
            missing=(),
            unavailable=True,
            unavailable_reason=row["unavailable_reason"],
            item_access=item_access,
        )

    if not item_access:
        # D13: skipped while its snapshot_id is the last clean full pass's and every track seen
        # then is still recorded. A snapshot this run's refresh couldn't read may be stale.
        if not job.snapshot_unread and await services.matching.d13_up_to_date(job.item_id):
            return ItemPlan(
                mode="whole",
                tracks=(),
                missing=(),
                up_to_date_by="d13_unchanged",
                item_access=False,
            )
        estimate = await _whole_estimate_ms(services, job.item_id, row["total"])
        return ItemPlan(
            mode="whole", tracks=(), missing=(), item_access=False, whole_estimate_ms=estimate
        )

    if row["catalog_fetched_at"] is None or not row["tracked"]:
        # Item access, but no stored list, or one the run's refresh didn't fetch (untracked):
        # play it whole rather than plan from it.
        estimate = await _whole_estimate_ms(services, job.item_id, row["total"])
        return ItemPlan(mode="whole", tracks=(), missing=(), whole_estimate_ms=estimate)

    entries = await store.fetchall(
        "SELECT it.position, it.track_id, it.playable, it.unplayable_reason, t.uri, t.name, "
        "t.artists, t.album_name, t.duration_ms, t.spytify_key "
        "FROM item_tracks it LEFT JOIN tracks t ON t.id = it.track_id "
        "WHERE it.item_id = ? ORDER BY it.position",
        (job.item_id,),
    )
    tracks = tuple(
        PlannedTrack(
            position=entry["position"],
            track_id=entry["track_id"],
            uri=entry["uri"],
            title=entry["name"],
            artists=tuple(json.loads(entry["artists"])),
            album=entry["album_name"],
            duration_ms=entry["duration_ms"],
            key=entry["spytify_key"],
        )
        for entry in entries
        if entry["playable"] == 1
    )
    index = await services.matching.index()
    missing = tuple(track for track in tracks if not index.has(track.key))
    if missing:
        return ItemPlan(mode="missing_only", tracks=tracks, missing=missing)

    not_offered = any(entry["unplayable_reason"] == "not_playable" for entry in entries)
    if row["kind"] == "album" and not tracks and not_offered:
        # Nothing on the album plays in the account's market (is_playable false everywhere).
        return ItemPlan(
            mode="missing_only",
            tracks=(),
            missing=(),
            unavailable=True,
            unavailable_reason="not_offered",
        )
    return ItemPlan(mode="missing_only", tracks=tracks, missing=(), up_to_date_by="nothing_missing")


async def _whole_estimate_ms(services: "Services", item_id: str, total: int | None) -> int:
    """The stand-in length of a whole item: the summed lengths of its last full pass
    (observed_tracks), else items.total × 5 min, else 6 h."""
    observed = await services.store.fetchone(
        "SELECT COUNT(*) AS n, SUM(coalesce(length_ms, 0)) AS ms FROM observed_tracks "
        "WHERE item_id = ?",
        (item_id,),
    )
    if observed is not None and observed["n"] and observed["ms"]:
        return int(observed["ms"])
    if total:
        return total * WHOLE_PER_TRACK_MS
    return WHOLE_FALLBACK_MS
