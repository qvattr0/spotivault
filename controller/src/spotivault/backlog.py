"""The backlog estimate: how long the rest of the backup takes (design.md § Backlog estimate).

Owner: matching-backlog. Built by services.py as `services.backlog`. Specs: design.md § Backlog
estimate (with D13), web-ui.md wizard step 9 and the Dashboard's Full backup card, openapi.yaml
`Backlog` and getBacklog, events.md `backlog`, contracts/vectors/backlog.json (every case must
pass through `estimate`).

Frozen for other modules and S6: `update()`.

**`estimate(...)`** is pure: the vectors' rules, as generate.py's `backlog_expected` encodes them.
- Items counted: albums on the Albums page, and tracked playlists (Liked Songs included), except
  Unavailable ones.
- An item with item access counts its tracks that have an id, aren't local and are playable;
  each track id once, however many items it's in.
- recorded: the track ids in `recorded_track_ids`.
- seconds: milliseconds summed first, then rounded half up. `seconds_left` adds 35 s for each
  item with at least one unrecorded track (`items_to_record`).
- `unknown_items`: counted items without item access that aren't Up to date by D13.
- `finish_at`: walk `window_instances` from now (a window in progress counts from now) until
  `seconds_left` is used up, in the container's TZ (RFC 3339 with its offset). Null with Manual
  only or when nothing is left. A continuous grid: now + seconds_left.
- `as_of`: now (UTC).

**Where its inputs come from** (`BacklogService`): the `items` rows (`removed_at` NULL), their
`item_tracks` joined to `tracks.duration_ms`, `services.matching.recorded_track_ids()` (the
tracks whose key is in Spytify's index, so the estimate agrees with what a run would record:
History's own records are all in that index too), `services.matching.d13_up_to_date()` for items
without item access, `windows.load_hours()`, `config.zone` and `services.clock.now()`.

**The service:**
- `update()` computes it now and keeps it as the last estimate; it publishes `backlog` when a
  figure other than `as_of` changed. Called after each catalog refresh (catalog-library), after
  adding albums (albums-covers) and after each run item (S6).
- `current()` is GET /api/backlog: the last estimate (computing one if there's none yet), and a
  `services.catalog.request_refresh("page_open")`, which the catalog throttles to once every 15
  minutes and refuses during a run. A `backlog` event follows if that refresh changes it.
- `snapshot()` is the hello's `backlog` key: the last estimate, or None before the first. It
  never computes and never starts a refresh.

Registered in the constructor: the hello's `backlog` (`snapshot`), and a start-up hook that makes
the first estimate (a failure there is logged, so start-up never fails on it).
"""

import asyncio
import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from spotivault.api.models import Backlog
from spotivault.windows import Hours, hours_per_week, load_hours, window_instances

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

ITEM_OVERHEAD_S = 35  # a few seconds to start, and the 25–30 s Finishing tail
WINDOW_HORIZON_DAYS = 21  # how far window_instances looks by default; finish dates go further


@dataclass(frozen=True, slots=True)
class BacklogTrack:
    id: str | None
    duration_ms: int
    playable: bool
    is_local: bool


@dataclass(frozen=True, slots=True)
class BacklogItem:
    """One item, as backlog.json's `input.items` describes it."""

    id: str
    kind: Literal["owned", "liked", "followed", "linked", "album"]
    tracked: bool
    item_access: bool
    unavailable: bool
    tracks: Sequence[BacklogTrack] | None  # None without a track list
    d13_up_to_date: bool  # for items without item access


def estimate(
    items: Sequence[BacklogItem],
    recorded_track_ids: Collection[str],
    hours: Hours,
    tz: ZoneInfo,
    now: datetime,
) -> Backlog:
    """The estimate (see the module docstring). Pure; checked against backlog.json."""
    recorded = set(recorded_track_ids)
    # Each track id once, however many items it's in: its duration, from its first entry.
    durations: dict[str, int] = {}
    items_to_record = 0
    unknown = 0
    for item in items:
        if item.kind != "album" and not item.tracked:
            continue
        if item.unavailable:
            continue
        if not item.item_access or item.tracks is None:
            if not item.d13_up_to_date:
                unknown += 1
            continue
        has_missing = False
        for track in item.tracks:
            if track.id is None or track.is_local or not track.playable:
                continue
            durations.setdefault(track.id, track.duration_ms)
            if track.id not in recorded:
                has_missing = True
        if has_missing:
            items_to_record += 1

    total_ms = sum(durations.values())
    recorded_ms = sum(ms for track_id, ms in durations.items() if track_id in recorded)
    seconds_left = _half_up_seconds(total_ms - recorded_ms) + ITEM_OVERHEAD_S * items_to_record
    return Backlog(
        tracks_total=len(durations),
        tracks_recorded=sum(1 for track_id in durations if track_id in recorded),
        seconds_total=_half_up_seconds(total_ms),
        seconds_recorded=_half_up_seconds(recorded_ms),
        seconds_left=seconds_left,
        items_to_record=items_to_record,
        unknown_items=unknown,
        finish_at=_finish_at(hours, tz, now, seconds_left),
        as_of=now,
    )


def _half_up_seconds(ms: int) -> int:
    """Milliseconds to whole seconds, rounding half up (1,500 ms is 2 s)."""
    return (ms + 500) // 1000


def _finish_at(hours: Hours, tz: ZoneInfo, now: datetime, seconds_left: int) -> datetime | None:
    """When the schedule has played `seconds_left` of music, in `tz`: walk the windows from now,
    each from its own start (a window in progress from now), using their real lengths. Null with
    Manual only, or when nothing is left."""
    if seconds_left == 0:
        return None
    # The default 21-day horizon would give null for a slow schedule (one hour a week, say),
    # which the contract doesn't allow (openapi.yaml Backlog.finish_at). So look as far as the
    # time left needs, plus two weeks for DST and partial windows.
    horizon_days = WINDOW_HORIZON_DAYS
    per_week = hours_per_week(hours) * 3600
    if per_week:
        weeks = seconds_left // per_week + 2
        horizon_days = max(horizon_days, weeks * 7)
    remaining = timedelta(seconds=seconds_left)
    for window in window_instances(hours, tz, now, horizon_days=horizon_days):
        begin = max(window.start, now)
        if window.end is None or remaining <= window.end - begin:
            return (begin + remaining).astimezone(tz)
        remaining -= window.end - begin
    return None


class BacklogService:
    """The last backlog estimate. See the module docstring."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        self._last: Backlog | None = None
        # One computation at a time, so an older one can't overwrite a newer answer.
        self._lock = asyncio.Lock()
        services.bus.add_snapshot("backlog", self.snapshot)
        services.add_startup("backlog", self._first_estimate)

    async def _first_estimate(self) -> None:
        """Start-up: the hello carries an estimate from the first moment. A failure is logged,
        not raised: the estimate can wait for the first refresh, and start-up must not fail."""
        try:
            await self.update()
        except Exception:
            log.exception("the first backlog estimate failed")

    async def update(self) -> Backlog:
        """Computes the estimate now, keeps it, publishes `backlog` if it changed."""
        async with self._lock:
            backlog = await self._compute()
            previous = self._last
            self._last = backlog
        # Only the figures count: as_of changes on every computation.
        if previous is None or _figures(previous) != _figures(backlog):
            self.services.bus.publish("backlog", backlog)
        return backlog

    async def current(self) -> Backlog:
        """GET /api/backlog (see the module docstring)."""
        last = self._last
        if last is None:
            last = await self.update()
        # The catalog throttles this (once every 15 minutes, never in a run). Its result, if it
        # changes the figures, comes later as a `backlog` event.
        self.services.catalog.request_refresh("page_open")
        return last

    async def snapshot(self) -> Backlog | None:
        """The hello's `backlog`: the last estimate, or None. Never raises."""
        return self._last

    async def _compute(self) -> Backlog:
        """Reads the inputs and runs `estimate`. Times are whole milliseconds, as the database's."""
        services = self.services
        now = services.clock.now()
        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
        items = await self._items()
        recorded = await services.matching.recorded_track_ids()
        hours = await load_hours(services.store)
        return estimate(items, recorded, hours, services.config.zone, now)

    async def _items(self) -> list[BacklogItem]:
        """Every item that isn't removed, with its track list (None without one). Two queries:
        the items, and every track list joined to its durations."""
        store = self.services.store
        rows = await store.fetchall(
            "SELECT id, kind, tracked, item_access, unavailable_at, catalog_fetched_at "
            "FROM items WHERE removed_at IS NULL ORDER BY id"
        )
        entries = await store.fetchall(
            "SELECT it.item_id, it.track_id, it.playable, it.unplayable_reason, t.duration_ms "
            "FROM item_tracks it "
            "JOIN items i ON i.id = it.item_id "
            "LEFT JOIN tracks t ON t.id = it.track_id "
            "WHERE i.removed_at IS NULL ORDER BY it.item_id, it.position"
        )
        lists: dict[str, list[BacklogTrack]] = {}
        for entry in entries:
            track = BacklogTrack(
                id=entry["track_id"],
                duration_ms=entry["duration_ms"] or 0,
                playable=entry["playable"] == 1,
                is_local=entry["unplayable_reason"] == "local",
            )
            lists.setdefault(entry["item_id"], []).append(track)
        items: list[BacklogItem] = []
        for row in rows:
            # A track list exists when the item has item access and it was fetched (an empty
            # playlist has a list with no entries).
            has_list = bool(row["item_access"]) and row["catalog_fetched_at"] is not None
            # D13 only matters for items without a list: the others are counted by their tracks.
            d13 = False if has_list else await self.services.matching.d13_up_to_date(row["id"])
            items.append(
                BacklogItem(
                    id=row["id"],
                    kind=row["kind"],
                    tracked=bool(row["tracked"]),
                    item_access=bool(row["item_access"]),
                    unavailable=row["unavailable_at"] is not None,
                    tracks=lists.get(row["id"], []) if has_list else None,
                    d13_up_to_date=d13,
                )
            )
        return items


def _figures(backlog: Backlog) -> dict[str, object]:
    """The estimate without `as_of`: what a `backlog` event is published for."""
    return backlog.model_dump(exclude={"as_of"})
