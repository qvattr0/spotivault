"""catalog/refresh.py on the fake Web API: what a refresh asks for, what it stores, and when it
runs. The same request counts on the real port and the mock Spotify are in
test_catalog_refresh_mock.py.

The fixtures library (fake/catalog.py): 17 owned playlists, one followed (Playlist 1, 35
entries, 403 on its items), 277 Liked Songs, and two linked playlists reachable by link.
"""

import dataclasses
import math
from collections import Counter
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from contract import assert_schema
from spotivault.catalog.refresh import LIKED_ID, THROTTLE_S
from spotivault.clock import iso_ms
from spotivault.fake.catalog import Catalog, Entry
from spotivault.fake.clock import FakeClock
from spotivault.fake.world import FakeWorld, world_of
from spotivault.ports import (
    ApiScope,
    NoAccess,
    NotFound,
    RateLimited,
    SpotifyUnavailable,
    TokenGrant,
    WebApiError,
)
from spotivault.services import Services

CLIENT_ID = "0123456789abcdef0123456789abcdef"
GRANT = TokenGrant(access_token="t" * 10, refresh_token="r" * 10, expires_in_s=3600, scopes=())

FOLLOWED = "a9poFNKiHX6sRmXWJ3e0mn"  # Playlist 1: 35 entries, 403 on its items
PLAYLIST_3 = "BcBk6G1xxldO5YUpUExUnE"  # 16 entries: a local file, an episode, an empty one
PLAYLIST_4 = "Vv5XOfWNU29YOsK88b8Lig"  # 84 entries, two pages
PLAYLIST_7 = "7aUxnM625jyHAtd7b7xZLg"  # 300 entries, 20 of them unplayable
LINKED = "gT7JiQHe0CjfUwwctmONus"  # Linked Mix: 20 entries, not in /me/playlists

LISTING = "GET /me/playlists"
ITEMS = "GET /playlists/{id}/items"
LIKED = "GET /me/tracks"
PLAYLIST = "GET /playlists/{id}"


def warm(catalog: Catalog) -> None:
    """Builds every lazily made entry now, outside the test's event loop: making thousands of
    them in one go would block the loop past the 100 ms the tests allow."""
    for item in catalog.playlists.values():
        _ = item.entries
    _ = catalog.liked


@pytest.fixture
def world(services: Services) -> FakeWorld:
    world = world_of(services.ports)
    warm(world.catalog)
    return world


async def connect_fake(services: Services, world: FakeWorld, *, account: bool = True) -> None:
    """A stored connection, as wizard step 5 leaves it. The fake Web API follows it."""
    await services.auth.set_client_id(CLIENT_ID)
    await services.auth.save_grant(CLIENT_ID, GRANT)
    if account:
        await services.auth.set_account(world.catalog.user)


@pytest.fixture
async def connected(running_app: FastAPI, services: Services, world: FakeWorld) -> FakeWorld:
    await connect_fake(services, world)
    world.webapi.calls.clear()
    return world


def owned_ids(catalog: Catalog) -> list[str]:
    return [p.playlist.id for p in catalog.library_playlists() if p.access == "owned"]


def pages(count: int) -> int:
    return max(1, math.ceil(count / 50))


async def item_row(services: Services, item_id: str) -> Any:
    return await services.store.fetchone("SELECT * FROM items WHERE id = ?", (item_id,))


async def list_ids(services: Services, item_id: str) -> list[str | None]:
    rows = await services.store.fetchall(
        "SELECT track_id FROM item_tracks WHERE item_id = ? ORDER BY position", (item_id,)
    )
    return [row["track_id"] for row in rows]


def fail_once(world: FakeWorld, method: str, error: Exception) -> None:
    """The fake Web API's next `method` call raises `error` (after it's recorded, as a real
    request would be)."""
    original: Callable[..., Any] = getattr(world.webapi, method)
    left = [1]

    async def failing(*args: Any, **kwargs: Any) -> Any:
        answer = await original(*args, **kwargs)
        if left[0]:
            left[0] -= 1
            raise error
        return answer

    setattr(world.webapi, method, failing)


def fail_always(world: FakeWorld, method: str, error: Exception, ident: str) -> None:
    """The fake Web API's `method` raises `error` for this playlist id from now on."""
    original: Callable[..., Any] = getattr(world.webapi, method)

    async def failing(*args: Any, **kwargs: Any) -> Any:
        answer = await original(*args, **kwargs)
        if args and args[0] == ident:
            raise error
        return answer

    setattr(world.webapi, method, failing)


async def add_run(services: Services, *, state: str = "running") -> int:
    now = iso_ms(services.clock.now())
    outcome = "completed" if state == "ended" else None
    result = await services.store.execute(
        "INSERT INTO runs (kind, trigger, state, outcome, started_at, ended_at) "
        "VALUES ('run', 'run_now', ?, ?, ?, ?)",
        (state, outcome, now, now if outcome else None),
    )
    assert result.lastrowid is not None
    return result.lastrowid


async def complete_setup(services: Services) -> None:
    now = iso_ms(services.clock.now())
    await services.store.execute(
        "INSERT INTO meta (key, value, updated_at) VALUES ('setup_completed_at', ?, ?)",
        (now, now),
    )


# --- A first refresh ----------------------------------------------------------------------------


async def test_a_first_refresh_fetches_every_tracked_list(
    services: Services, connected: FakeWorld
) -> None:
    catalog = connected.catalog
    result = await services.catalog.refresh(trigger="setup")

    assert result.outcome == "ok" and result.error is None
    assert result.refresh_id is not None
    calls = Counter(connected.webapi.endpoints())
    owned = owned_ids(catalog)
    assert len(owned) == 17
    assert calls == {
        LISTING: 1,
        ITEMS: sum(pages(len(catalog.playlists[i].entries)) for i in owned),
        LIKED: pages(277),
    }
    scope = ApiScope("refresh", result.refresh_id)
    assert {call.scope for call in connected.webapi.calls} == {scope}

    rows = await services.store.fetchall(
        "SELECT kind, COUNT(*) AS n, SUM(tracked) AS tracked FROM items GROUP BY kind"
    )
    assert {r["kind"]: (r["n"], r["tracked"]) for r in rows} == {
        "liked": (1, 1),
        "owned": (17, 17),
    }
    followed = await services.store.fetchall("SELECT * FROM followed_playlists")
    assert [(r["id"], r["total"], r["refresh_id"]) for r in followed] == [
        (FOLLOWED, 35, result.refresh_id)
    ]

    # Every list in Web API order, the total its playable entries.
    for item_id in owned:
        entries = catalog.playlists[item_id].entries
        row = await item_row(services, item_id)
        stored = await list_ids(services, item_id)
        assert len(stored) == len(entries), item_id
        assert row["snapshot_id"] == catalog.playlists[item_id].playlist.snapshot_id
        assert row["catalog_fetched_at"] is not None and row["changed_at"] is not None
    assert (await item_row(services, PLAYLIST_3))["total"] == 13  # local, episode, empty
    assert (await item_row(services, PLAYLIST_7))["total"] == 280  # 20 unplayable
    liked = await item_row(services, LIKED_ID)
    assert liked["uri"] == "spotify:user:user2:collection" and liked["name"] == "Liked Songs"
    assert liked["total"] == 277 and liked["cover_source"] == "none"
    assert liked["liked_newest_added_at"] == catalog.liked[0].added_at
    assert await list_ids(services, LIKED_ID) == [e.track.id for e in catalog.liked if e.track]

    row = await services.store.fetchone(
        "SELECT * FROM catalog_refreshes WHERE id = ?", (result.refresh_id,)
    )
    assert row["trigger"] == "setup" and row["outcome"] == "ok"
    assert row["finished_at"] is not None
    assert row["items_changed"] == result.items_changed == 18
    assert row["covers_saved"] == result.covers_saved == 17
    assert row["api_requests"] == 0  # the fake port writes no usage rows
    assert await services.catalog.last_refresh_at() is not None


async def test_a_refresh_with_nothing_changed_costs_two_requests(
    services: Services, connected: FakeWorld
) -> None:
    await services.catalog.refresh(trigger="setup")
    connected.webapi.calls.clear()
    fetched = (await item_row(services, PLAYLIST_4))["catalog_fetched_at"]

    result = await services.catalog.refresh(trigger="page_open")

    assert connected.webapi.endpoints() == [LISTING, LIKED]
    assert (result.outcome, result.items_changed, result.covers_saved) == ("ok", 0, 0)
    assert (await item_row(services, PLAYLIST_4))["catalog_fetched_at"] == fetched


async def test_a_changed_snapshot_refetches_only_that_playlist(
    services: Services, connected: FakeWorld, fake_clock: FakeClock
) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    before = await item_row(services, PLAYLIST_4)
    other = await item_row(services, PLAYLIST_7)
    connected.webapi.calls.clear()
    await fake_clock.advance(60)

    entries = catalog.playlists[PLAYLIST_4].entries[:10] + [catalog.entry("Brand New")]
    catalog.set_entries(PLAYLIST_4, entries)
    result = await services.catalog.refresh(trigger="page_open")

    assert connected.webapi.endpoints() == [LISTING, ITEMS, LIKED]
    assert result.items_changed == 1
    row = await item_row(services, PLAYLIST_4)
    assert row["total"] == 11
    assert row["snapshot_id"] == catalog.playlists[PLAYLIST_4].playlist.snapshot_id
    assert row["snapshot_id"] != before["snapshot_id"]
    assert row["changed_at"] > before["changed_at"]  # a new track appeared
    assert (await list_ids(services, PLAYLIST_4))[-1] == entries[-1].track.id
    assert (await item_row(services, PLAYLIST_7))["catalog_fetched_at"] == (
        other["catalog_fetched_at"]
    )


async def test_a_list_with_tracks_only_removed_keeps_its_changed_at(
    services: Services, connected: FakeWorld, fake_clock: FakeClock
) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    before = await item_row(services, PLAYLIST_4)
    await fake_clock.advance(60)
    catalog.set_entries(PLAYLIST_4, catalog.playlists[PLAYLIST_4].entries[:-5])

    result = await services.catalog.refresh(trigger="page_open")

    row = await item_row(services, PLAYLIST_4)
    assert result.items_changed == 1 and row["total"] == 79
    assert row["changed_at"] == before["changed_at"]


# --- Liked Songs --------------------------------------------------------------------------------


def liked_entry(catalog: Catalog, title: str, added_at: str) -> Entry:
    entry = catalog.entry(title, artist="Fresh Artist")
    entry.added_at = added_at
    return entry


async def test_liked_songs_stop_at_a_known_track(services: Services, connected: FakeWorld) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    connected.webapi.calls.clear()
    new = [liked_entry(catalog, f"Fresh {n}", f"2026-11-14T10:{n:02d}:00Z") for n in (2, 1)]
    catalog.liked[:0] = new

    result = await services.catalog.refresh(trigger="page_open")

    assert connected.webapi.endpoints() == [LISTING, LIKED]
    assert result.items_changed == 1
    stored = await list_ids(services, LIKED_ID)
    assert len(stored) == 279
    assert stored[:3] == [new[0].track.id, new[1].track.id, catalog.liked[2].track.id]
    row = await item_row(services, LIKED_ID)
    assert row["liked_newest_added_at"] == "2026-11-14T10:02:00Z"
    assert row["total"] == 279


async def test_liked_songs_read_more_pages_until_a_known_track(
    services: Services, connected: FakeWorld
) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    connected.webapi.calls.clear()
    new = [
        liked_entry(catalog, f"Fresh {n}", f"2026-11-14T{n // 60:02d}:{n % 60:02d}:00Z")
        for n in range(60, 0, -1)
    ]
    catalog.liked[:0] = new

    await services.catalog.refresh(trigger="page_open")

    assert connected.webapi.endpoints() == [LISTING, LIKED, LIKED]
    stored = await list_ids(services, LIKED_ID)
    assert len(stored) == 337
    assert stored == [e.track.id for e in catalog.liked]


@pytest.mark.parametrize("change", ["removed", "removed_and_added", "liked_again"])
async def test_liked_songs_total_mismatch_reads_the_whole_list(
    services: Services, connected: FakeWorld, change: str
) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    connected.webapi.calls.clear()
    if change in ("removed", "removed_and_added"):
        del catalog.liked[100]
    if change == "removed_and_added":
        catalog.liked.insert(0, liked_entry(catalog, "Fresh", "2026-11-14T10:00:00Z"))
    if change == "liked_again":  # unliked, then liked again: it moves to the top
        entry = catalog.liked.pop(30)
        entry.added_at = "2026-11-14T10:00:00Z"
        catalog.liked.insert(0, entry)

    await services.catalog.refresh(trigger="page_open")

    # The first page, then the rest: the whole list once, no page twice.
    assert connected.webapi.endpoints() == [LISTING] + [LIKED] * pages(len(catalog.liked))
    assert await list_ids(services, LIKED_ID) == [e.track.id for e in catalog.liked]
    assert (await item_row(services, LIKED_ID))["total"] == len(catalog.liked)


async def test_untracked_liked_songs_are_not_read(services: Services, connected: FakeWorld) -> None:
    await services.catalog.refresh(trigger="setup")
    await services.library.set_tracked(LIKED_ID, False)
    await services.catalog.wait_idle()
    connected.webapi.calls.clear()

    await services.catalog.refresh(trigger="page_open")

    assert connected.webapi.endpoints() == [LISTING]


# --- Followed and linked playlists --------------------------------------------------------------


async def test_followed_playlists_keep_their_total_without_items(
    services: Services, connected: FakeWorld
) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    item = await services.library.add(f"spotify:playlist:{FOLLOWED}")
    assert (item.kind, item.item_access, item.total, item.new) == ("followed", False, 35, None)
    connected.webapi.calls.clear()

    entries = catalog.playlists[FOLLOWED].entries + [catalog.entry("One More")]
    catalog.set_entries(FOLLOWED, entries)
    result = await services.catalog.refresh(trigger="page_open")

    assert connected.webapi.endpoints() == [LISTING, LIKED]  # never its items
    assert result.items_changed == 1
    row = await item_row(services, FOLLOWED)
    assert (row["total"], row["item_access"]) == (36, 0)
    assert row["snapshot_id"] == catalog.playlists[FOLLOWED].playlist.snapshot_id  # D13
    assert row["catalog_fetched_at"] is None
    item = await services.library.item(FOLLOWED)
    assert item is not None and (item.total, item.recorded, item.new) == (36, 0, None)


async def test_linked_playlists_are_read_by_link_only_on_a_runs_refresh(
    services: Services, connected: FakeWorld
) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    item = await services.library.add(f"https://open.spotify.com/playlist/{LINKED}?si=x")
    assert (item.kind, item.item_access, item.total, item.name) == (
        "linked",
        False,
        None,
        "Linked Mix",
    )
    assert connected.webapi.endpoints()[-1] == PLAYLIST
    connected.webapi.calls.clear()

    catalog.set_entries(LINKED, catalog.playlists[LINKED].entries[:5])
    linked = catalog.playlists[LINKED]
    linked.playlist = dataclasses.replace(linked.playlist, name="Linked Mix II")
    page_open = await services.catalog.refresh(trigger="page_open")
    assert connected.webapi.endpoints() == [LISTING, LIKED]  # a page open never reads it
    assert (await item_row(services, LINKED))["name"] == "Linked Mix"
    assert page_open.snapshots_unread == (LINKED,)  # its snapshot_id may be stale

    connected.webapi.calls.clear()
    run_id = await add_run(services)
    result = await services.catalog.refresh(trigger="run", run_id=run_id)

    # A run's refresh reads it right after the listing, before any track list (D13).
    assert connected.webapi.endpoints() == [LISTING, PLAYLIST, LIKED]
    assert result.items_changed == 1
    assert result.snapshots_unread == ()
    row = await item_row(services, LINKED)
    assert row["name"] == "Linked Mix II"
    assert row["snapshot_id"] == linked.playlist.snapshot_id
    assert row["total"] is None and row["item_access"] == 0
    refresh = await services.store.fetchone(
        "SELECT trigger, run_id FROM catalog_refreshes WHERE id = ?", (result.refresh_id,)
    )
    assert (refresh["trigger"], refresh["run_id"]) == ("run", run_id)


async def test_a_linked_playlist_that_answers_404_or_403_is_unavailable(
    services: Services, connected: FakeWorld
) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    await services.library.add(f"spotify:playlist:{LINKED}")
    other = "EgRXcfrpIQQg4bVz2br5Tw"  # Friday Finds
    await services.library.add(f"spotify:playlist:{other}")
    del catalog.playlists[LINKED]  # deleted: 404
    fail_always(connected, "playlist", NoAccess("Forbidden", status=403), other)  # made private

    run_id = await add_run(services)
    result = await services.catalog.refresh(trigger="run", run_id=run_id)

    assert result.outcome == "ok"
    for item_id, reason in ((LINKED, "deleted"), (other, "private")):
        row = await item_row(services, item_id)
        assert row["unavailable_reason"] == reason and row["unavailable_at"] is not None
        item = await services.library.item(item_id)
        assert item is not None and item.status == "unavailable"


async def test_a_followed_playlist_you_collaborate_on_is_fetched_like_your_own(
    services: Services, connected: FakeWorld
) -> None:
    catalog = connected.catalog
    shared = catalog.add_playlist("Shared Songs", tracks=7, access="followed")
    shared.playlist = dataclasses.replace(shared.playlist, collaborative=True)
    shared.access = "collaborative"  # its items answer, though someone else owns it
    shared_id = shared.playlist.id
    await services.catalog.refresh(trigger="setup")
    assert await item_row(services, shared_id) is None  # followed: only a suggestion

    item = await services.library.add(f"spotify:playlist:{shared_id}")
    assert (item.kind, item.item_access, item.total) == ("followed", True, 7)
    assert len(await list_ids(services, shared_id)) == 7

    connected.webapi.calls.clear()
    catalog.set_entries(shared_id, shared.entries + [catalog.entry("Added By A Friend")])
    await services.catalog.refresh(trigger="page_open")
    assert connected.webapi.endpoints() == [LISTING, ITEMS, LIKED]
    assert (await item_row(services, shared_id))["total"] == 8

    # No longer a collaborator: 403. It loses item access and isn't asked again.
    shared.access = "followed"
    catalog.set_entries(shared_id, shared.entries[:3])
    connected.webapi.calls.clear()
    result = await services.catalog.refresh(trigger="page_open")
    assert connected.webapi.endpoints() == [LISTING, ITEMS, LIKED]
    assert result.outcome == "ok" and result.items_changed == 1
    row = await item_row(services, shared_id)
    assert row["item_access"] == 0 and row["total"] == 3
    item = await services.library.item(shared_id)
    assert item is not None and (item.item_access, item.total, item.new) == (False, 3, None)
    connected.webapi.calls.clear()
    await services.catalog.refresh(trigger="page_open")
    assert connected.webapi.endpoints() == [LISTING, LIKED]


# --- Unavailable --------------------------------------------------------------------------------


async def test_playlists_gone_from_the_listing_are_unavailable_until_back(
    services: Services, connected: FakeWorld
) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    await services.library.add(f"spotify:playlist:{FOLLOWED}")
    entries = await list_ids(services, PLAYLIST_4)
    catalog.playlists[PLAYLIST_4].in_library = False  # deleted
    catalog.playlists[FOLLOWED].in_library = False  # unfollowed

    result = await services.catalog.refresh(trigger="page_open")

    assert result.items_changed == 2
    assert (await item_row(services, PLAYLIST_4))["unavailable_reason"] == "deleted"
    assert (await item_row(services, FOLLOWED))["unavailable_reason"] == "unfollowed"
    assert await list_ids(services, PLAYLIST_4) == entries  # kept
    assert await services.store.fetchval("SELECT COUNT(*) FROM followed_playlists") == 0
    first = (await item_row(services, PLAYLIST_4))["unavailable_at"]

    await services.catalog.refresh(trigger="page_open")  # still gone: nothing changes
    assert (await item_row(services, PLAYLIST_4))["unavailable_at"] == first

    catalog.playlists[PLAYLIST_4].in_library = True
    catalog.playlists[FOLLOWED].in_library = True
    result = await services.catalog.refresh(trigger="page_open")
    assert result.items_changed == 2
    for item_id in (PLAYLIST_4, FOLLOWED):
        row = await item_row(services, item_id)
        assert row["unavailable_at"] is None and row["unavailable_reason"] is None


async def test_a_playlist_whose_items_answer_404_is_deleted(
    services: Services, connected: FakeWorld
) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    catalog.set_entries(PLAYLIST_4, catalog.playlists[PLAYLIST_4].entries[:3])
    fail_always(connected, "playlist_items", NotFound("Resource not found", status=404), PLAYLIST_4)

    result = await services.catalog.refresh(trigger="page_open")

    assert result.outcome == "ok" and result.items_changed == 1
    row = await item_row(services, PLAYLIST_4)
    assert row["unavailable_reason"] == "deleted" and row["total"] == 84


# --- Errors -------------------------------------------------------------------------------------


async def test_rate_limiting_stops_the_track_lists_and_ends_partial(
    services: Services, connected: FakeWorld
) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    for item_id in (PLAYLIST_3, PLAYLIST_4):
        catalog.set_entries(item_id, catalog.playlists[item_id].entries[:2])
    connected.webapi.calls.clear()
    fail_once(connected, "playlist_items", RateLimited("429", retry_after_s=600))

    result = await services.catalog.refresh(trigger="page_open")

    assert result.outcome == "partial"
    assert result.error is not None and "429" in result.error
    assert connected.webapi.endpoints() == [LISTING, ITEMS]  # nothing after the 429
    row = await services.store.fetchone(
        "SELECT outcome, error FROM catalog_refreshes WHERE id = ?", (result.refresh_id,)
    )
    assert (row["outcome"], row["error"]) == ("partial", result.error)

    # The next refresh picks up what was left.
    connected.webapi.calls.clear()
    result = await services.catalog.refresh(trigger="page_open")
    assert result.outcome == "ok"
    assert Counter(connected.webapi.endpoints()) == {LISTING: 1, ITEMS: 2, LIKED: 1}
    for item_id in (PLAYLIST_3, PLAYLIST_4):
        assert (await item_row(services, item_id))["total"] is not None
        assert len(await list_ids(services, item_id)) == 2


async def test_another_error_fails_that_item_only(services: Services, connected: FakeWorld) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    for item_id in (PLAYLIST_3, PLAYLIST_4):
        catalog.set_entries(item_id, catalog.playlists[item_id].entries[:2])
    fail_always(connected, "playlist_items", WebApiError("Bad request", status=400), PLAYLIST_4)
    result = await services.catalog.refresh(trigger="page_open")

    assert result.outcome == "partial"
    assert len(await list_ids(services, PLAYLIST_3)) == 2
    assert len(await list_ids(services, PLAYLIST_4)) == 84  # the old list stays


async def test_a_failed_listing_fails_the_refresh_and_changes_nothing(
    services: Services, connected: FakeWorld
) -> None:
    await services.catalog.refresh(trigger="setup")
    connected.webapi.failures.append(SpotifyUnavailable("Spotify didn't answer", status=503))

    result = await services.catalog.refresh(trigger="page_open")

    assert result.outcome == "failed" and result.items_changed == 0
    assert connected.webapi.endpoints()[-1] == LISTING
    assert (
        await services.store.fetchval("SELECT COUNT(*) FROM items WHERE unavailable_at IS NOT NULL")
        == 0
    )
    assert await services.store.fetchval("SELECT COUNT(*) FROM followed_playlists") == 1


async def test_an_expired_connection_fails_the_refresh_then_skips_the_next(
    services: Services, connected: FakeWorld
) -> None:
    connected.webapi.expired = True  # Spotify answers invalid_grant
    result = await services.catalog.refresh(trigger="setup")
    assert result.outcome == "failed" and result.refresh_id is not None

    again = await services.catalog.refresh(trigger="page_open")
    assert (again.outcome, again.refresh_id) == ("skipped", None)
    assert await services.store.fetchval("SELECT COUNT(*) FROM catalog_refreshes") == 1


async def test_a_connection_past_its_expiry_date_still_refreshes(
    services: Services, connected: FakeWorld
) -> None:
    # The 6-month date only holds scheduled runs; Spotify's invalid_grant is what ends it.
    past = iso_ms(services.clock.now() - timedelta(days=1))
    await services.store.execute("UPDATE spotify_auth SET expires_at = ? WHERE id = 1", (past,))
    assert (await services.connection.connection()).state == "expired"

    result = await services.catalog.refresh(trigger="run", run_id=await add_run(services))

    assert result.outcome == "ok" and result.refresh_id is not None
    assert LISTING in connected.webapi.endpoints()


async def test_without_a_connection_a_refresh_is_skipped(
    running_app: FastAPI, services: Services, world: FakeWorld
) -> None:
    result = await services.catalog.refresh(trigger="page_open")
    assert (result.outcome, result.refresh_id, result.items_changed) == ("skipped", None, 0)
    assert world.webapi.calls == []
    assert await services.store.fetchval("SELECT COUNT(*) FROM catalog_refreshes") == 0
    assert await services.catalog.last_refresh_at() is None


async def test_the_user_id_comes_from_get_me_when_it_isnt_stored(
    running_app: FastAPI, services: Services, world: FakeWorld
) -> None:
    await connect_fake(services, world, account=False)
    await services.catalog.refresh(trigger="setup")
    assert world.webapi.endpoints()[:2] == ["GET /me", LISTING]
    assert (await services.auth.load()).user_id == "user2"
    world.webapi.calls.clear()
    await services.catalog.refresh(trigger="page_open")
    assert "GET /me" not in world.webapi.endpoints()


# --- When refreshes run -------------------------------------------------------------------------


async def test_page_opens_are_throttled_to_one_every_15_minutes(
    services: Services, connected: FakeWorld, fake_clock: FakeClock
) -> None:
    catalog = services.catalog
    assert catalog.request_refresh("page_open") is True
    await catalog.wait_idle()
    assert catalog.request_refresh("page_open") is False

    fake_clock.set_now(fake_clock.now() + timedelta(seconds=THROTTLE_S - 1))
    assert catalog.request_refresh("page_open") is False
    fake_clock.set_now(fake_clock.now() + timedelta(seconds=2))
    assert catalog.request_refresh("page_open") is True
    await catalog.wait_idle()

    # Setup and adding items aren't throttled, and restart the 15 minutes.
    assert catalog.request_refresh("item_added") is True
    await catalog.wait_idle()
    assert catalog.request_refresh("setup") is True
    await catalog.wait_idle()
    assert catalog.request_refresh("page_open") is False
    rows = await services.store.fetchall("SELECT trigger FROM catalog_refreshes ORDER BY id")
    assert [r["trigger"] for r in rows] == ["page_open", "page_open", "item_added", "setup"]


async def test_requests_queued_together_run_as_one_refresh(
    services: Services, connected: FakeWorld
) -> None:
    catalog = services.catalog
    assert catalog.request_refresh("page_open") is True
    assert catalog.request_refresh("item_added") is True
    assert catalog.request_refresh("page_open") is True  # merged with the queued one
    await catalog.wait_idle()
    rows = await services.store.fetchall("SELECT trigger FROM catalog_refreshes")
    assert [r["trigger"] for r in rows] == ["item_added"]


async def test_no_background_refresh_runs_during_a_run(
    services: Services, connected: FakeWorld
) -> None:
    await add_run(services)
    assert services.catalog.request_refresh("item_added") is True
    await services.catalog.wait_idle()
    assert await services.store.fetchval("SELECT COUNT(*) FROM catalog_refreshes") == 0
    assert connected.webapi.calls == []


async def test_a_failing_background_refresh_doesnt_stop_the_controller(
    services: Services, connected: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("a bug")

    monkeypatch.setattr(connected.webapi, "my_playlists", broken)
    assert services.catalog.request_refresh("setup") is True
    await services.catalog.wait_idle()
    row = await services.store.fetchone("SELECT outcome, error FROM catalog_refreshes")
    assert row["outcome"] == "failed" and "RuntimeError" in row["error"]
    assert services.fatal_errors == []


# --- Liked Songs at connect ---------------------------------------------------------------------


async def test_liked_songs_exists_once_step_5_stores_the_account(
    running_app: FastAPI, services: Services, world: FakeWorld
) -> None:
    await connect_fake(services, world)
    row = await item_row(services, LIKED_ID)
    assert row is not None and row["tracked"] == 1  # "Include Liked Songs" is on by default
    assert row["uri"] == f"spotify:user:{world.catalog.user.id}:collection"
    assert world.webapi.calls == []  # no request


async def test_choosing_in_the_library_before_connecting_leaves_liked_songs_untracked(
    running_app: FastAPI, services: Services, world: FakeWorld
) -> None:
    await services.settings.set_value("auto_track_owned", False)
    await connect_fake(services, world)
    assert (await item_row(services, LIKED_ID))["tracked"] == 0
    await services.catalog.refresh(trigger="setup")
    assert LIKED not in world.webapi.endpoints()
    assert (await item_row(services, LIKED_ID))["tracked"] == 0


async def test_step_7_can_untrack_liked_songs_before_the_first_refresh(
    services: Services, connected: FakeWorld, client: httpx.AsyncClient
) -> None:
    response = await client.patch("/api/library/liked", json={"tracked": False})
    assert response.status_code == 200, response.text
    await services.catalog.refresh(trigger="setup")
    assert LIKED not in connected.webapi.endpoints()
    assert (await item_row(services, LIKED_ID))["tracked"] == 0


# --- D13: snapshot_ids a run's refresh couldn't read ---------------------------------------------


async def add_and_settle(services: Services, *links: str) -> None:
    for link in links:
        await services.library.add(f"spotify:playlist:{link}")
    await services.catalog.wait_idle()


async def test_a_runs_refresh_reads_linked_snapshots_before_the_track_lists(
    services: Services, connected: FakeWorld
) -> None:
    catalog = connected.catalog
    await services.catalog.refresh(trigger="setup")
    await add_and_settle(services, LINKED, FOLLOWED)
    catalog.set_entries(LINKED, catalog.playlists[LINKED].entries[:5])  # a new snapshot_id
    catalog.set_entries(PLAYLIST_4, catalog.playlists[PLAYLIST_4].entries[:80])
    fail_always(connected, "playlist_items", SpotifyUnavailable("down", status=503), PLAYLIST_4)
    connected.webapi.calls.clear()

    result = await services.catalog.refresh(trigger="run", run_id=await add_run(services))

    assert result.outcome == "partial"  # Spotify stopped answering the track lists
    assert connected.webapi.endpoints() == [LISTING, PLAYLIST, ITEMS]
    row = await item_row(services, LINKED)
    assert row["snapshot_id"] == catalog.playlists[LINKED].playlist.snapshot_id
    assert result.snapshots_unread == ()  # the followed one's came with the listing


async def test_snapshots_a_runs_refresh_could_not_read_are_reported(
    services: Services, connected: FakeWorld
) -> None:
    await services.catalog.refresh(trigger="setup")
    await add_and_settle(services, LINKED, FOLLOWED)

    run_id = await add_run(services)
    fail_always(connected, "playlist", SpotifyUnavailable("down", status=503), LINKED)
    result = await services.catalog.refresh(trigger="run", run_id=run_id)
    assert result.outcome == "partial"
    assert result.snapshots_unread == (LINKED,)  # S6 plays it whole

    connected.webapi.failures.append(SpotifyUnavailable("Spotify didn't answer", status=503))
    result = await services.catalog.refresh(trigger="run", run_id=run_id)
    assert result.outcome == "failed"  # the listing: no snapshot_id was read
    assert set(result.snapshots_unread) == {LINKED, FOLLOWED}


async def test_untracked_playlists_snapshots_are_reported_unread_unless_listed(
    services: Services, connected: FakeWorld
) -> None:
    """createRun with `items` runs an untracked playlist too. An untracked linked one is never
    read, so its stored snapshot_id may be stale (D13 mustn't skip it); an untracked followed
    one's comes with the listing."""
    await services.catalog.refresh(trigger="setup")
    await add_and_settle(services, LINKED, FOLLOWED)
    await services.library.set_tracked(LINKED, False)
    await services.library.set_tracked(FOLLOWED, False)
    await services.catalog.wait_idle()
    result = await services.catalog.refresh(trigger="run", run_id=await add_run(services))
    assert result.snapshots_unread == (LINKED,)


# --- auto_track_owned ---------------------------------------------------------------------------


async def tracked_owned(services: Services) -> int:
    return await services.store.fetchval(
        "SELECT COUNT(*) FROM items WHERE kind = 'owned' AND tracked = 1"
    )


async def test_with_auto_tracking_off_new_playlists_come_in_untracked(
    services: Services, connected: FakeWorld
) -> None:
    await services.settings.set_value("auto_track_owned", False)  # "I'll choose in the Library"
    result = await services.catalog.refresh(trigger="setup")

    assert result.outcome == "ok"
    # Nothing is tracked yet, Liked Songs included (web-ui.md step 7): no track list is read.
    assert Counter(connected.webapi.endpoints()) == {LISTING: 1}
    assert await tracked_owned(services) == 0
    assert (await item_row(services, LIKED_ID))["tracked"] == 0
    item = await services.library.item(PLAYLIST_4)
    assert item is not None
    assert (item.tracked, item.status, item.total, item.new) == (False, "not_tracked", 84, None)


async def test_turning_auto_tracking_on_tracks_every_owned_playlist(
    services: Services, connected: FakeWorld
) -> None:
    await services.settings.set_value("auto_track_owned", False)
    await services.catalog.refresh(trigger="setup")
    connected.webapi.calls.clear()

    await services.settings.set_value("auto_track_owned", True)
    assert await tracked_owned(services) == 17
    await services.catalog.wait_idle()  # it asked for a refresh, for their track lists
    calls = Counter(connected.webapi.endpoints())
    assert calls[ITEMS] == sum(
        pages(len(connected.catalog.playlists[i].entries)) for i in owned_ids(connected.catalog)
    )
    rows = await services.store.fetchall("SELECT trigger FROM catalog_refreshes ORDER BY id")
    assert [r["trigger"] for r in rows] == ["setup", "item_added"]


async def test_turning_auto_tracking_off_during_setup_untracks_everything(
    services: Services, connected: FakeWorld
) -> None:
    await services.catalog.refresh(trigger="setup")
    assert await tracked_owned(services) == 17

    await services.settings.set_value("auto_track_owned", False)  # "I'll choose in the Library"

    assert await tracked_owned(services) == 0
    assert (await item_row(services, LIKED_ID))["tracked"] == 0
    summary = await services.library.summary()
    assert (summary.tracked_count, summary.auto_track_owned) == (0, False)


async def test_turning_auto_tracking_off_after_setup_keeps_whats_tracked(
    services: Services, connected: FakeWorld
) -> None:
    await services.catalog.refresh(trigger="setup")
    await complete_setup(services)

    await services.settings.set_value("auto_track_owned", False)
    assert await tracked_owned(services) == 17

    # Only new playlists stop being tracked.
    new = connected.catalog.add_playlist("Made Today", tracks=3)
    await services.catalog.refresh(trigger="page_open")
    assert (await item_row(services, new.playlist.id))["tracked"] == 0


async def test_saving_auto_tracking_unchanged_keeps_what_you_untracked(
    services: Services, connected: FakeWorld
) -> None:
    await services.catalog.refresh(trigger="setup")
    await services.library.set_tracked(PLAYLIST_4, False)
    await services.catalog.wait_idle()

    await services.settings.set_value("auto_track_owned", True)  # already on

    assert (await item_row(services, PLAYLIST_4))["tracked"] == 0


# --- Events -------------------------------------------------------------------------------------


@pytest.fixture
def events(services: Services, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Every event published, as (type, data)."""
    seen: list[tuple[str, Any]] = []
    publish = services.bus.publish

    def record(type: str, data: Any) -> Any:
        event = publish(type, data)
        seen.append((type, event.data))
        return event

    monkeypatch.setattr(services.bus, "publish", record)
    return seen


async def test_each_changed_item_is_published(
    services: Services, connected: FakeWorld, events: list[tuple[str, Any]]
) -> None:
    await services.catalog.refresh(trigger="setup")

    items = [data for type, data in events if type == "library.item"]
    assert len(items) == 18
    assert {item["id"] for item in items} == {LIKED_ID, *owned_ids(connected.catalog)}
    for item in items:
        assert_schema("LibraryItem", item)
    liked = next(item for item in items if item["id"] == LIKED_ID)
    assert (liked["total"], liked["status"], liked["owner"]) == (277, "never_backed_up", "you")

    events.clear()
    await services.catalog.refresh(trigger="page_open")
    assert [type for type, _ in events if type == "library.item"] == []
