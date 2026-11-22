"""The Library: playlists and Liked Songs, their states, and what the + modal offers.

Owner: catalog-library. Built by services.py as `services.library`. Specs: web-ui.md § Library
(all subsections), wizard step 7, Settings › Library; openapi.yaml tag `library` (LibraryItem,
LibrarySummary, PlaylistPreview, TrackList); events.md `library.item`.

Frozen for other modules and S6: `item()` and `publish()`.

**A LibraryItem** comes from its `items` row (kinds owned, liked, followed, linked; never album;
`removed_at` NULL), `services.matching.item_counts()` and the History tables:
- `owner`: "you" for owned and liked items, else the owner's display name (or id).
- `cover`: `covers.cover_url("library", id, thumb_path, image_id)`; always null for Liked Songs.
- `total`: the playable tracks of its stored list; without one, the total the listing gave
  (`/me/playlists`' `items.total`: a followed playlist's "32 / 35 recorded", web-ui.md § List
  view), and null for a linked playlist, whose total is unknown.
- `recorded`: from the index for an item with a track list; otherwise the distinct tracks History
  recorded for it (`track_results` → `files`, counted and not missing).
- `new`: from the index for an item with a track list, else null (unknown).
- `status`, in this order: `recording`/`queued` (in the current run: `run_items` of the run
  that hasn't ended), `unavailable`, `not_tracked`, `never_backed_up` (no `last_backup_at`),
  `partial` (the last run item for it that ran ended `partial`), `new` (`new` > 0), else
  `up_to_date`. An item without item access has no `new`: after a backup it's `up_to_date`
  ("every known track is recorded"), whatever D13 says; D13 only decides whether a run skips it.
- `progress`: set while the item is in the current run (S6 fills `run_items`), else null.
- `removable`: followed and linked items only.

**Endpoints** (api/routers/library.py calls these):
- GET /api/library/summary → `summary()`: owned_count (owned items not removed), owned_tracked,
  liked_tracked, added_count (followed + linked), tracked_count, and the auto_track_owned setting.
- GET /api/library → `list_items()`: filter, case-insensitive search on the name, sort (ties
  by name); Liked Songs first whenever it matches the filter.
- PATCH /api/library/{id} → `set_tracked()`; works on `liked` too (step 7). Tracking an item
  asks for a refresh (`services.catalog.request_refresh("item_added")`). 404 for no such item.
- DELETE /api/library/{id} → `remove()`: followed and linked only (409 `not_removable` else);
  sets `removed_at` (and untracks it), keeps files and History.
- GET /api/library/suggestions?q= → `suggestions()`: `followed_playlists` rows not in the
  Library, filtered by name or owner. No Web API request. `cover` is a CDN URL only if a refresh
  in this process saw one in the last 12 hours (kept in memory by CatalogService, never stored:
  playlist image URLs expire within a day), else null.
- POST /api/library/resolve → `resolve()`: links.parse_playlist_link, then GET /playlists/{id}
  (S0, Q10: name, owner, cover and snapshot_id; no total for a linked one). 422 `invalid_url`,
  `spotify_owned`, `not_found` (404), `private` (403). `kind` followed when it's in
  `followed_playlists`, else linked; `already_added` when it's in the Library.
- POST /api/library → `add()`: refused with 409 `already_added` before asking Spotify when it's
  in the Library; otherwise as resolve, then the item comes in tracked (`added_by` 'user'); a
  removed one comes back. Its track list is fetched now when it has item access (a refresh is
  asked for if that fails); its cover is saved now. Returns 201 with the item.
- GET /api/library/{id}/tracks → `tracks()`: TrackList in Web API order (`position` from 1); for
  an item without a track list (no item access, or not fetched yet), the tracks History
  recorded, in recording order, `position` null. Track states: unplayable; skipped_duplicate
  (the last run that played the item skipped it as a duplicate, and its key is in the index);
  recorded (key in the index; `size_bytes`, `path` relative to the music folder and
  `recorded_at` from `files` when History has the file, else the index's path); failed (from the
  last run's `track_results`); new (added after `last_backup_at`, or never backed up); missing.

**Not connected:** resolve and add leave a missing or expired connection, rate limiting and an
outage to the API's error handler, as every endpoint does: 409 `not_connected` or
`connection_expired`, 503 `rate_limited` or `spotify_unavailable`.

**Events:** `publish(id)` sends `library.item` with the item. At most one per item per second,
during a run and outside one: a later call within the second is merged into one sent at its end
by the background task `library.publish`.
"""

import asyncio
import json
import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from spotivault.api.models import (
    ItemProgress,
    ItemTrack,
    LibraryItem,
    LibrarySummary,
    PlaylistPreview,
    TrackList,
)
from spotivault.catalog.covers import cover_url
from spotivault.catalog.links import LinkError, parse_playlist_link
from spotivault.catalog.refresh import preview_image
from spotivault.clock import iso_ms, parse_iso
from spotivault.errors import ApiError, not_found
from spotivault.matching import ItemCounts, RecordedIndex
from spotivault.ports import (
    OTHER,
    NoAccess,
    NotFound,
    Playlist,
    WebApiError,
)

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

type LibraryFilter = Literal["all", "tracked", "not_tracked", "owned", "added"]
type LibrarySort = Literal["recently_backed_up", "name", "recently_added", "track_count"]

PUBLISH_INTERVAL_S = 1.0  # at most one library.item per item per second (events.md)
LIBRARY_KINDS = ("owned", "liked", "followed", "linked")

# run_items states (openapi.yaml ItemState) that make the pill `recording` or `queued`.
_RECORDING_STATES = ("planning", "preflight", "preparing", "starting", "playing", "finishing")
_QUEUED_STATES = ("up_next", "interrupted")
# The states a run item ends in once it ran (for `partial`).
_RAN_STATES = ("done", "up_to_date", "partial", "stopped", "carried_over", "failed", "unavailable")


@dataclass(slots=True)
class _Facts:
    """What the database says about some Library items, read in one go."""

    rows: list[sqlite3.Row] = field(default_factory=list)
    run_id: int | None = None  # the run that hasn't ended
    in_run: dict[str, sqlite3.Row] = field(default_factory=dict)  # item id → its run_items row
    last_outcome: dict[str, str] = field(default_factory=dict)  # item id → last state it ran to
    history: dict[str, int] = field(default_factory=dict)  # item id → distinct tracks recorded


class LibraryService:
    """The Library. See the module docstring."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        self._last_sent: dict[str, float] = {}  # item id → when library.item was last sent
        self._due: dict[str, float] = {}  # item id → when its merged library.item is due
        self._wake = asyncio.Event()
        services.add_background("library.publish", self._send_due)

    # --- Reading -------------------------------------------------------------------------------

    async def summary(self) -> LibrarySummary:
        row = await self.services.store.fetchone(
            "SELECT "
            "coalesce(SUM(kind = 'owned'), 0) AS owned_count, "
            "coalesce(SUM(kind = 'owned' AND tracked = 1), 0) AS owned_tracked, "
            "coalesce(SUM(kind = 'liked' AND tracked = 1), 0) AS liked_tracked, "
            "coalesce(SUM(kind IN ('followed', 'linked')), 0) AS added_count, "
            "coalesce(SUM(tracked = 1), 0) AS tracked_count "
            "FROM items WHERE kind <> 'album' AND removed_at IS NULL"
        )
        assert row is not None
        auto_track = await self.services.settings.get_value("auto_track_owned")
        return LibrarySummary(
            owned_count=row["owned_count"],
            owned_tracked=row["owned_tracked"],
            liked_tracked=bool(row["liked_tracked"]),
            added_count=row["added_count"],
            tracked_count=row["tracked_count"],
            auto_track_owned=bool(auto_track),
        )

    async def list_items(
        self,
        *,
        filter: LibraryFilter = "all",
        q: str | None = None,
        sort: LibrarySort = "recently_backed_up",
    ) -> list[LibraryItem]:
        pairs = await self._build(None)
        query = (q or "").strip().casefold()
        chosen = [
            (item, added_at)
            for item, added_at in pairs
            if _matches_filter(item, filter) and (not query or query in item.name.casefold())
        ]
        chosen.sort(key=lambda pair: _sort_key(pair[0], pair[1], sort))
        liked = [item for item, _ in chosen if item.kind == "liked"]
        return liked + [item for item, _ in chosen if item.kind != "liked"]

    async def item(self, item_id: str) -> LibraryItem | None:
        """One Library item, or None when there's no such item (or it's an album or removed)."""
        pairs = await self._build([item_id])
        return pairs[0][0] if pairs else None

    async def suggestions(self, q: str | None = None) -> list[PlaylistPreview]:
        rows = await self.services.store.fetchall(
            "SELECT * FROM followed_playlists WHERE id NOT IN "
            "(SELECT id FROM items WHERE removed_at IS NULL) ORDER BY listed_order"
        )
        query = (q or "").strip().casefold()
        previews = []
        for row in rows:
            owner = _owner(row["owner_name"], row["owner_id"])
            if query and query not in row["name"].casefold() and query not in owner.casefold():
                continue
            previews.append(
                PlaylistPreview(
                    id=row["id"],
                    uri=row["uri"],
                    name=row["name"],
                    owner=owner,
                    cover=self.services.catalog.preview_cover(row["id"]),
                    kind="followed",
                    item_access=bool(row["collaborative"]),
                    total=row["total"],
                    already_added=False,
                )
            )
        return previews

    async def tracks(self, item_id: str) -> TrackList:
        row = await self._row(item_id)
        if row is None:
            raise not_found()
        if row["item_access"] and row["catalog_fetched_at"] is not None:
            return await self._listed_tracks(row)
        return await self._recorded_tracks(row)

    # --- Changing ------------------------------------------------------------------------------

    async def set_tracked(self, item_id: str, tracked: bool) -> LibraryItem:
        row = await self._row(item_id)
        if row is None:
            raise not_found()
        if bool(row["tracked"]) != tracked:
            await self.services.store.execute(
                "UPDATE items SET tracked = ? WHERE id = ?", (1 if tracked else 0, item_id)
            )
            log.info("library: %s %s", item_id, "tracked" if tracked else "not tracked")
            if tracked:
                self.services.catalog.request_refresh("item_added")
            await self.publish(item_id)
            await self._update_backlog()
        item = await self.item(item_id)
        assert item is not None
        return item

    async def remove(self, item_id: str) -> None:
        row = await self._row(item_id)
        if row is None:
            raise not_found()
        if row["kind"] not in ("followed", "linked"):
            raise ApiError(
                409,
                "not_removable",
                "Your own playlists and Liked Songs can't be removed, only untracked.",
            )
        now = iso_ms(self.services.clock.now())
        await self.services.store.execute(
            "UPDATE items SET removed_at = ?, tracked = 0 WHERE id = ?", (now, item_id)
        )
        log.info("library: %s removed (its files are kept)", item_id)
        await self._update_backlog()

    async def resolve(self, url: str) -> PlaylistPreview:
        playlist_id = _parse_link(url)
        playlist = await self._read_playlist(playlist_id)
        facts = await self._link_facts(playlist)
        return PlaylistPreview(
            id=playlist.id,
            uri=playlist.uri,
            name=playlist.name,
            owner=_owner(playlist.owner_name, playlist.owner_id),
            cover=preview_image(playlist.images),
            kind="followed" if facts.followed is not None else "linked",
            item_access=facts.item_access,
            total=facts.followed["total"] if facts.followed is not None else None,
            already_added=facts.already_added,
        )

    async def add(self, url: str) -> LibraryItem:
        playlist_id = _parse_link(url)
        if await self._row(playlist_id) is not None:
            raise _already_added()
        playlist = await self._read_playlist(playlist_id)
        facts = await self._link_facts(playlist)
        if facts.already_added:
            raise _already_added()  # added while Spotify was answering
        if facts.owned:
            kind = "owned"
        elif facts.followed is not None:
            kind = "followed"
        else:
            kind = "linked"
        if facts.item_access:
            snapshot_id = None  # set with the track list, fetched below
            total = facts.followed["total"] if facts.followed is not None else playlist.total
        else:
            snapshot_id = playlist.snapshot_id  # D13
            total = facts.followed["total"] if facts.followed is not None else None
        now = iso_ms(self.services.clock.now())
        values = (
            kind,
            playlist.uri,
            playlist.name,
            playlist.owner_id,
            playlist.owner_name,
            now,
            1 if facts.item_access else 0,
            snapshot_id,
            total,
            playlist.id,
        )

        def insert(conn: sqlite3.Connection) -> bool:
            exists = conn.execute("SELECT 1 FROM items WHERE id = ?", (playlist.id,)).fetchone()
            if exists is None:
                conn.execute(
                    "INSERT INTO items (kind, uri, name, owner_id, owner_name, tracked, "
                    "added_by, added_at, item_access, snapshot_id, total, cover_source, id) "
                    "VALUES (?, ?, ?, ?, ?, 1, 'user', ?, ?, ?, ?, 'none', ?)",
                    values,
                )
                return True
            # A removed one comes back. (A row that isn't removed is an album with the same id,
            # in theory: nothing is written.)
            cur = conn.execute(
                "UPDATE items SET kind = ?, uri = ?, name = ?, owner_id = ?, "
                "owner_name = ?, tracked = 1, added_by = 'user', added_at = ?, "
                "item_access = ?, snapshot_id = ?, total = ?, removed_at = NULL, "
                "catalog_fetched_at = NULL, unavailable_at = NULL, "
                "unavailable_reason = NULL WHERE id = ? AND removed_at IS NOT NULL",
                values,
            )
            return cur.rowcount > 0

        if not await self.services.store.transaction(insert):
            raise _already_added()
        log.info("library: added %s (%s)", playlist.id, kind)
        if facts.item_access:
            await self._fetch_added(playlist)
        try:
            await self.services.covers.update(playlist.id, playlist.images)
        except Exception:
            log.warning("covers: saving %s's cover failed", playlist.id, exc_info=True)
        await self.publish(playlist.id)
        await self._update_backlog()
        item = await self.item(playlist.id)
        assert item is not None
        return item

    # --- Events --------------------------------------------------------------------------------

    async def publish(self, item_id: str) -> None:
        """Sends `library.item` for this item (S6 calls it as an item's progress changes).
        Throttled to one per item per second, during a run and outside one: a call within the
        second is merged into one sent at its end. Never raises: a failure is logged."""
        try:
            if item_id in self._due:
                return  # merged into the one already due
            last = self._last_sent.get(item_id)
            now = self.services.clock.monotonic()
            if last is not None and now - last < PUBLISH_INTERVAL_S:
                self._due[item_id] = last + PUBLISH_INTERVAL_S
                self._wake.set()
                return
            await self._send(item_id)
        except Exception:
            log.exception("library: couldn't publish %s", item_id)

    async def _send(self, item_id: str) -> None:
        self._last_sent[item_id] = self.services.clock.monotonic()
        item = await self.item(item_id)
        if item is not None:
            self.services.bus.publish("library.item", item)

    async def _send_due(self) -> None:
        """Background task: sends the merged `library.item` events when they're due."""
        clock = self.services.clock
        while True:
            if not self._due:
                self._wake.clear()
                await self._wake.wait()
                continue
            now = clock.monotonic()
            due = sorted(item_id for item_id, at in self._due.items() if at <= now)
            if not due:
                await clock.sleep(min(self._due.values()) - now)
                continue
            for item_id in due:
                del self._due[item_id]
                try:
                    await self._send(item_id)
                except Exception:
                    log.exception("library: couldn't publish %s", item_id)

    # --- Building items ------------------------------------------------------------------------

    async def _build(self, item_ids: Sequence[str] | None) -> list[tuple[LibraryItem, str]]:
        """LibraryItems (with their `added_at`, for sorting) for these ids, or every one."""
        facts = await self.services.store.call(lambda conn: _read_facts(conn, item_ids))
        if not facts.rows:
            return []
        with_access = [row["id"] for row in facts.rows if row["item_access"]]
        counts = await self.services.matching.item_counts(with_access) if with_access else {}
        return [
            (_library_item(row, counts.get(row["id"]), facts), row["added_at"])
            for row in facts.rows
        ]

    async def _row(self, item_id: str) -> sqlite3.Row | None:
        return await self.services.store.fetchone(
            "SELECT * FROM items WHERE id = ? AND kind <> 'album' AND removed_at IS NULL",
            (item_id,),
        )

    # --- Adding --------------------------------------------------------------------------------

    async def _read_playlist(self, playlist_id: str) -> Playlist:
        """GET /playlists/{id}, with Spotify's answers as the link's error codes. Other Web API
        errors (not connected, rate limited, …) go to the API's error handler."""
        try:
            return await self.services.ports.webapi.playlist(playlist_id, scope=OTHER)
        except NotFound as exc:
            raise ApiError(422, "not_found", "Spotify has no such playlist.") from exc
        except NoAccess as exc:
            raise ApiError(422, "private", "This playlist is private.") from exc

    async def _link_facts(self, playlist: Playlist) -> "_LinkFacts":
        row = await self._row(playlist.id)
        followed = await self.services.store.fetchone(
            "SELECT * FROM followed_playlists WHERE id = ?", (playlist.id,)
        )
        user_id = (await self.services.auth.load()).user_id
        owned = user_id is not None and playlist.owner_id == user_id
        access = owned or (followed is not None and bool(followed["collaborative"]))
        return _LinkFacts(
            followed=followed, owned=owned, item_access=access, already_added=row is not None
        )

    async def _fetch_added(self, playlist: Playlist) -> None:
        """An added playlist with item access: its track list now. On a failure, the next
        refresh fetches it."""
        try:
            await self.services.catalog.fetch_playlist_tracks(
                playlist.id, playlist.snapshot_id, scope=OTHER
            )
        except WebApiError as exc:
            log.warning("library: %s's track list couldn't be read now: %s", playlist.id, exc)
            self.services.catalog.request_refresh("item_added")

    async def _update_backlog(self) -> None:
        try:
            await self.services.backlog.update()
        except Exception:
            log.warning("library: the backlog estimate couldn't be updated", exc_info=True)

    # --- Track lists ---------------------------------------------------------------------------

    async def _listed_tracks(self, row: sqlite3.Row) -> TrackList:
        item_id = row["id"]
        data = await self.services.store.call(lambda conn: _read_listed(conn, item_id))
        index = await self.services.matching.index()
        last_backup = _parse_time(row["last_backup_at"])
        music_dir = self.services.config.music_dir
        tracks = []
        total = 0
        duration_ms = 0
        for entry in data.entries:
            track = _listed_track(entry, data, index, last_backup, music_dir)
            if track.state != "unplayable":
                total += 1
                duration_ms += track.duration_ms or 0
            tracks.append(track)
        return TrackList(
            item_id=item_id,
            item_access=True,
            total=total,
            duration_ms=duration_ms,
            tracks=tracks,
        )

    async def _recorded_tracks(self, row: sqlite3.Row) -> TrackList:
        rows = await self.services.store.fetchall(
            "SELECT tr.track_id, tr.artist, tr.title, tr.length_ms, t.artists, t.album_name, "
            "t.duration_ms, f.spytify_key, f.bytes, f.path, f.recorded_at, f.duration_ms AS "
            "file_ms FROM run_items ri "
            "JOIN track_results tr ON tr.run_item_id = ri.id "
            "JOIN files f ON f.id = tr.file_id "
            "LEFT JOIN tracks t ON t.id = tr.track_id "
            "WHERE ri.item_id = ? AND tr.result = 'recorded' AND f.counted = 1 "
            "AND f.missing_at IS NULL ORDER BY f.recorded_at, f.id",
            (row["id"],),
        )
        seen: set[str] = set()
        tracks = []
        for r in rows:
            if r["spytify_key"] in seen:
                continue
            seen.add(r["spytify_key"])
            artists = _json_list(r["artists"]) if r["artists"] else [r["artist"]]
            duration = r["duration_ms"] if r["duration_ms"] is not None else r["length_ms"]
            tracks.append(
                ItemTrack(
                    position=None,
                    track_id=r["track_id"],
                    title=r["title"],
                    artists=artists,
                    album=r["album_name"],
                    duration_ms=duration if duration is not None else r["file_ms"],
                    state="recorded",
                    size_bytes=r["bytes"],
                    path=r["path"],
                    reason=None,
                    recorded_at=r["recorded_at"],
                )
            )
        return TrackList(
            item_id=row["id"],
            item_access=bool(row["item_access"]),
            total=row["total"],
            duration_ms=None,
            tracks=tracks,
        )


@dataclass(frozen=True, slots=True)
class _LinkFacts:
    followed: sqlite3.Row | None  # its followed_playlists row
    owned: bool
    item_access: bool
    already_added: bool


@dataclass(slots=True)
class _Listed:
    """An item's stored track list and what History says about its tracks."""

    entries: list[sqlite3.Row]
    files: dict[str, sqlite3.Row]  # spytify_key → the latest file History has for it
    last_results: dict[str, sqlite3.Row]  # track id → its result in the last run that played it


# --- On the database thread ---------------------------------------------------------------------


def _read_facts(conn: sqlite3.Connection, item_ids: Sequence[str] | None) -> _Facts:
    facts = _Facts()
    sql = (
        "SELECT * FROM items WHERE kind IN ('owned', 'liked', 'followed', 'linked') "
        "AND removed_at IS NULL"
    )
    params: list[Any] = []
    if item_ids is not None:
        if not item_ids:
            return facts
        sql += f" AND id IN ({', '.join('?' * len(item_ids))})"
        params = list(item_ids)
    facts.rows = conn.execute(sql, params).fetchall()
    if not facts.rows:
        return facts
    ids = [row["id"] for row in facts.rows]
    marks = ", ".join("?" * len(ids))

    run = conn.execute(
        "SELECT id FROM runs WHERE kind = 'run' AND state <> 'ended' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run is not None:
        facts.run_id = run["id"]
        for row in conn.execute(
            f"SELECT item_id, state, recorded, planned FROM run_items "
            f"WHERE run_id = ? AND state <> 'removed' AND item_id IN ({marks})",
            [run["id"], *ids],
        ):
            facts.in_run[row["item_id"]] = row

    ran = ", ".join(f"'{state}'" for state in _RAN_STATES)
    for row in conn.execute(
        f"SELECT item_id, state FROM (SELECT item_id, state, ROW_NUMBER() OVER "
        f"(PARTITION BY item_id ORDER BY id DESC) AS n FROM run_items "
        f"WHERE state IN ({ran}) AND item_id IN ({marks})) WHERE n = 1",
        ids,
    ):
        facts.last_outcome[row["item_id"]] = row["state"]

    for row in conn.execute(
        f"SELECT ri.item_id AS item_id, COUNT(DISTINCT f.spytify_key) AS n FROM run_items ri "
        f"JOIN track_results tr ON tr.run_item_id = ri.id JOIN files f ON f.id = tr.file_id "
        f"WHERE tr.result = 'recorded' AND f.counted = 1 AND f.missing_at IS NULL "
        f"AND ri.item_id IN ({marks}) GROUP BY ri.item_id",
        ids,
    ):
        facts.history[row["item_id"]] = row["n"]
    return facts


def _read_listed(conn: sqlite3.Connection, item_id: str) -> _Listed:
    entries = conn.execute(
        "SELECT it.position, it.track_id, it.playable, it.unplayable_reason, it.added_at, "
        "t.name, t.artists, t.album_name, t.duration_ms, t.spytify_key "
        "FROM item_tracks it LEFT JOIN tracks t ON t.id = it.track_id "
        "WHERE it.item_id = ? ORDER BY it.position",
        (item_id,),
    ).fetchall()
    files: dict[str, sqlite3.Row] = {}
    for row in conn.execute(
        "SELECT f.spytify_key, f.path, f.bytes, f.recorded_at FROM files f "
        "WHERE f.counted = 1 AND f.missing_at IS NULL AND f.spytify_key IN "
        "(SELECT t.spytify_key FROM item_tracks it JOIN tracks t ON t.id = it.track_id "
        "WHERE it.item_id = ?) ORDER BY f.recorded_at, f.id",
        (item_id,),
    ):
        files[row["spytify_key"]] = row  # the latest file wins
    last_results: dict[str, sqlite3.Row] = {}
    last_run_item = conn.execute(
        "SELECT MAX(id) AS id FROM run_items WHERE item_id = ? AND started_at IS NOT NULL",
        (item_id,),
    ).fetchone()
    if last_run_item is not None and last_run_item["id"] is not None:
        for row in conn.execute(
            "SELECT track_id, result, reason FROM track_results "
            "WHERE run_item_id = ? AND track_id IS NOT NULL AND result IS NOT NULL ORDER BY id",
            (last_run_item["id"],),
        ):
            last_results[row["track_id"]] = row  # a later take of the same track wins
    return _Listed(entries=entries, files=files, last_results=last_results)


# --- Building models ----------------------------------------------------------------------------


def _library_item(row: sqlite3.Row, counts: ItemCounts | None, facts: _Facts) -> LibraryItem:
    kind = row["kind"]
    item_id = row["id"]
    if counts is not None:
        total: int | None = counts.total
        recorded = counts.recorded
        new: int | None = counts.new
    else:
        total = row["total"]
        recorded = facts.history.get(item_id, 0)
        new = None
    in_run = facts.in_run.get(item_id)
    progress = None
    if in_run is not None and facts.run_id is not None:
        progress = ItemProgress(
            run_id=facts.run_id,
            state=in_run["state"],
            recorded=in_run["recorded"],
            planned=in_run["planned"],
        )
    return LibraryItem(
        id=item_id,
        kind=kind,
        uri=row["uri"],
        name=row["name"],
        owner="you" if kind in ("owned", "liked") else _owner(row["owner_name"], row["owner_id"]),
        cover=None
        if kind == "liked"
        else cover_url("library", item_id, row["thumb_path"], row["image_id"]),
        cover_source=row["cover_source"],
        tracked=bool(row["tracked"]),
        item_access=bool(row["item_access"]),
        total=total,
        recorded=recorded,
        new=new,
        last_backup_at=row["last_backup_at"],
        status=_status(row, in_run, facts.last_outcome.get(item_id), new),
        removable=kind in ("followed", "linked"),
        progress=progress,
    )


def _status(
    row: sqlite3.Row, in_run: sqlite3.Row | None, last_outcome: str | None, new: int | None
) -> str:
    """The pill, in the module docstring's order."""
    if in_run is not None and in_run["state"] in _RECORDING_STATES:
        return "recording"
    if in_run is not None and in_run["state"] in _QUEUED_STATES:
        return "queued"
    if row["unavailable_at"] is not None:
        return "unavailable"
    if not row["tracked"]:
        return "not_tracked"
    if row["last_backup_at"] is None:
        return "never_backed_up"
    if last_outcome == "partial":
        return "partial"
    if new:
        return "new"
    return "up_to_date"


def _listed_track(
    entry: sqlite3.Row,
    data: _Listed,
    index: RecordedIndex,
    last_backup: datetime | None,
    music_dir: Path,
) -> ItemTrack:
    """One entry of a stored track list, with its state (see the module docstring)."""
    reason = entry["unplayable_reason"]
    title = entry["name"]
    if title is None:
        title = "Local file" if reason == "local" else "Empty entry"
    common: dict[str, Any] = {
        "position": entry["position"] + 1,
        "track_id": entry["track_id"],
        "title": title,
        "artists": _json_list(entry["artists"]),
        "album": entry["album_name"],
        "duration_ms": entry["duration_ms"],
        "size_bytes": None,
        "path": None,
        "reason": None,
        "recorded_at": None,
    }
    if not entry["playable"]:
        return ItemTrack(state="unplayable", **common)
    key = entry["spytify_key"]
    result = data.last_results.get(entry["track_id"])
    if key is not None and index.has(key):
        file = data.files.get(key)
        if file is not None:
            common.update(
                size_bytes=file["bytes"], path=file["path"], recorded_at=file["recorded_at"]
            )
        else:
            common.update(path=_relative(index.path(key), music_dir))
        duplicate = result is not None and result["result"] == "skipped"
        if duplicate and result["reason"] == "duplicate":
            return ItemTrack(state="skipped_duplicate", **common)
        return ItemTrack(state="recorded", **common)
    if result is not None and result["result"] == "failed":
        common.update(reason=result["reason"])
        return ItemTrack(state="failed", **common)
    added = _parse_time(entry["added_at"])
    if last_backup is None or (added is not None and added > last_backup):
        return ItemTrack(state="new", **common)
    return ItemTrack(state="missing", **common)


# --- Small helpers ------------------------------------------------------------------------------


def _matches_filter(item: LibraryItem, filter: LibraryFilter) -> bool:
    if filter == "tracked":
        return item.tracked
    if filter == "not_tracked":
        return not item.tracked
    if filter == "owned":
        return item.kind in ("owned", "liked")
    if filter == "added":
        return item.kind in ("followed", "linked")
    return True


def _sort_key(item: LibraryItem, added_at: str, sort: LibrarySort) -> tuple[Any, ...]:
    """Newest or largest first; missing values last; ties by name."""
    name = item.name.casefold()
    if sort == "name":
        return (name, item.id)
    if sort == "recently_added":
        return (-_timestamp(added_at), name, item.id)
    if sort == "track_count":
        return (item.total is None, -(item.total or 0), name, item.id)
    backed_up = item.last_backup_at
    return (backed_up is None, -(backed_up.timestamp() if backed_up else 0.0), name, item.id)


def _timestamp(text: str | None) -> float:
    moment = _parse_time(text)
    return moment.timestamp() if moment is not None else 0.0


def _parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return parse_iso(text)
    except ValueError:
        return None


def _owner(name: str | None, owner_id: str | None) -> str:
    return name or owner_id or ""


def _json_list(text: str | None) -> list[str]:
    if not text:
        return []
    value = json.loads(text)
    return [str(v) for v in value] if isinstance(value, list) else []


def _relative(path: str | None, music_dir: Path) -> str | None:
    """A path from Spytify's index (absolute, under the music folder) relative to it."""
    if path is None:
        return None
    try:
        return str(Path(path).relative_to(music_dir))
    except ValueError:
        return path


def _parse_link(url: str) -> str:
    try:
        return parse_playlist_link(url)
    except LinkError as exc:
        raise ApiError(422, exc.code, str(exc)) from exc


def _already_added() -> ApiError:
    return ApiError(409, "already_added", "This playlist is already in the Library.")
