"""The catalog refresh: playlists, Liked Songs, followed and linked playlists, from the Web API.

Owner: catalog-library. Built by services.py as `services.catalog`. Specs: design.md § Web API
usage (Load), § Run flow step 1 (D13), § Backlog estimate (when it's refreshed), § Playlist
covers (images come with the listing); web-ui.md § Library; contracts/schema.sql `items`,
`tracks`, `item_tracks`, `catalog_refreshes`; migration 002's `followed_playlists`.

Frozen for other modules and S6: `RefreshTrigger`, `RefreshResult`, `refresh()`,
`request_refresh()` and `last_refresh_at()`.

**One refresh**, `refresh(trigger=..., run_id=...)`, one at a time (a lock):
1. A `catalog_refreshes` row (trigger, run_id, started_at); every request counts against
   `ApiScope("refresh", <its id>)`, the run's own refresh included.
2. **Liked Songs** is the item `liked` (kind liked, uri `spotify:user:<user_id>:collection`, name
   "Liked Songs", no cover), made as soon as the user id is known: when step 5 stores the account
   (an AuthStore listener on `account`), so step 7 can set it before any refresh ends, or else at
   the first refresh (`services.auth.load().user_id`; GET /me only if it's missing). It starts
   tracked when the `auto_track_owned` setting is on, like your own playlists: step 7's "Include
   Liked Songs" is on by default, and "I'll choose in the Library" tracks nothing.
3. **GET /me/playlists**, every page (50 each):
   - **Yours** (`owner_id` is the user's): an `owned` item, made the first time it's seen (tracked
     when the `auto_track_owned` setting is on, `added_by` 'auto'), its name and owner kept
     current, and its cover passed to `services.covers.update(id, images)` straight away (image
     URLs expire within a day; no URL is stored).
   - **Everyone else's:** a `followed_playlists` row (the table is replaced each refresh). One
     already in the Library (kind `followed`, or `linked` until it shows up here) gets its name,
     owner, snapshot_id, total and cover updated the same way. A followed playlist you
     collaborate on has item access: kind stays `followed`, `item_access` 1, and it's fetched like
     your own (openapi.yaml LibraryKind). Its item access is decided when it's added (from
     `collaborative`) and lost on a 403; a listing never gives it back, so a 403 isn't asked for
     again on every refresh.
   - **Gone from the listing:** an owned item → Unavailable `deleted`; a followed one →
     `unfollowed` (`unavailable_at`, `unavailable_reason`; files kept). Back again → cleared.
4. **Linked playlists** aren't in /me/playlists: only a refresh with trigger `run` reads each
   tracked one with GET /playlists/{id}, for D13's snapshot_id, its name and cover (404 →
   Unavailable `deleted`; 403 → `private`). They're read before the track lists: they're cheap,
   and D13 needs them. Page-open refreshes skip them, so a refresh where nothing changed costs at
   most 3 requests (the S5 exit criterion).
5. **Track lists**, only for tracked items with item access, and only when needed:
   - **A playlist** is refetched (GET /playlists/{id}/items, every page) only when the listing's
     `snapshot_id` differs from the stored one, or it was never fetched. For an item with item
     access, the stored `snapshot_id` is the one its stored track list belongs to: it's written
     together with the list, so a list that failed to load, or an untracked item's list, is
     refetched once it's needed. 403 → `item_access` 0; 404 → Unavailable `deleted`.
   - **Liked Songs** has no snapshot_id: read /me/tracks from the newest page until reaching a
     track already stored with an `added_at` no newer than `liked_newest_added_at`, then compare
     the answer's `total` with the stored count plus the new entries; if they differ (a track was
     removed), read the rest of the list and store it whole.
   - Each list is stored with `catalog.tracks.replace_item_tracks`; `items.total` is its playable
     count, `catalog_fetched_at` now, and `changed_at` now when new tracks appeared.
   - An untracked item isn't fetched (it shows the listing's `items.total` until tracked);
     tracking it asks for a refresh (`request_refresh("item_added")`).
   - **Errors:** a 429 that outlasted the scheduler (RateLimited) or a Spotify outage
     (SpotifyUnavailable) stops the linked reads and the track lists there: the refresh ends
     `partial`, and the rest waits for the next one. Any other error fails that item only.
6. **D13 bookkeeping:** keep `snapshot_id` current for items without item access (followed and
   linked). Don't touch `last_full_pass_snapshot`, `last_full_pass_at` or `observed_tracks`: S6
   sets them after a clean full pass. `RefreshResult.snapshots_unread` lists the items without
   item access whose `snapshot_id` this refresh didn't read (the listing failed, a linked read
   failed or was never reached, every linked one outside a run's refresh, and untracked linked
   ones always: only tracked ones are read). Their stored snapshot_id may be stale, so D13 can't
   call them Up to date: S6 plays them whole (the cautious answer). Untracked ones are listed
   too, because createRun with `items` runs an item whatever its tracking.
7. **The end:** `services.webapi_usage.finish_scope(scope)` gives the counts and logs the Web API
   line; log "Catalog: 3 changed" and the covers line ("Covers: 4 saved · 1 at the size
   returned"; `saved` counts both) when there were any; fill the row's outcome (`ok`, `partial`
   when some items failed, `failed` when the listing did), items_changed, covers_*, api_* and
   error; publish `library.item` for each item that changed (`services.library.publish`), then
   `await services.backlog.update()`. A cover, the usage summary or the backlog failing is
   logged and never fails the refresh.

**When refreshes happen:** S6's run start (`refresh(trigger="run", run_id=...)`, awaited); page
opens through `request_refresh("page_open")` (the Dashboard via GET /api/backlog), at most once
every 15 minutes (THROTTLE_S) since the last one of any trigger started; `setup` after connecting
(step 7 needs the playlist count) and `item_added` after tracking or adding an item, both
unthrottled. Never during a run, except the run's own refresh: `watch` checks the `runs` table
just before it starts a queued refresh, and drops it while a run is going. Not connected (no
Client ID or no token), or Spotify already answered `invalid_grant`: no row is written, the
result says `skipped`. A connection past its `expires_at` date still refreshes: the date only
holds scheduled runs, and Spotify's own `invalid_grant` ends the refresh (web-ui.md step 5).

**auto_track_owned:** a settings listener (`services.settings.add_listener`), acting only when
the value changes. Turned on: every owned item is tracked, and new ones will be. Turned off before
setup is complete (wizard step 7's "I'll choose in the Library"): owned items that were tracked
automatically, and Liked Songs, are untracked, so nothing is tracked yet (web-ui.md step 7).
Turned off later: only new playlists stop being tracked.
"""

import asyncio
import json
import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from spotivault.catalog.tracks import ListedTrack, replace_item_tracks
from spotivault.clock import iso_ms, parse_iso
from spotivault.logs import redact
from spotivault.ports import (
    ApiScope,
    ConnectionExpired,
    Image,
    NoAccess,
    NotConnected,
    NotFound,
    Playlist,
    RateLimited,
    SavedTrack,
    SpotifyUnavailable,
    Track,
    WebApiError,
)
from spotivault.webapi.auth_store import AuthChange
from spotivault.webapi.usage import ScopeSummary

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

THROTTLE_S = 15 * 60
PAGE_LIMIT = 50  # the most a listing gives per request
PREVIEW_COVER_TTL_S = 12 * 3600  # a suggestion's cover URL is offered this long after it was seen
LIKED_ID = "liked"
LIKED_NAME = "Liked Songs"

type RefreshTrigger = Literal["run", "page_open", "setup", "item_added"]
type RefreshOutcome = Literal["ok", "partial", "failed", "skipped"]

# When several background refreshes are queued at once, one runs, recorded with the first of
# these that was asked for.
_TRIGGER_ORDER: tuple[RefreshTrigger, ...] = ("setup", "item_added", "page_open")
_NO_API = ScopeSummary(requests=0, retried=0, rate_limited=0)


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """How a refresh went. `refresh_id` is its `catalog_refreshes` row (None when skipped)."""

    refresh_id: int | None
    outcome: RefreshOutcome
    items_changed: int
    covers_saved: int
    covers_fallback: int
    api: ScopeSummary
    error: str | None = None
    # Playlists without item access (followed, linked), tracked or not, whose snapshot_id this
    # refresh didn't read, so D13 can't call them Up to date (module docstring, step 6).
    snapshots_unread: tuple[str, ...] = ()


class _StopTrackLists(Exception):
    """Spotify is rate limiting or down: fetching more track lists now would only make it
    worse. The refresh ends `partial`."""


@dataclass(slots=True)
class _Progress:
    """What one refresh did so far."""

    refresh_id: int
    scope: ApiScope
    changed: set[str] = field(default_factory=set)
    covers_saved: int = 0  # fallbacks included
    covers_fallback: int = 0
    failed_items: int = 0
    listing_failed: bool = False
    error: str | None = None
    # Items whose snapshot_id this refresh read: from the listing, or a linked one's own read.
    snapshots_read: set[str] = field(default_factory=set)

    def note_error(self, message: str) -> None:
        if self.error is None:
            self.error = message


@dataclass(slots=True)
class _Listing:
    """What applying GET /me/playlists to the database found (see `_apply_listing`)."""

    changed: set[str] = field(default_factory=set)
    covers: list[tuple[str, tuple[Image, ...]]] = field(default_factory=list)
    to_fetch: list[tuple[str, str | None]] = field(default_factory=list)  # (id, snapshot_id)


class CatalogService:
    """The catalog refresh. See the module docstring."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        self._lock = asyncio.Lock()  # one refresh at a time
        self._pending: set[RefreshTrigger] = set()  # queued by request_refresh, run by watch
        self._wake = asyncio.Event()  # set when something is queued
        self._idle = asyncio.Event()  # set while nothing is queued or running in the background
        self._idle.set()
        self._last_started_at: datetime | None = None  # for the 15-minute throttle
        self._auto_track_owned: bool | None = None  # the setting as last seen
        # Followed playlists' cover URLs as the last listing gave them, with when. Kept in memory
        # only: playlist image URLs expire within a day (getLibrarySuggestions).
        self._preview_covers: dict[str, tuple[str, datetime]] = {}
        services.add_startup("catalog", self.start)
        services.add_background("catalog.refresh", self.watch)
        services.settings.add_listener(self._settings_saved)
        services.auth.add_listener(self._auth_changed)

    # --- Frozen interface -----------------------------------------------------------------------

    async def refresh(self, *, trigger: RefreshTrigger, run_id: int | None = None) -> RefreshResult:
        """Refreshes the catalog now and returns how it went. S6 awaits it at the start of each
        run (trigger `run`, with its run id). Waits for a refresh already going, then runs."""
        async with self._lock:
            return await self._refresh(trigger, run_id)

    def request_refresh(self, trigger: Literal["page_open", "setup", "item_added"]) -> bool:
        """Asks for a refresh in the background and returns at once: True when one was queued,
        False when the throttle refused it (a `page_open` within 15 minutes of the last refresh).
        A queued refresh is dropped if a run is going when its turn comes. Never raises."""
        try:
            if trigger == "page_open" and not self._pending and self._throttled():
                return False
            self._pending.add(trigger)
            self._idle.clear()
            self._wake.set()
            return True
        except Exception:
            log.exception("catalog: couldn't queue a %s refresh", trigger)
            return False

    async def last_refresh_at(self) -> datetime | None:
        """When the last refresh that ran finished, or None before the first."""
        text = await self.services.store.fetchval(
            "SELECT MAX(finished_at) FROM catalog_refreshes WHERE finished_at IS NOT NULL"
        )
        return parse_iso(text) if text else None

    async def watch(self) -> None:
        """Background task: runs the refreshes `request_refresh` queued, one at a time. A failed
        refresh is logged, never raised: it would stop the controller."""
        while True:
            await self._wake.wait()
            self._wake.clear()
            triggers, self._pending = self._pending, set()
            if triggers:
                trigger = next(t for t in _TRIGGER_ORDER if t in triggers)
                try:
                    await self._run_queued(trigger)
                except Exception:
                    log.exception("catalog: the %s refresh failed", trigger)
            if not self._pending:
                self._idle.set()

    # --- For the Library -----------------------------------------------------------------------

    def preview_cover(self, playlist_id: str) -> str | None:
        """The cover URL the last listing gave a followed playlist, if it's under 12 hours old
        (suggestions). Never stored."""
        seen = self._preview_covers.get(playlist_id)
        if seen is None:
            return None
        url, at = seen
        if (self.services.clock.now() - at).total_seconds() > PREVIEW_COVER_TTL_S:
            return None
        return url

    async def fetch_playlist_tracks(
        self, item_id: str, snapshot_id: str | None, *, scope: ApiScope
    ) -> bool:
        """Fetches and stores one playlist's track list now (adding an item). Returns True when
        the item changed. NoAccess and NotFound are handled (item access lost, Unavailable);
        other Web API errors are raised."""
        return await self._fetch_playlist(item_id, snapshot_id, scope)

    async def wait_idle(self) -> None:
        """Waits until no background refresh is queued or running (tests)."""
        await self._idle.wait()

    # --- Lifecycle -----------------------------------------------------------------------------

    async def start(self) -> None:
        """Start-up: the last refresh's start, for the throttle, and the setting as it is."""
        text = await self.services.store.fetchval("SELECT MAX(started_at) FROM catalog_refreshes")
        if text:
            self._last_started_at = parse_iso(text)
        self._auto_track_owned = bool(await self.services.settings.get_value("auto_track_owned"))

    async def _run_queued(self, trigger: RefreshTrigger) -> None:
        if await self._run_is_active():
            log.info("catalog: no %s refresh during a run", trigger)
            return
        if trigger == "page_open" and self._throttled():
            return  # a refresh ran since this one was asked for
        await self.refresh(trigger=trigger)

    def _throttled(self) -> bool:
        if self._last_started_at is None:
            return False
        since = (self.services.clock.now() - self._last_started_at).total_seconds()
        return since < THROTTLE_S

    async def _run_is_active(self) -> bool:
        row = await self.services.store.fetchone(
            "SELECT 1 FROM runs WHERE kind = 'run' AND state <> 'ended' LIMIT 1"
        )
        return row is not None

    # --- One refresh ---------------------------------------------------------------------------

    async def _refresh(self, trigger: RefreshTrigger, run_id: int | None) -> RefreshResult:
        services = self.services
        auth = await services.auth.load()
        state = auth.state(services.clock.now())
        # Only what refuses every request skips it (tokens.py). Past `expires_at` by the date
        # alone, the token may still work: Spotify's invalid_grant decides.
        if state in ("not_configured", "disconnected") or auth.invalid_grant_at is not None:
            log.info(
                "catalog: %s refresh skipped, the Web API isn't connected (%s)", trigger, state
            )
            return RefreshResult(
                None,
                "skipped",
                0,
                0,
                0,
                _NO_API,
                error=f"connection {state}",
                snapshots_unread=await self._snapshots_unread(set()),
            )

        started = services.clock.now()
        refresh_id = await self._insert_row(trigger, run_id, started)
        self._last_started_at = started
        progress = _Progress(refresh_id=refresh_id, scope=ApiScope("refresh", refresh_id))
        log.info("catalog: refresh %d started (%s)", refresh_id, trigger)
        try:
            await self._fetch_everything(progress, auth.user_id, trigger)
        except (NotConnected, ConnectionExpired) as exc:
            progress.listing_failed = True
            progress.note_error(_message(exc))
            log.warning("catalog: refresh %d stopped: %s", refresh_id, _message(exc))
        except Exception as exc:
            # A bug or a database error: the row is closed as failed, and the caller sees it.
            progress.listing_failed = True
            progress.note_error(f"internal error: {type(exc).__name__}")
            await self._finish(progress, _NO_API)
            raise

        api = await self._finish_scope(progress.scope)
        result = await self._finish(progress, api)
        for item_id in sorted(progress.changed):
            await services.library.publish(item_id)
        await self._update_backlog()
        return result

    async def _fetch_everything(
        self, progress: _Progress, user_id: str | None, trigger: RefreshTrigger
    ) -> None:
        """Steps 2 to 5 of the module docstring. Raises NotConnected or ConnectionExpired."""
        try:
            if user_id is None:
                user = await self.services.ports.webapi.me(scope=progress.scope)
                user_id = user.id
                await self.services.auth.set_account(user)
            if await self._ensure_liked(user_id):
                progress.changed.add(LIKED_ID)
            playlists = await self._list_playlists(progress.scope)
        except (NotConnected, ConnectionExpired):
            raise
        except WebApiError as exc:
            progress.listing_failed = True
            progress.note_error(_message(exc))
            log.warning("catalog: the playlist listing failed: %s", _message(exc))
            return

        auto_track = bool(await self.services.settings.get_value("auto_track_owned"))
        now = iso_ms(self.services.clock.now())

        def apply(conn: sqlite3.Connection) -> _Listing:
            return _apply_listing(
                conn,
                playlists,
                user_id=user_id,
                auto_track=auto_track,
                now=now,
                refresh_id=progress.refresh_id,
            )

        listing = await self.services.store.transaction(apply)
        progress.changed |= listing.changed
        progress.snapshots_read.update(playlist.id for playlist in playlists)
        self._remember_preview_covers(playlists, user_id)
        await self._save_covers(progress, listing.covers)

        try:
            if trigger == "run":
                # First: cheap, and D13 needs them to plan the run.
                await self._read_linked(progress)
            for item_id, snapshot_id in listing.to_fetch:
                await self._fetch_list_safely(progress, item_id, snapshot_id)
            await self._fetch_liked_safely(progress)
        except _StopTrackLists:
            pass

    async def _list_playlists(self, scope: ApiScope) -> list[Playlist]:
        """Every page of GET /me/playlists."""
        webapi = self.services.ports.webapi
        playlists: list[Playlist] = []
        offset = 0
        while True:
            page = await webapi.my_playlists(offset=offset, limit=PAGE_LIMIT, scope=scope)
            playlists.extend(page.items)
            if page.next_offset is None or page.next_offset <= offset:
                return playlists
            offset = page.next_offset

    async def _ensure_liked(self, user_id: str) -> bool:
        """Makes the Liked Songs item if it isn't there yet, tracked when `auto_track_owned` is
        on (step 2). True when it was made."""
        uri = f"spotify:user:{user_id}:collection"
        now = iso_ms(self.services.clock.now())
        tracked = 1 if await self.services.settings.get_value("auto_track_owned") else 0

        def ensure(conn: sqlite3.Connection) -> bool:
            row = conn.execute("SELECT uri FROM items WHERE id = ?", (LIKED_ID,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO items (id, kind, uri, name, tracked, added_by, added_at, "
                    "item_access, cover_source) VALUES (?, 'liked', ?, ?, ?, 'auto', ?, 1, 'none')",
                    (LIKED_ID, uri, LIKED_NAME, tracked, now),
                )
                return True
            if row["uri"] != uri:
                conn.execute("UPDATE items SET uri = ? WHERE id = ?", (uri, LIKED_ID))
            return False

        return await self.services.store.transaction(ensure)

    async def _auth_changed(self, change: AuthChange) -> None:
        """An AuthStore listener: once step 5 stores the account, Liked Songs exists, so step 7's
        "Include Liked Songs" (PATCH /api/library/liked) works before the first refresh ends. No
        event here: the setup refresh that follows publishes it with its track list."""
        if change != "account":
            return
        row = await self.services.auth.load()
        if row.user_id is not None:
            await self._ensure_liked(row.user_id)

    def _remember_preview_covers(self, playlists: Sequence[Playlist], user_id: str) -> None:
        now = self.services.clock.now()
        for playlist in playlists:
            if playlist.owner_id == user_id:
                continue
            url = preview_image(playlist.images)
            if url is None:
                self._preview_covers.pop(playlist.id, None)
            else:
                self._preview_covers[playlist.id] = (url, now)

    async def _save_covers(
        self, progress: _Progress, covers: Sequence[tuple[str, tuple[Image, ...]]]
    ) -> None:
        for item_id, images in covers:
            if await self._save_cover(progress, item_id, images):
                progress.changed.add(item_id)

    async def _save_cover(self, progress: _Progress, item_id: str, images: Sequence[Image]) -> bool:
        """Passes the images to the cover cache. True when a new cover was saved."""
        try:
            update = await self.services.covers.update(item_id, images)
        except Exception:
            log.warning("covers: updating %s's cover failed", item_id, exc_info=True)
            return False
        if update.outcome == "fallback":
            progress.covers_fallback += 1
        if update.outcome in ("saved", "fallback"):
            progress.covers_saved += 1
            return True
        return False

    # --- Track lists ---------------------------------------------------------------------------

    async def _fetch_list_safely(
        self, progress: _Progress, item_id: str, snapshot_id: str | None
    ) -> None:
        try:
            if await self._fetch_playlist(item_id, snapshot_id, progress.scope):
                progress.changed.add(item_id)
        except (NotConnected, ConnectionExpired):
            raise
        except (RateLimited, SpotifyUnavailable) as exc:
            self._item_failed(progress, item_id, exc)
            raise _StopTrackLists from exc
        except WebApiError as exc:
            self._item_failed(progress, item_id, exc)

    async def _fetch_liked_safely(self, progress: _Progress) -> None:
        try:
            if await self._fetch_liked(progress.scope):
                progress.changed.add(LIKED_ID)
        except (NotConnected, ConnectionExpired):
            raise
        except (RateLimited, SpotifyUnavailable) as exc:
            self._item_failed(progress, LIKED_ID, exc)
            raise _StopTrackLists from exc
        except WebApiError as exc:
            self._item_failed(progress, LIKED_ID, exc)

    def _item_failed(self, progress: _Progress, item_id: str, exc: WebApiError) -> None:
        progress.failed_items += 1
        progress.note_error(_message(exc))
        log.warning("catalog: %s's track list couldn't be read: %s", item_id, _message(exc))

    async def _fetch_playlist(self, item_id: str, snapshot_id: str | None, scope: ApiScope) -> bool:
        """GET /playlists/{id}/items, every page, stored. True when the item changed."""
        webapi = self.services.ports.webapi
        entries: list[ListedTrack] = []
        offset = 0
        try:
            while True:
                page = await webapi.playlist_items(
                    item_id, offset=offset, limit=PAGE_LIMIT, scope=scope
                )
                entries.extend(ListedTrack(e.track, e.added_at) for e in page.items)
                if page.next_offset is None or page.next_offset <= offset:
                    break
                offset = page.next_offset
        except NoAccess:
            log.info("catalog: %s answers 403, so it has no item access", item_id)
            return await self._lose_item_access(item_id, snapshot_id)
        except NotFound:
            return await self._mark_unavailable(item_id, "deleted")
        return await self._store_list(item_id, entries, snapshot_id=snapshot_id)

    async def _fetch_liked(self, scope: ApiScope) -> bool:
        """Liked Songs, incrementally (step 4). True when its list changed."""
        store = self.services.store
        row = await store.fetchone(
            "SELECT tracked, catalog_fetched_at, liked_newest_added_at FROM items "
            "WHERE id = ? AND removed_at IS NULL",
            (LIKED_ID,),
        )
        if row is None or not row["tracked"]:
            return False
        stored = await store.fetchall(
            "SELECT track_id FROM item_tracks WHERE item_id = ? ORDER BY position", (LIKED_ID,)
        )
        known = {r["track_id"] for r in stored if r["track_id"] is not None}
        newest = _parse_time(row["liked_newest_added_at"])
        incremental = row["catalog_fetched_at"] is not None and newest is not None and known

        webapi = self.services.ports.webapi
        read: list[SavedTrack] = []  # every entry of every page read, newest first
        new_count = 0  # how many entries come before the first known one
        reached = False
        offset = 0
        total = 0
        next_offset: int | None = None
        while True:
            page = await webapi.saved_tracks(offset=offset, limit=PAGE_LIMIT, scope=scope)
            total = page.total
            for saved in page.items:
                if incremental and not reached and _known_liked(saved, known, newest):
                    reached = True
                if not reached:
                    new_count += 1
            read.extend(page.items)
            next_offset = page.next_offset
            if reached or next_offset is None or next_offset <= offset:
                break
            offset = next_offset

        if reached and new_count + len(stored) == total:
            if new_count == 0:
                return False  # nothing changed: one request
            new = [ListedTrack(s.track, s.added_at) for s in read[:new_count]]
            return await self._store_list(LIKED_ID, new, keep_stored=True)

        if reached:
            # The counts differ: a track was removed (or liked again). Read the rest of the
            # list after the pages already read, then store it whole.
            log.info("catalog: Liked Songs' total changed, reading the whole list")
            while next_offset is not None and next_offset > offset:
                offset = next_offset
                page = await webapi.saved_tracks(offset=offset, limit=PAGE_LIMIT, scope=scope)
                read.extend(page.items)
                next_offset = page.next_offset
        whole = [ListedTrack(s.track, s.added_at) for s in read]
        return await self._store_list(LIKED_ID, whole)

    async def _store_list(
        self,
        item_id: str,
        entries: Sequence[ListedTrack],
        *,
        snapshot_id: str | None = None,
        keep_stored: bool = False,
    ) -> bool:
        """Stores a track list (`keep_stored`: these entries go before the stored ones) and
        updates the item's row. True when the list differs from the stored one."""
        now = iso_ms(self.services.clock.now())

        def save(conn: sqlite3.Connection) -> bool:
            old_list = _list_signature(conn, item_id)
            listed = list(entries)
            if keep_stored:
                listed += stored_entries(conn, item_id)
            summary = replace_item_tracks(conn, item_id, listed, now)
            new_list = _list_signature(conn, item_id)
            old_ids = {track_id for track_id, _ in old_list if track_id is not None}
            appeared = any(track_id not in old_ids for track_id, _ in new_list if track_id)
            newest = listed[0].added_at if item_id == LIKED_ID and listed else None
            conn.execute(
                "UPDATE items SET total = ?, catalog_fetched_at = ?, item_access = 1, "
                "snapshot_id = CASE WHEN kind = 'liked' THEN NULL ELSE ? END, "
                "liked_newest_added_at = CASE WHEN kind = 'liked' THEN ? "
                "ELSE liked_newest_added_at END, "
                "changed_at = CASE WHEN ? THEN ? ELSE changed_at END, "
                "unavailable_at = NULL, unavailable_reason = NULL WHERE id = ?",
                (summary.playable, now, snapshot_id, newest, appeared, now, item_id),
            )
            return old_list != new_list

        return await self.services.store.transaction(save)

    async def _lose_item_access(self, item_id: str, snapshot_id: str | None) -> bool:
        """A 403 on the items: from now on it's like any followed playlist without item access,
        its snapshot_id current (D13) and its total the listing's."""

        def lose(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE items SET item_access = 0, snapshot_id = ?, "
                "total = coalesce((SELECT total FROM followed_playlists WHERE id = ?), total) "
                "WHERE id = ? AND item_access = 1",
                (snapshot_id, item_id, item_id),
            )
            return cur.rowcount > 0

        return await self.services.store.transaction(lose)

    async def _mark_unavailable(self, item_id: str, reason: str) -> bool:
        now = iso_ms(self.services.clock.now())
        log.info("catalog: %s is unavailable (%s)", item_id, reason)

        def mark(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE items SET unavailable_at = ?, unavailable_reason = ? "
                "WHERE id = ? AND unavailable_at IS NULL",
                (now, reason, item_id),
            )
            return cur.rowcount > 0

        return await self.services.store.transaction(mark)

    # --- Linked playlists (a run's own refresh) ------------------------------------------------

    async def _read_linked(self, progress: _Progress) -> None:
        rows = await self.services.store.fetchall(
            "SELECT id FROM items WHERE kind = 'linked' AND tracked = 1 AND removed_at IS NULL "
            "ORDER BY added_at, id"
        )
        webapi = self.services.ports.webapi
        for row in rows:
            item_id = row["id"]
            try:
                playlist = await webapi.playlist(item_id, scope=progress.scope)
            except NotFound:
                progress.snapshots_read.add(item_id)  # checked: it's gone
                if await self._mark_unavailable(item_id, "deleted"):
                    progress.changed.add(item_id)
                continue
            except NoAccess:
                progress.snapshots_read.add(item_id)  # checked: it's private now
                if await self._mark_unavailable(item_id, "private"):
                    progress.changed.add(item_id)
                continue
            except (NotConnected, ConnectionExpired):
                raise
            except (RateLimited, SpotifyUnavailable) as exc:
                self._item_failed(progress, item_id, exc)
                raise _StopTrackLists from exc
            except WebApiError as exc:
                self._item_failed(progress, item_id, exc)
                continue
            if await self._update_linked(playlist):
                progress.changed.add(item_id)
            progress.snapshots_read.add(item_id)
            if await self._save_cover(progress, item_id, playlist.images):
                progress.changed.add(item_id)

    async def _update_linked(self, playlist: Playlist) -> bool:
        def update(conn: sqlite3.Connection) -> bool:
            before = conn.execute(
                "SELECT name, owner_id, owner_name, unavailable_at FROM items WHERE id = ?",
                (playlist.id,),
            ).fetchone()
            conn.execute(
                "UPDATE items SET uri = ?, name = ?, owner_id = ?, owner_name = ?, "
                "snapshot_id = ?, unavailable_at = NULL, unavailable_reason = NULL WHERE id = ?",
                (
                    playlist.uri,
                    playlist.name,
                    playlist.owner_id,
                    playlist.owner_name,
                    playlist.snapshot_id,
                    playlist.id,
                ),
            )
            if before is None:
                return False
            return (
                before["name"] != playlist.name
                or before["owner_id"] != playlist.owner_id
                or before["owner_name"] != playlist.owner_name
                or before["unavailable_at"] is not None
            )

        return await self.services.store.transaction(update)

    # --- The end -------------------------------------------------------------------------------

    async def _insert_row(self, trigger: RefreshTrigger, run_id: int | None, at: datetime) -> int:
        result = await self.services.store.execute(
            "INSERT INTO catalog_refreshes (trigger, run_id, started_at) VALUES (?, ?, ?)",
            (trigger, run_id, iso_ms(at)),
        )
        assert result.lastrowid is not None
        return result.lastrowid

    async def _finish_scope(self, scope: ApiScope) -> ScopeSummary:
        try:
            return await self.services.webapi_usage.finish_scope(scope)
        except Exception:
            log.warning("catalog: the Web API usage summary failed", exc_info=True)
            return _NO_API

    async def _snapshots_unread(self, read: set[str]) -> tuple[str, ...]:
        """The items without item access, tracked or not, whose snapshot_id isn't in `read`
        (step 6)."""
        rows = await self.services.store.fetchall(
            "SELECT id FROM items WHERE kind IN ('followed', 'linked') AND item_access = 0 "
            "AND removed_at IS NULL ORDER BY id"
        )
        return tuple(row["id"] for row in rows if row["id"] not in read)

    async def _finish(self, progress: _Progress, api: ScopeSummary) -> RefreshResult:
        if progress.listing_failed:
            outcome: RefreshOutcome = "failed"
        elif progress.failed_items:
            outcome = "partial"
        else:
            outcome = "ok"
        await self.services.store.execute(
            "UPDATE catalog_refreshes SET finished_at = ?, outcome = ?, items_changed = ?, "
            "covers_saved = ?, covers_fallback = ?, api_requests = ?, api_retried = ?, "
            "api_rate_limited = ?, error = ? WHERE id = ?",
            (
                iso_ms(self.services.clock.now()),
                outcome,
                len(progress.changed),
                progress.covers_saved,
                progress.covers_fallback,
                api.requests,
                api.retried,
                api.rate_limited,
                progress.error,
                progress.refresh_id,
            ),
        )
        if progress.changed:
            log.info("Catalog: %d changed", len(progress.changed))
        if progress.covers_saved:
            log.info(
                "Covers: %d saved · %d at the size returned",
                progress.covers_saved,
                progress.covers_fallback,
            )
        log.info("catalog: refresh %d ended %s", progress.refresh_id, outcome)
        return RefreshResult(
            refresh_id=progress.refresh_id,
            outcome=outcome,
            items_changed=len(progress.changed),
            covers_saved=progress.covers_saved,
            covers_fallback=progress.covers_fallback,
            api=api,
            error=progress.error,
            snapshots_unread=await self._snapshots_unread(progress.snapshots_read),
        )

    async def _update_backlog(self) -> None:
        try:
            await self.services.backlog.update()
        except Exception:
            log.warning("catalog: the backlog estimate couldn't be updated", exc_info=True)

    # --- auto_track_owned ----------------------------------------------------------------------

    async def _settings_saved(self, keys: frozenset[str]) -> None:
        if "auto_track_owned" not in keys:
            return
        value = bool(await self.services.settings.get_value("auto_track_owned"))
        if value == self._auto_track_owned:
            return
        self._auto_track_owned = value
        if value:
            sql = (
                "UPDATE items SET tracked = 1 WHERE kind = 'owned' AND tracked = 0 "
                "AND removed_at IS NULL RETURNING id"
            )
        elif not await self.services.setup.is_complete():
            sql = (
                "UPDATE items SET tracked = 0 WHERE tracked = 1 AND removed_at IS NULL "
                "AND ((kind = 'owned' AND added_by = 'auto') OR kind = 'liked') RETURNING id"
            )
        else:
            return  # turned off after setup: only new playlists stop being tracked

        def change(conn: sqlite3.Connection) -> list[str]:
            return [row["id"] for row in conn.execute(sql).fetchall()]

        changed = await self.services.store.transaction(change)
        log.info(
            "catalog: auto-tracking turned %s; %d items %s",
            "on" if value else "off",
            len(changed),
            "tracked" if value else "untracked",
        )
        if not changed:
            return
        for item_id in sorted(changed):
            await self.services.library.publish(item_id)
        if value:
            self.request_refresh("item_added")  # their track lists
        await self._update_backlog()


# --- On the database thread ---------------------------------------------------------------------


def _apply_listing(
    conn: sqlite3.Connection,
    playlists: Sequence[Playlist],
    *,
    user_id: str,
    auto_track: bool,
    now: str,
    refresh_id: int,
) -> _Listing:
    """Step 3: GET /me/playlists into `items` and `followed_playlists`, in one transaction.
    Returns what changed, the covers to pass on, and the track lists to fetch."""
    result = _Listing()
    rows = {
        row["id"]: row
        for row in conn.execute("SELECT * FROM items WHERE kind <> 'album'").fetchall()
    }
    conn.execute("DELETE FROM followed_playlists")
    listed: set[str] = set()
    for order, playlist in enumerate(playlists):
        if playlist.id in listed:
            continue
        listed.add(playlist.id)
        owned = playlist.owner_id == user_id
        if not owned:
            conn.execute(
                "INSERT INTO followed_playlists (id, uri, name, owner_id, owner_name, "
                "collaborative, total, snapshot_id, listed_order, refresh_id, seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    playlist.id,
                    playlist.uri,
                    playlist.name,
                    playlist.owner_id,
                    playlist.owner_name,
                    1 if playlist.collaborative else 0,
                    playlist.total,
                    playlist.snapshot_id,
                    order,
                    refresh_id,
                    now,
                ),
            )
        row = rows.get(playlist.id)
        if row is None:
            if owned:
                _insert_owned(conn, playlist, tracked=auto_track, now=now, result=result)
            continue
        if row["removed_at"] is not None:
            continue  # removed from the Library: a listing doesn't bring it back
        _update_listed(conn, row, playlist, owned=owned, result=result)

    # Owned and followed items the listing no longer has.
    for item_id, row in rows.items():
        if item_id in listed or row["removed_at"] is not None:
            continue
        if row["kind"] not in ("owned", "followed") or row["unavailable_at"] is not None:
            continue
        reason = "deleted" if row["kind"] == "owned" else "unfollowed"
        conn.execute(
            "UPDATE items SET unavailable_at = ?, unavailable_reason = ? WHERE id = ?",
            (now, reason, item_id),
        )
        result.changed.add(item_id)
    return result


def _insert_owned(
    conn: sqlite3.Connection, playlist: Playlist, *, tracked: bool, now: str, result: _Listing
) -> None:
    cur = conn.execute(
        "INSERT INTO items (id, kind, uri, name, owner_id, owner_name, tracked, added_by, "
        "added_at, item_access, total, cover_source) "
        "VALUES (?, 'owned', ?, ?, ?, ?, ?, 'auto', ?, 1, ?, 'none') "
        "ON CONFLICT (id) DO NOTHING",
        (
            playlist.id,
            playlist.uri,
            playlist.name,
            playlist.owner_id,
            playlist.owner_name,
            1 if tracked else 0,
            now,
            playlist.total,
        ),
    )
    if cur.rowcount == 0:
        return  # an album with the same id, in theory
    result.changed.add(playlist.id)
    result.covers.append((playlist.id, playlist.images))
    if tracked:
        result.to_fetch.append((playlist.id, playlist.snapshot_id))


def _update_listed(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    playlist: Playlist,
    *,
    owned: bool,
    result: _Listing,
) -> None:
    """A Library item the listing has: its facts kept current, its cover and track list queued."""
    kind = row["kind"]
    item_access = row["item_access"]
    if kind == "linked" and not owned:
        # A linked playlist you've since followed: it's a followed one now, with item access if
        # you collaborate on it.
        kind = "followed"
        item_access = 1 if playlist.collaborative else 0
    if item_access:
        # The stored snapshot_id belongs to the stored track list; the list sets both together.
        # Until it's fetched, the total is the listing's.
        snapshot_id = row["snapshot_id"]
        total = row["total"] if row["catalog_fetched_at"] is not None else playlist.total
    else:
        snapshot_id = playlist.snapshot_id  # D13 compares it with the last full pass
        total = playlist.total
    conn.execute(
        "UPDATE items SET kind = ?, uri = ?, name = ?, owner_id = ?, owner_name = ?, "
        "item_access = ?, snapshot_id = ?, total = ?, unavailable_at = NULL, "
        "unavailable_reason = NULL WHERE id = ?",
        (
            kind,
            playlist.uri,
            playlist.name,
            playlist.owner_id,
            playlist.owner_name,
            item_access,
            snapshot_id,
            total,
            row["id"],
        ),
    )
    if (
        kind != row["kind"]
        or playlist.name != row["name"]
        or playlist.owner_id != row["owner_id"]
        or playlist.owner_name != row["owner_name"]
        or item_access != row["item_access"]
        or total != row["total"]
        or row["unavailable_at"] is not None
    ):
        result.changed.add(row["id"])
    result.covers.append((row["id"], playlist.images))
    needs_list = row["catalog_fetched_at"] is None or row["snapshot_id"] != playlist.snapshot_id
    if row["tracked"] and item_access and needs_list:
        result.to_fetch.append((row["id"], playlist.snapshot_id))


def stored_entries(conn: sqlite3.Connection, item_id: str) -> list[ListedTrack]:
    """An item's stored track list as ListedTracks again, so new entries can be put before it
    (Liked Songs). Entries keep why they can't be recorded."""
    rows = conn.execute(
        "SELECT it.track_id, it.unplayable_reason, it.added_at, t.uri, t.name, t.artists, "
        "t.album_id, t.album_name, t.track_number, t.disc_number, t.duration_ms "
        "FROM item_tracks it LEFT JOIN tracks t ON t.id = it.track_id "
        "WHERE it.item_id = ? ORDER BY it.position",
        (item_id,),
    ).fetchall()
    entries = []
    for row in rows:
        reason = row["unplayable_reason"]
        if reason == "local":
            track: Track | None = Track(
                id=None,
                uri="",
                name="",
                artists=(),
                album_id=None,
                album_name=None,
                track_number=None,
                disc_number=None,
                duration_ms=0,
                is_local=True,
                is_playable=None,
                is_episode=False,
            )
        elif row["track_id"] is None or row["uri"] is None:
            track = None
        else:
            track = Track(
                id=row["track_id"],
                uri=row["uri"],
                name=row["name"],
                artists=tuple(_json_list(row["artists"])),
                album_id=row["album_id"],
                album_name=row["album_name"],
                track_number=row["track_number"],
                disc_number=row["disc_number"],
                duration_ms=row["duration_ms"],
                is_local=False,
                is_playable=False if reason == "not_playable" else True,
                is_episode=reason == "episode",
            )
        entries.append(ListedTrack(track, row["added_at"]))
    return entries


def _list_signature(conn: sqlite3.Connection, item_id: str) -> list[tuple[str | None, int]]:
    """The stored list as (track id, playable) pairs in order, to tell whether it changed."""
    rows = conn.execute(
        "SELECT track_id, playable FROM item_tracks WHERE item_id = ? ORDER BY position",
        (item_id,),
    ).fetchall()
    return [(row["track_id"], row["playable"]) for row in rows]


# --- Small helpers ------------------------------------------------------------------------------


def preview_image(images: Sequence[Image]) -> str | None:
    """The image to show in a preview row: the 300 px one if listed, else the first."""
    for image in images:
        if image.width == 300:
            return image.url
    return images[0].url if images else None


def _known_liked(saved: SavedTrack, known: set[str], newest: datetime | None) -> bool:
    """A Liked Songs entry that's already stored: the incremental read stops there."""
    if newest is None or saved.track.id is None or saved.track.id not in known:
        return False
    added = _parse_time(saved.added_at)
    return added is not None and added <= newest


def _parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return parse_iso(text)
    except ValueError:
        return None


def _json_list(text: str | None) -> list[str]:
    if not text:
        return []
    value = json.loads(text)
    return [str(v) for v in value] if isinstance(value, list) else []


def _message(exc: Exception) -> str:
    """An error's message for the log and `catalog_refreshes.error`, with any token masked."""
    return redact(str(exc) or type(exc).__name__)
