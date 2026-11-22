"""Albums: your saved albums, added once and recorded once (web-ui.md § Albums).

Owner: albums-covers. Built by services.py as `services.albums`. Specs: web-ui.md § Albums (all
subsections) and wizard step 8; design.md § Web API usage ("Albums: fetched once, when added");
openapi.yaml tag `albums` (Album, AlbumsSummary, SavedAlbum, TrackList); events.md `album.item`.

Frozen for other modules and S6: `album()` and `publish()`.

**Saved albums** (GET /api/albums/saved → `saved()`): every page of GET /me/albums (50 each),
most recently saved first; `saved_total` is the answer's total, and `items` the ones not on the
page yet (no `items` row with kind 'album' and `removed_at` NULL). `artist` is the first album
artist, `year` from `release_date`, `total` the album's `total_tracks`, `cover` the listed 300 px
image URL (used at once, never stored), `saved_at` the entry's `added_at`. The listing is kept in
memory for a few minutes, so adding right after opening the modal costs no second listing.
409 `not_connected`/`connection_expired` when the Web API isn't usable.

**Adding** (POST /api/albums → `add()`): `{ids}` or `{all: true}` (every saved album not added
yet; choosing "all" again only adds the missing ones). Each album comes from the saved listing
(`skipped` with `not_saved` when it isn't there, `already_added` when it's on the page). Its
tracks: the listing's first page (`album.tracks`), then GET /albums/{id}/tracks for the rest
(404 → `not_found`), stored with `catalog.tracks.replace_item_tracks`. The `items` row: kind
'album', uri, name, owner fields NULL, `artist`, `year`, `tracked` 1, `added_by` 'user' ('setup'
while setup isn't complete), `added_at` now, `saved_at`, `total` (the playable count), and
`removed_at` cleared for one added again. Then `services.covers.update(id, album.images)`; a
cover that can't be saved (a full disk) is logged, and the album stays added.
After every POST: `services.setup.mark_done("albums")` (step 8), `album.item` for each added
album, and `await services.backlog.update()`.

**The page** (GET /api/albums → `list_albums()`): albums with `removed_at` NULL, filtered,
searched (album or artist, case-insensitive) and sorted (ties by artist, then album), with the
header's summary.
- `recorded` from `services.matching.item_counts()`; `total` the playable count.
- `status`: `recording` while in the current run's queue as the current item, `queued` while
  it's up next or not complete, `unavailable` when `unavailable_at` is set, `partial` when its
  last run item ended `partial` (or failed tracks), `recorded` once `completed_at` is set (a
  lifecycle fact S6 writes: later missing files don't un-complete it).
- `cover`: `covers.cover_url("albums", id, thumb_path, image_id)`.
- `progress`: set while it's in the current run, else null.

**Removing** (DELETE /api/albums/{id} → `remove()`): sets `removed_at`; files and History are
kept, and the backlog is updated. 404 when it isn't on the page. (Removing it from the current
run's queue is S6's.)

**Tracks** (GET /api/albums/{id}/tracks → `tracks()`): TrackList in album order, `item_access`
true, with each track's state (recorded, skipped_duplicate, missing, failed, unplayable), as
LibraryService.tracks does for playlists.

**Events:** `publish(id)` sends `album.item` with the album, at most one per album per second.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from spotivault import ports
from spotivault.api.models import (
    AddAlbumsResponse,
    AddAlbumsResponseSkippedItem,
    Album,
    AlbumsSummary,
    GetSavedAlbumsResponse,
    ItemProgress,
    ItemTrack,
    ListAlbumsResponse,
    TrackList,
)
from spotivault.api.models import (
    SavedAlbum as SavedAlbumModel,
)
from spotivault.catalog.covers import cover_url, listed_thumbnail
from spotivault.catalog.tracks import ListedTrack, replace_item_tracks
from spotivault.clock import iso_ms
from spotivault.errors import not_found
from spotivault.matching import ItemCounts

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

SAVED_LISTING_TTL_S = 5 * 60
PAGE_SIZE = 50  # the Web API's limit for these listings
PUBLISH_GAP_S = 1.0  # at most one album.item per album per second
PUBLISH_FLUSH_S = 0.25  # how often the held-back events are checked

type AlbumFilter = Literal["all", "recorded", "queued", "partial"]
type AlbumSort = Literal["recently_added", "album", "artist", "year"]
type AlbumStatus = Literal["queued", "recording", "recorded", "partial", "unavailable"]

# The run-item states of an album being recorded now, and of one waiting in the current run.
# `interrupted` waits: it was re-queued at the end after a stall (openapi.yaml ItemState).
RECORDING_STATES = frozenset(
    {"planning", "preflight", "preparing", "starting", "playing", "finishing"}
)
QUEUED_RUN_STATES = frozenset({"up_next", "interrupted", "carried_over"})
QUEUED_STATUSES = frozenset({"queued", "recording"})  # the Queued filter and summary

# The albums on the page (kind 'album', not removed), with the columns the page shows.
_PAGE_ROWS = (
    "SELECT id, uri, name, artist, year, total, added_at, completed_at, unavailable_at, "
    "thumb_path, image_id FROM items WHERE kind = 'album' AND removed_at IS NULL"
)
_TRACK_ROWS = (
    "SELECT it.position, it.playable, it.track_id, t.name, t.artists, t.album_name, "
    "t.duration_ms, t.spytify_key FROM item_tracks it LEFT JOIN tracks t ON t.id = it.track_id "
    "WHERE it.item_id = ? ORDER BY it.position"
)
# Adding an album. The total is set after its tracks are stored, in the same transaction.
_UPSERT_ALBUM = (
    "INSERT INTO items (id, kind, uri, name, artist, year, tracked, added_by, added_at, saved_at, "
    "removed_at, item_access, total, catalog_fetched_at) "
    "VALUES (?, 'album', ?, ?, ?, ?, 1, ?, ?, ?, NULL, 1, 0, ?) "
    "ON CONFLICT (id) DO UPDATE SET uri = excluded.uri, name = excluded.name, "
    "artist = excluded.artist, year = excluded.year, tracked = 1, "
    "added_by = excluded.added_by, added_at = excluded.added_at, saved_at = excluded.saved_at, "
    "removed_at = NULL, unavailable_at = NULL, unavailable_reason = NULL, item_access = 1, "
    "total = excluded.total, catalog_fetched_at = excluded.catalog_fetched_at"
)


@dataclass(frozen=True, slots=True)
class _Listing:
    """The saved-albums listing, kept for SAVED_LISTING_TTL_S (monotonic time)."""

    at: float
    albums: list[ports.SavedAlbum]
    total: int


@dataclass(frozen=True, slots=True)
class _RunItem:
    """An album's row in the current run."""

    state: str
    recorded: int
    planned: int | None


@dataclass(frozen=True, slots=True)
class _Built:
    """An album as the page shows it, with what the filters and sorts need."""

    album: Album
    status: str
    recorded: int
    name: str
    artist: str
    year: int | None
    added_at: str


class AlbumsService:
    """The Albums page. See the module docstring."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        self._listing_cache: _Listing | None = None
        self._last_sent: dict[str, float] = {}  # album id → monotonic time of its last album.item
        self._pending: set[str] = set()  # album ids whose event waits for the one-second gap
        services.add_background("albums.publish", self._flush_pending)

    async def list_albums(
        self,
        *,
        filter: AlbumFilter = "all",
        q: str | None = None,
        sort: AlbumSort = "recently_added",
    ) -> ListAlbumsResponse:
        built = await self._build(await self._album_rows())
        summary = AlbumsSummary(
            total=len(built),
            recorded=sum(1 for item in built if item.status == "recorded"),
            queued=sum(1 for item in built if item.status in QUEUED_STATUSES),
            partial=sum(1 for item in built if _is_partial(item)),
        )
        needle = q.strip().casefold() if q else ""
        shown = [
            item
            for item in built
            if _matches(item, filter)
            and (not needle or needle in item.name.casefold() or needle in item.artist.casefold())
        ]
        # Ties sort by artist, then album: the first sort sets that order, the next keeps it.
        shown.sort(key=lambda item: (item.artist.casefold(), item.name.casefold()))
        if sort == "recently_added":
            shown.sort(key=lambda item: item.added_at, reverse=True)
        elif sort == "album":
            shown.sort(key=lambda item: item.name.casefold())
        elif sort == "artist":
            shown.sort(key=lambda item: item.artist.casefold())
        else:  # year, undated albums last
            shown.sort(key=lambda item: (item.year is None, item.year or 0))
        return ListAlbumsResponse(items=[item.album for item in shown], summary=summary)

    async def saved(self) -> GetSavedAlbumsResponse:
        albums, total = await self._listing()
        on_page = await self._on_page_ids()
        items = [_saved_model(saved) for saved in albums if saved.album.id not in on_page]
        return GetSavedAlbumsResponse(saved_total=total, items=items)

    async def add(
        self, *, ids: list[str] | None = None, all_saved: bool = False
    ) -> AddAlbumsResponse:
        """`ids` for `{ids: [...]}`, `all_saved=True` for `{all: true}`.

        Ids use the kept listing (the modal just loaded it), and a fresh one when an id isn't in
        it: an album saved since then is still found. "All" always lists afresh."""
        on_page = await self._on_page_ids()
        albums, _ = await self._listing(fresh=all_saved)
        if not all_saved:
            known = {saved.album.id for saved in albums}
            if any(i not in known and i not in on_page for i in dict.fromkeys(ids or [])):
                albums, _ = await self._listing(fresh=True)
        listed = {saved.album.id: saved for saved in albums}
        skipped: list[AddAlbumsResponseSkippedItem] = []
        wanted: list[ports.SavedAlbum] = []
        if all_saved:
            wanted = [saved for saved in albums if saved.album.id not in on_page]
        else:
            for album_id in dict.fromkeys(ids or []):  # each id once, in the order given
                if album_id in on_page:
                    skipped.append(
                        AddAlbumsResponseSkippedItem(id=album_id, reason="already_added")
                    )
                elif album_id in listed:
                    wanted.append(listed[album_id])
                else:
                    skipped.append(AddAlbumsResponseSkippedItem(id=album_id, reason="not_saved"))

        added_by = "user" if await self.services.setup.is_complete() else "setup"
        added: list[str] = []
        try:
            for saved in wanted:
                try:
                    tracks = await self._all_tracks(saved)
                except ports.NotFound:
                    skipped.append(
                        AddAlbumsResponseSkippedItem(id=saved.album.id, reason="not_found")
                    )
                    continue
                await self._store(saved, tracks, added_by)
                added.append(saved.album.id)
                try:
                    await self.services.covers.update(saved.album.id, saved.album.images)
                except Exception:
                    # The album is added either way, without a cover for now, like library.add.
                    log.warning(
                        "albums: %s's cover couldn't be saved", saved.album.id, exc_info=True
                    )
        finally:
            # What was added stays (its rows are committed), so its events and the backlog follow
            # even when a later album's download failed.
            if added:
                await self.services.backlog.update()
                for album_id in added:
                    await self.publish(album_id)
        await self.services.setup.mark_done("albums")

        models: list[Album] = []
        for album_id in added:
            model = await self.album(album_id)
            if model is not None:
                models.append(model)
        return AddAlbumsResponse(added=models, skipped=skipped)

    async def remove(self, album_id: str) -> None:
        # Files and History stay: only the page forgets the album.
        now = iso_ms(self.services.clock.now())
        result = await self.services.store.execute(
            "UPDATE items SET removed_at = ? "
            "WHERE id = ? AND kind = 'album' AND removed_at IS NULL",
            (now, album_id),
        )
        if result.rowcount == 0:
            raise not_found("No such album on the Albums page.")
        log.info("albums: %s removed (its files are kept)", album_id)
        # The backlog counts the albums on the page, so it changes too. A failure there is logged:
        # the album is removed either way.
        try:
            await self.services.backlog.update()
        except Exception:
            log.warning("albums: the backlog estimate couldn't be updated", exc_info=True)

    async def tracks(self, album_id: str) -> TrackList:
        store = self.services.store
        item = await store.fetchone(
            "SELECT total FROM items WHERE id = ? AND kind = 'album' AND removed_at IS NULL",
            (album_id,),
        )
        if item is None:
            raise not_found("No such album on the Albums page.")
        rows = await store.fetchall(_TRACK_ROWS, (album_id,))
        index = await self.services.matching.index()
        files = await self._latest_files(album_id)
        results = await self._last_results(album_id)

        tracks: list[ItemTrack] = []
        duration_ms = 0
        for row in rows:
            track_id: str | None = row["track_id"]
            state: str = "unplayable"
            size: int | None = None
            path: str | None = None
            recorded_at: str | None = None
            reason: str | None = None
            if row["playable"]:
                duration_ms += row["duration_ms"] or 0
                key: str | None = row["spytify_key"]
                if key is not None and index.has(key):
                    state = "recorded"
                    file = files.get(key)
                    if file is not None:
                        size, path, recorded_at = file["bytes"], file["path"], file["recorded_at"]
                else:
                    # Not in the index: the last run's result says why (design.md, D10 tables).
                    result, why = results.get(track_id or "", (None, None))
                    if result == "failed":
                        state, reason = "failed", why
                    elif result == "skipped" and why == "duplicate":
                        state = "skipped_duplicate"
                    else:
                        state = "missing"
            artists = json.loads(row["artists"]) if row["artists"] else []
            tracks.append(
                ItemTrack(
                    position=row["position"] + 1,  # Web API order, from 1
                    track_id=track_id,
                    title=row["name"] or "",  # a local file keeps no name
                    artists=artists,
                    album=row["album_name"],
                    duration_ms=row["duration_ms"],
                    state=state,
                    size_bytes=size,
                    path=path,
                    reason=reason,
                    recorded_at=recorded_at,
                )
            )
        return TrackList(
            item_id=album_id,
            item_access=True,
            total=item["total"],
            duration_ms=duration_ms,
            tracks=tracks,
        )

    async def album(self, album_id: str) -> Album | None:
        """One album on the page, or None (not added, or removed)."""
        rows = await self._album_rows(album_id)
        if not rows:
            return None
        built = await self._build(rows)
        return built[0].album

    async def publish(self, album_id: str) -> None:
        """Sends `album.item` for this album (S6 calls it as an album's progress changes).
        Throttled to one per album per second. Never raises: a failure is logged."""
        try:
            now = self.services.clock.monotonic()
            last = self._last_sent.get(album_id)
            if last is not None and now - last < PUBLISH_GAP_S:
                # The flush task sends it once the second is over (only the latest state counts).
                self._pending.add(album_id)
                return
            await self._send(album_id)
        except Exception:
            log.exception("album.item for %s not sent", album_id)

    # --- Helpers ---------------------------------------------------------------------------------

    async def _send(self, album_id: str) -> None:
        self._last_sent[album_id] = self.services.clock.monotonic()
        self._pending.discard(album_id)
        album = await self.album(album_id)
        if album is not None:  # removed since: nothing to show
            self.services.bus.publish("album.item", album)

    async def _flush_pending(self) -> None:
        """Background: sends the events the one-second rule held back, once their second is over."""
        while True:
            await self.services.clock.sleep(PUBLISH_FLUSH_S)
            now = self.services.clock.monotonic()
            for album_id in list(self._pending):
                last = self._last_sent.get(album_id, float("-inf"))
                if now - last < PUBLISH_GAP_S:
                    continue
                try:
                    await self._send(album_id)
                except Exception:
                    log.exception("album.item for %s not sent", album_id)

    async def _scope(self) -> ports.ApiScope:
        """The usage log's scope: the wizard's listings count as setup's (api_requests)."""
        if await self.services.setup.is_complete():
            return ports.OTHER
        return ports.SETUP

    async def _listing(self, *, fresh: bool = False) -> tuple[list[ports.SavedAlbum], int]:
        """Every page of GET /me/albums, most recently saved first, kept for a few minutes so the
        modal and the add that follows share one listing. `fresh` asks Spotify again."""
        clock = self.services.clock
        now = clock.monotonic()
        cached = self._listing_cache
        if not fresh and cached is not None and now - cached.at < SAVED_LISTING_TTL_S:
            return cached.albums, cached.total
        scope = await self._scope()
        albums: list[ports.SavedAlbum] = []
        total = 0
        offset = 0
        while True:
            page = await self.services.ports.webapi.saved_albums(
                offset=offset, limit=PAGE_SIZE, scope=scope
            )
            albums.extend(page.items)
            total = page.total
            if page.next_offset is None or not page.items:
                break
            offset = page.next_offset
        self._listing_cache = _Listing(at=now, albums=albums, total=total)
        return albums, total

    async def _all_tracks(self, saved: ports.SavedAlbum) -> list[ports.Track]:
        """The album's tracks in order: the listing's first page, then the rest (404 propagates
        as NotFound, and the album is skipped)."""
        album = saved.album
        scope = await self._scope()
        tracks: list[ports.Track] = []
        first = album.tracks
        offset: int | None = 0
        if first is not None:
            tracks.extend(first.items)
            offset = first.next_offset
        while offset is not None:
            page = await self.services.ports.webapi.album_tracks(
                album.id, offset=offset, limit=PAGE_SIZE, scope=scope
            )
            if not page.items:
                break
            tracks.extend(page.items)
            offset = page.next_offset
        return tracks

    async def _store(
        self, saved: ports.SavedAlbum, tracks: list[ports.Track], added_by: str
    ) -> None:
        """The album's row and its track list, in one transaction. Its cover comes after."""
        album = saved.album
        now = iso_ms(self.services.clock.now())
        entries = [ListedTrack(track=track) for track in tracks]

        def save(conn: sqlite3.Connection) -> None:
            conn.execute(
                _UPSERT_ALBUM,
                (
                    album.id,
                    album.uri,
                    album.name,
                    _artist(album),
                    _year(album.release_date),
                    added_by,
                    now,
                    saved.added_at,
                    now,
                ),
            )
            summary = replace_item_tracks(conn, album.id, entries, now)
            conn.execute("UPDATE items SET total = ? WHERE id = ?", (summary.playable, album.id))

        await self.services.store.transaction(save)

    async def _on_page_ids(self) -> set[str]:
        rows = await self.services.store.fetchall(
            "SELECT id FROM items WHERE kind = 'album' AND removed_at IS NULL"
        )
        return {row["id"] for row in rows}

    async def _album_rows(self, album_id: str | None = None) -> list[sqlite3.Row]:
        if album_id is None:
            return await self.services.store.fetchall(_PAGE_ROWS)
        return await self.services.store.fetchall(_PAGE_ROWS + " AND id = ?", (album_id,))

    async def _build(self, rows: list[sqlite3.Row]) -> list[_Built]:
        """The page's albums, with their status and progress. One read each of the counts, the
        current run and the last run, however many albums there are."""
        if not rows:
            return []
        counts: dict[str, ItemCounts] = await self.services.matching.item_counts(
            [row["id"] for row in rows]
        )
        run_id, current = await self._current_run()
        last = await self._last_run_items()
        built: list[_Built] = []
        for row in rows:
            item_id: str = row["id"]
            run_item = current.get(item_id)
            recorded = counts[item_id].recorded if item_id in counts else 0
            status = _status(row, run_item, last.get(item_id))
            progress = None
            if run_item is not None and run_id is not None:
                progress = ItemProgress(
                    run_id=run_id,
                    state=run_item.state,
                    recorded=run_item.recorded,
                    planned=run_item.planned,
                )
            album = Album(
                id=item_id,
                uri=row["uri"],
                name=row["name"],
                artist=row["artist"],
                year=row["year"],
                cover=cover_url("albums", item_id, row["thumb_path"], row["image_id"]),
                total=row["total"],
                recorded=recorded,
                status=status,
                added_at=row["added_at"],
                completed_at=row["completed_at"],
                progress=progress,
            )
            built.append(
                _Built(
                    album=album,
                    status=status,
                    recorded=recorded,
                    name=row["name"],
                    artist=row["artist"],
                    year=row["year"],
                    added_at=row["added_at"],
                )
            )
        return built

    async def _current_run(self) -> tuple[int | None, dict[str, _RunItem]]:
        """The run that's going (at most one), and its items by id."""
        store = self.services.store
        run = await store.fetchone("SELECT id FROM runs WHERE kind = 'run' AND state <> 'ended'")
        if run is None:
            return None, {}
        rows = await store.fetchall(
            "SELECT item_id, state, recorded, planned FROM run_items WHERE run_id = ?",
            (run["id"],),
        )
        items = {
            row["item_id"]: _RunItem(row["state"], row["recorded"], row["planned"]) for row in rows
        }
        return run["id"], items

    async def _last_run_items(self) -> dict[str, tuple[str, int]]:
        """Each album's item in its last run that ended: (state, failed tracks)."""
        rows = await self.services.store.fetchall(
            "SELECT ri.item_id, ri.state, ri.failed FROM run_items ri "
            "WHERE ri.ended_at IS NOT NULL "
            "AND ri.item_id IN (SELECT id FROM items WHERE kind = 'album' AND removed_at IS NULL) "
            "AND ri.run_id = (SELECT MAX(r2.run_id) FROM run_items r2 "
            "WHERE r2.item_id = ri.item_id AND r2.ended_at IS NOT NULL)"
        )
        return {row["item_id"]: (row["state"], row["failed"]) for row in rows}

    async def _latest_files(self, album_id: str) -> dict[str, sqlite3.Row]:
        """The newest counted file of each of the album's keys (History's record)."""
        rows = await self.services.store.fetchall(
            "SELECT f.spytify_key, f.path, f.bytes, f.recorded_at FROM files f "
            "WHERE f.counted = 1 AND f.missing_at IS NULL "
            "AND f.spytify_key IN (SELECT t.spytify_key FROM item_tracks it "
            "JOIN tracks t ON t.id = it.track_id WHERE it.item_id = ?) ORDER BY f.id",
            (album_id,),
        )
        return {row["spytify_key"]: row for row in rows}

    async def _last_results(self, album_id: str) -> dict[str, tuple[str | None, str | None]]:
        """The album's takes in its last run, by track id: (result, reason)."""
        rows = await self.services.store.fetchall(
            "SELECT tr.track_id, tr.result, tr.reason FROM track_results tr "
            "JOIN run_items ri ON ri.id = tr.run_item_id "
            "WHERE ri.item_id = ? AND ri.run_id = "
            "(SELECT MAX(run_id) FROM run_items WHERE item_id = ?) ORDER BY tr.id",
            (album_id, album_id),
        )
        return {row["track_id"]: (row["result"], row["reason"]) for row in rows if row["track_id"]}


def _status(
    row: sqlite3.Row, run_item: _RunItem | None, last: tuple[str, int] | None
) -> AlbumStatus:
    """The pill, in the order web-ui.md's album states give: recording, queued, unavailable,
    partial (the last run ended partial, or had failed tracks), recorded, else queued."""
    if run_item is not None:
        if run_item.state in RECORDING_STATES:
            return "recording"
        if run_item.state in QUEUED_RUN_STATES:
            return "queued"
    if row["unavailable_at"] is not None:
        return "unavailable"
    if last is not None and (last[0] == "partial" or last[1] > 0):
        return "partial"
    if row["completed_at"] is not None:
        return "recorded"
    return "queued"


def _is_partial(item: _Built) -> bool:
    """The Partial filter: partial albums, and unavailable ones with recorded tracks."""
    return item.status == "partial" or (item.status == "unavailable" and item.recorded > 0)


def _matches(item: _Built, filter: AlbumFilter) -> bool:
    if filter == "all":
        return True
    if filter == "recorded":
        return item.status == "recorded"
    if filter == "queued":
        return item.status in QUEUED_STATUSES
    return _is_partial(item)


def _artist(album: ports.Album) -> str:
    return album.artists[0] if album.artists else ""


def _year(release_date: str | None) -> int | None:
    """The year of Spotify's release_date ('2026', '2026-01' or '2026-01-01')."""
    if release_date and release_date[:4].isdigit():
        return int(release_date[:4])
    return None


def _saved_model(saved: ports.SavedAlbum) -> SavedAlbumModel:
    album = saved.album
    thumb = listed_thumbnail(album.images)  # used at once, never stored
    return SavedAlbumModel(
        id=album.id,
        uri=album.uri,
        name=album.name,
        artist=_artist(album),
        year=_year(album.release_date),
        cover=thumb.url if thumb is not None else None,
        total=album.total_tracks,
        saved_at=saved.added_at,
    )
