"""Spytify's track key and its duplicate index: what's recorded, as Spytify itself decides it.

Spytify skips a track as a duplicate when its key is in `<music>/.spytify/recorded.jsonl` and that
entry's file still exists (internal/core/records.go). The controller uses the same rule to know
what's recorded and what's missing (design.md § Run flow step 1): the Library's and Albums' counts,
the detail views' track states, the backlog, D13, and S6's planning.

**The key** (frozen, written in S5's foundation, checked against contracts/vectors/track-keys.json):
the first artist and the title, each trimmed with Go's `strings.TrimSpace` and lowercased with
Go's `strings.ToLower`, joined by U+001F. Python's own `lower()` and `strip()` differ from Go's on a
few characters, so these are probe.py's `go_lower` and `go_trim`, exactly. They match Go on every
code point under Python 3.12 (design.md § Stack): don't "simplify" them.

**The index** (matching-backlog): `read_recorded_index` reads the file as probe.py's
`recorded_index` does, later lines winning, keeping an entry only while its file exists. It's
blocking file work, so `MatchingService.index()` runs it with `asyncio.to_thread`, and caches it.

Owner: matching-backlog, except the four key functions at the top, which are frozen.
"""

import asyncio
import json
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from spotivault.ports import Track

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

# --- The key (frozen) ---------------------------------------------------------------------------

# Go's unicode.IsSpace: \t \n \v \f \r, space, U+0085, U+00A0, U+1680, U+2000–U+200A, U+2028,
# U+2029, U+202F, U+205F, U+3000. Not U+001C–U+001F, which Python's strip() also removes.
_GO_SPACE = " \t\n\v\f\r\x85\xa0                　"


def go_lower(text: str) -> str:
    """Go's strings.ToLower: per-rune simple case mapping. Python's lower() differs for U+0130
    (İ → 'i̇', two runes) and for a final Σ (→ ς); Go gives 'i' and 'σ'."""
    return "".join("i" if c == "İ" else c.lower() for c in text)


def go_trim(text: str) -> str:
    """Go's strings.TrimSpace (unicode.IsSpace). Python's strip() also strips U+001C–U+001F."""
    return text.strip(_GO_SPACE)


def track_key(artist: str, title: str) -> str:
    """Spytify's trackKey: first artist + U+001F + title, each trimmed and lowercased the Go
    way. Spotify's MPRIS `xesam:artist` holds only the first artist, so a Web API track's key is
    `artists[0]` and `name` (web_track_key)."""
    return go_lower(go_trim(artist)) + "\x1f" + go_lower(go_trim(title))


def web_track_key(track: Track) -> str:
    """The key of a track from the Web API: its first artist ('' when it has none) and its name."""
    return track_key(track.artists[0] if track.artists else "", track.name)


# --- The index (matching-backlog) ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecordedIndex:
    """Spytify's index as read at `read_at`: key → the file's path as Spytify wrote it (absolute,
    under the music folder), only for entries whose file existed then."""

    paths: Mapping[str, str]
    read_at: datetime

    def has(self, key: str) -> bool:
        """The track with this key is recorded: Spytify would skip it as a duplicate."""
        return key in self.paths

    def path(self, key: str) -> str | None:
        return self.paths.get(key)


@dataclass(frozen=True, slots=True)
class ItemCounts:
    """One item's playable tracks against the index. For the Library's "84 / 120 recorded", the
    Albums' "11 / 11", the `n new` pill and the statuses."""

    total: int  # playable entries (item_tracks.playable = 1)
    recorded: int  # of those, the ones whose key is in the index
    new: int  # unrecorded ones added after items.last_backup_at; every unrecorded one if never


def read_recorded_index(index_file: Path) -> dict[str, str]:
    """Reads Spytify's `recorded.jsonl` into key → path: one JSON object per line with `Key` and
    `Path`, later lines winning, unreadable lines skipped, and only entries whose file exists
    (`os.path.exists`, as Spytify's recordIndex.lookup). A missing file is an empty index.

    Blocking: call it through `asyncio.to_thread`. Exactly probe.py's `recorded_index`.
    """
    entries: dict[str, str] = {}
    try:
        # errors="replace": a line with bad bytes is still tried. A key with bad bytes matches no
        # track, so it's harmless; the rest of the file still counts.
        with index_file.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                entry = _parse_index_line(line)
                if entry is not None:
                    entries[entry[0]] = entry[1]
    except FileNotFoundError:
        return {}  # no index yet: nothing is recorded
    return {key: path for key, path in entries.items() if os.path.exists(path)}


def _parse_index_line(line: str) -> tuple[str, str] | None:
    """(Key, Path) of one index line, or None for a line to skip: not JSON, not an object, or
    without a non-empty string Key and Path."""
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict):
        return None
    key = entry.get("Key")
    path = entry.get("Path")
    if not isinstance(key, str) or not isinstance(path, str) or not key or not path:
        return None
    return key, path


class MatchingService:
    """What's recorded. Built by services.py as `services.matching`. Owner: matching-backlog.

    Frozen interface (other builders and S6 call these): `index`, `invalidate`, `item_counts`,
    `recorded_track_ids`, `observed_all_in_index`, `d13_up_to_date`.
    """

    def __init__(self, services: "Services") -> None:
        self.services = services
        self.index_file = services.config.spytify_index
        # `_generation` goes up on each invalidate(). A read started under an older generation
        # is never cached, and a new caller doesn't wait on it.
        self._generation = 0
        self._cached: tuple[int, float, RecordedIndex] | None = None  # generation, monotonic, index
        self._read: asyncio.Task[RecordedIndex] | None = None
        self._read_generation = -1

    async def index(self, *, max_age_s: float = 2.0) -> RecordedIndex:
        """The index, read with `asyncio.to_thread(read_recorded_index, ...)`. A read younger
        than `max_age_s` (services.clock) is reused, unless `invalidate()` was called since; a
        list view and its counts then cost one read. Concurrent callers share one read."""
        cached = self._cached
        if (
            cached is not None
            and cached[0] == self._generation
            and self.services.clock.monotonic() - cached[1] < max_age_s
        ):
            return cached[2]
        read = self._read
        if read is None or read.done() or self._read_generation != self._generation:
            read = asyncio.create_task(self._read_file(self._generation))
            self._read = read
            self._read_generation = self._generation
        # shield: one caller's cancellation doesn't cancel the read the others are waiting for.
        return await asyncio.shield(read)

    async def _read_file(self, generation: int) -> RecordedIndex:
        """One read of the file on a worker thread, cached if no invalidate() came meanwhile."""
        paths = await asyncio.to_thread(read_recorded_index, self.index_file)
        index = RecordedIndex(paths=paths, read_at=self.services.clock.now())
        if generation == self._generation:
            self._cached = (generation, self.services.clock.monotonic(), index)
        return index

    def invalidate(self) -> None:
        """Forgets the cached read. S6 calls it after each item, when new files are written."""
        self._generation += 1
        self._cached = None

    async def item_counts(self, item_ids: Sequence[str] | None = None) -> dict[str, ItemCounts]:
        """ItemCounts for these items (every item when None), from `item_tracks` joined to
        `tracks.spytify_key` and one `index()` read. An item without a track list (no item
        access, or never fetched) is left out of the answer."""
        index = await self.index()
        # Left join: an item with a fetched list and no entries still gets (0, 0, 0). Items
        # without a list (no item access, or never fetched) don't appear at all.
        sql = (
            "SELECT i.id AS item_id, it.playable, it.added_at, i.last_backup_at, t.spytify_key "
            "FROM items i "
            "LEFT JOIN item_tracks it ON it.item_id = i.id "
            "LEFT JOIN tracks t ON t.id = it.track_id "
            "WHERE i.removed_at IS NULL AND i.item_access = 1 AND i.catalog_fetched_at IS NOT NULL"
        )
        params: tuple[str, ...] = ()
        if item_ids is not None:
            sql += " AND i.id IN (SELECT value FROM json_each(?))"
            params = (json.dumps(list(item_ids)),)
        rows = await self.services.store.fetchall(sql, params)
        # Per item: [playable entries, recorded among them, new among them].
        counts: dict[str, list[int]] = {}
        for row in rows:
            slot = counts.setdefault(row["item_id"], [0, 0, 0])
            if row["playable"] != 1:
                continue  # NULL (no entry) or an entry that can't be recorded
            slot[0] += 1
            if index.has(row["spytify_key"]):
                slot[1] += 1
            elif row["last_backup_at"] is None or (
                # Added after the last backup finished; ISO times with the same format compare.
                row["added_at"] is not None and row["added_at"] > row["last_backup_at"]
            ):
                slot[2] += 1
        return {
            item_id: ItemCounts(total=total, recorded=recorded, new=new)
            for item_id, (total, recorded, new) in counts.items()
        }

    async def recorded_track_ids(self) -> frozenset[str]:
        """The ids in `tracks` whose key is in the index: the backlog's "recorded" set."""
        index = await self.index()
        rows = await self.services.store.fetchall("SELECT id, spytify_key FROM tracks")
        return frozenset(row["id"] for row in rows if index.has(row["spytify_key"]))

    async def observed_all_in_index(self, item_id: str) -> bool:
        """D13: every `observed_tracks` row of the item has its key in the index. False when the
        item has no observed tracks (no clean full pass yet)."""
        rows = await self.services.store.fetchall(
            "SELECT spytify_key FROM observed_tracks WHERE item_id = ?", (item_id,)
        )
        if not rows:
            return False
        index = await self.index()
        return all(index.has(row["spytify_key"]) for row in rows)

    async def d13_up_to_date(self, item_id: str) -> bool:
        """D13 (design.md § Run flow step 1): a playlist without item access is Up to date when
        `items.snapshot_id` equals `last_full_pass_snapshot` (not NULL) and every observed track
        is still in the index. A deleted file forces a full pass. S6's planning and the backlog
        both use it."""
        row = await self.services.store.fetchone(
            "SELECT snapshot_id, last_full_pass_snapshot FROM items WHERE id = ?", (item_id,)
        )
        if row is None or row["last_full_pass_snapshot"] is None:
            return False  # no clean full pass yet
        if row["snapshot_id"] != row["last_full_pass_snapshot"]:
            return False  # the playlist changed since that pass
        return await self.observed_all_in_index(item_id)
