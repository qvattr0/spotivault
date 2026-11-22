"""The Albums page (catalog/albums.py and api/routers/albums.py): adding by ids and by all, removing
(files kept), the tracks with their per-track state, and the album.item events.

The matching surface (the index and the counts) and the backlog are stubbed here with the
monkeypatched `recorded` fixture, until matching-backlog lands: the index is a set of keys the
test fills in. The Web API is the fake one, connected through the stored token.
"""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import contract
from spotivault.catalog.covers import CoverService
from spotivault.errors import ApiError
from spotivault.fake import world_of
from spotivault.fake.catalog import CatalogAlbum
from spotivault.fake.clock import FakeClock
from spotivault.fake.world import FakeWorld
from spotivault.matching import ItemCounts, RecordedIndex, track_key
from spotivault.ports import NotFound, TokenGrant
from spotivault.services import Services

CLIENT_ID = "0123456789abcdef0123456789abcdef"
GRANT = TokenGrant(access_token="t" * 10, refresh_token="r" * 10, expires_in_s=3600, scopes=())


@pytest.fixture
async def connected(running_app: FastAPI, services: Services) -> None:
    await services.auth.set_client_id(CLIENT_ID)
    await services.auth.save_grant(CLIENT_ID, GRANT)


@pytest.fixture
def recorded(services: Services, monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """The stand-in for Spytify's index: the keys in this set are recorded. Also the counts the
    page shows, computed from the same set, and a backlog that does nothing."""
    keys: set[str] = set()

    async def index(*, max_age_s: float = 2.0) -> RecordedIndex:
        paths = {key: f"/music/{key}.m4a" for key in keys}
        return RecordedIndex(paths=paths, read_at=services.clock.now())

    async def item_counts(item_ids: Any = None) -> dict[str, ItemCounts]:
        counts: dict[str, ItemCounts] = {}
        for item_id in item_ids or []:
            rows = await services.store.fetchall(
                "SELECT it.playable, t.spytify_key FROM item_tracks it "
                "LEFT JOIN tracks t ON t.id = it.track_id WHERE it.item_id = ?",
                (item_id,),
            )
            if not rows:
                continue
            playable = [row for row in rows if row["playable"]]
            recorded_count = sum(1 for row in playable if row["spytify_key"] in keys)
            counts[item_id] = ItemCounts(total=len(playable), recorded=recorded_count, new=0)
        return counts

    async def backlog_update() -> None:
        return None

    monkeypatch.setattr(services.matching, "index", index)
    monkeypatch.setattr(services.matching, "item_counts", item_counts)
    monkeypatch.setattr(services.backlog, "update", backlog_update)
    return keys


def world(services: Services) -> FakeWorld:
    return world_of(services.ports)


def only_saved(
    services: Services, name: str, *, artist: str = "Test Artist", tracks: Any = 3
) -> str:
    """A saved album in the fake catalog, and the library's other albums unsaved, so the saved
    list holds just the ones the test makes. Returns its id."""
    catalog = world(services).catalog
    for album in catalog.albums.values():
        album.added_at = None
    entry: CatalogAlbum = catalog.add_album(name, artist=artist, tracks=tracks)
    return entry.album.id


async def stored(services: Services, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return await services.store.fetchone(sql, params)


async def setup_step(services: Services, step: str) -> str:
    setup = await services.setup.snapshot()
    return next(item.state for item in setup.steps if item.id == step)


def spy_events(services: Services, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Records every event published, and still publishes it."""
    seen: list[tuple[str, Any]] = []
    real_publish = services.bus.publish

    def publish(type: str, data: Any) -> Any:
        seen.append((type, data))
        return real_publish(type, data)

    monkeypatch.setattr(services.bus, "publish", publish)
    return seen


# --- Adding -------------------------------------------------------------------------------------


async def test_add_by_ids_stores_the_album_its_tracks_and_its_cover(
    connected: None,
    services: Services,
    recorded: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    album_id = only_saved(services, "Night Drive")
    events = spy_events(services, monkeypatch)

    response = await services.albums.add(ids=[album_id])

    assert [album.name for album in response.added] == ["Night Drive"]
    assert response.skipped == []
    added = response.added[0]
    assert added.status == "queued" and added.total == 3 and added.recorded == 0
    assert added.cover is not None and added.cover.startswith(f"/api/albums/{album_id}/cover")

    row = await stored(services, "SELECT * FROM items WHERE id = ?", (album_id,))
    assert row["kind"] == "album" and row["tracked"] == 1 and row["removed_at"] is None
    # Setup isn't complete in a fresh controller: the add is part of setup (web-ui.md step 8).
    assert row["added_by"] == "setup"
    assert row["total"] == 3 and row["saved_at"] is not None
    tracks = await stored(
        services, "SELECT COUNT(*) AS n FROM item_tracks WHERE item_id = ?", (album_id,)
    )
    assert tracks["n"] == 3

    assert row["cover_source"] == "spotify" and row["thumb_path"] and row["full_path"]
    cache = services.config.covers_cache_dir
    assert (cache / row["thumb_path"]).is_file() and (cache / row["full_path"]).is_file()
    assert any(
        url.endswith("ab67616d00001e02" + row["image_id"]) for url in world(services).cdn.fetched
    )

    # Step 8 is done, and one album.item went out for it.
    assert await setup_step(services, "albums") == "done"
    assert [(type, data.id) for type, data in events if type == "album.item"] == [
        ("album.item", album_id)
    ]


async def test_a_cover_that_cannot_be_saved_does_not_stop_the_add(
    connected: None,
    services: Services,
    recorded: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = only_saved(services, "Full Disk One")
    second = world(services).catalog.add_album("Full Disk Two", tracks=2).album.id

    async def full_disk(item_id: str, images: Any) -> Any:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(services.covers, "update", full_disk)
    response = await services.albums.add(all_saved=True)  # wizard step 8's "all"

    assert sorted(album.id for album in response.added) == sorted([first, second])
    assert all(album.cover is None for album in response.added)
    assert await setup_step(services, "albums") == "done"


async def test_an_album_requeued_after_a_stall_is_queued_not_recording(
    connected: None, services: Services, recorded: set[str]
) -> None:
    album_id = only_saved(services, "Stalled Once")
    await services.albums.add(ids=[album_id])

    def write(conn: Any) -> None:
        run = conn.execute(
            "INSERT INTO runs (kind, trigger, state, started_at) "
            "VALUES ('run', 'run_now', 'running', '2026-11-15T09:00:00.000Z')"
        ).lastrowid
        conn.execute(
            "INSERT INTO run_items (run_id, item_id, queue_pos, state, interrupted_count) "
            "VALUES (?, ?, 5, 'interrupted', 1)",
            (run, album_id),
        )

    await services.store.transaction(write)
    album = await services.albums.album(album_id)
    assert album is not None and album.status == "queued"  # openapi.yaml ItemState: it waits


async def test_adding_as_the_user_once_setup_is_complete(
    connected: None,
    services: Services,
    recorded: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    album_id = only_saved(services, "Later")

    async def complete() -> bool:
        return True

    monkeypatch.setattr(services.setup, "is_complete", complete)
    await services.albums.add(ids=[album_id])

    row = await stored(services, "SELECT added_by FROM items WHERE id = ?", (album_id,))
    assert row["added_by"] == "user"


async def test_add_all_adds_only_the_saved_albums_not_yet_added(
    connected: None, services: Services, recorded: set[str]
) -> None:
    first = only_saved(services, "One")
    second = world(services).catalog.add_album("Two", tracks=2).album.id

    added = await services.albums.add(all_saved=True)
    assert sorted(album.id for album in added.added) == sorted([first, second])
    assert added.skipped == []

    # Choosing "all" again adds only the missing ones: none now.
    again = await services.albums.add(all_saved=True)
    assert again.added == [] and again.skipped == []

    third = world(services).catalog.add_album("Three", tracks=2).album.id
    later = await services.albums.add(all_saved=True)
    assert [album.id for album in later.added] == [third]


async def test_add_by_ids_skips_what_is_not_saved_or_already_added(
    connected: None, services: Services, recorded: set[str]
) -> None:
    album_id = only_saved(services, "Saved")
    unsaved = world(services).catalog.add_album("Not saved", tracks=2, saved=False).album.id
    await services.albums.add(ids=[album_id])

    response = await services.albums.add(ids=[album_id, unsaved])

    assert response.added == []
    reasons = {item.id: item.reason for item in response.skipped}
    assert reasons == {album_id: "already_added", unsaved: "not_saved"}


async def test_an_album_saved_after_the_listing_was_kept_is_found_by_id(
    connected: None, services: Services, recorded: set[str]
) -> None:
    only_saved(services, "Cached")
    await services.albums.saved()  # the listing is kept now
    fresh = world(services).catalog.add_album("Saved since", tracks=2).album.id

    response = await services.albums.add(ids=[fresh])

    assert [album.id for album in response.added] == [fresh]


async def test_a_track_list_that_goes_past_its_first_page_is_fetched_in_full(
    connected: None, services: Services, recorded: set[str]
) -> None:
    album_id = only_saved(services, "Long", tracks=60)
    calls_before = len(world(services).webapi.calls)

    response = await services.albums.add(ids=[album_id])

    assert response.added[0].total == 60
    rows = await stored(
        services, "SELECT COUNT(*) AS n FROM item_tracks WHERE item_id = ?", (album_id,)
    )
    assert rows["n"] == 60
    # The listing's first page came with the listing; the rest is one call for offset 50.
    new_calls = [call.endpoint for call in world(services).webapi.calls[calls_before:]]
    assert new_calls.count("GET /albums/{id}/tracks") == 1


async def test_an_album_whose_tracks_answer_404_is_skipped(
    connected: None,
    services: Services,
    recorded: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    album_id = only_saved(services, "Gone", tracks=60)
    fake = world(services).webapi

    async def missing(album: str, **kwargs: Any) -> Any:
        raise NotFound("Resource not found", status=404)

    monkeypatch.setattr(fake, "album_tracks", missing)

    response = await services.albums.add(ids=[album_id])

    assert response.added == []
    assert [(item.id, item.reason) for item in response.skipped] == [(album_id, "not_found")]
    assert await stored(services, "SELECT id FROM items WHERE id = ?", (album_id,)) is None


# --- Removing -----------------------------------------------------------------------------------


async def test_remove_keeps_the_files_and_the_tracks(
    connected: None, services: Services, recorded: set[str]
) -> None:
    album_id = only_saved(services, "Kept")
    await services.albums.add(ids=[album_id])
    cover = (await stored(services, "SELECT thumb_path FROM items WHERE id = ?", (album_id,)))[
        "thumb_path"
    ]

    await services.albums.remove(album_id)

    row = await stored(services, "SELECT removed_at FROM items WHERE id = ?", (album_id,))
    assert row["removed_at"] is not None
    assert (services.config.covers_cache_dir / cover).is_file()
    tracks = await stored(
        services, "SELECT COUNT(*) AS n FROM item_tracks WHERE item_id = ?", (album_id,)
    )
    assert tracks["n"] == 3
    page = await services.albums.list_albums()
    assert album_id not in [album.id for album in page.items]
    saved = await services.albums.saved()
    assert album_id in [album.id for album in saved.items]

    with pytest.raises(ApiError) as gone:
        await services.albums.remove(album_id)
    assert gone.value.status == 404

    # Adding it again brings it back on the page, with its tracks.
    back = await services.albums.add(ids=[album_id])
    assert [album.id for album in back.added] == [album_id]
    row = await stored(services, "SELECT removed_at FROM items WHERE id = ?", (album_id,))
    assert row["removed_at"] is None


# --- The page -----------------------------------------------------------------------------------


async def test_the_page_sorts_searches_and_filters(
    connected: None, services: Services, recorded: set[str]
) -> None:
    catalog = world(services).catalog
    for album in catalog.albums.values():
        album.added_at = None
    # "Charlie" by Alpha, "Alpha" by Bravo, "Bravo" by Charlie.
    names = {}
    for name, artist in (("Charlie", "Alpha"), ("Alpha", "Bravo"), ("Bravo", "Charlie")):
        names[name] = catalog.add_album(name, artist=artist, tracks=2).album.id
    await services.albums.add(all_saved=True)

    by_album = await services.albums.list_albums(sort="album")
    assert [album.name for album in by_album.items] == ["Alpha", "Bravo", "Charlie"]
    by_artist = await services.albums.list_albums(sort="artist")
    assert [album.name for album in by_artist.items] == ["Charlie", "Alpha", "Bravo"]

    searched = await services.albums.list_albums(q="BRAVO")
    assert sorted(album.name for album in searched.items) == ["Alpha", "Bravo"]

    await services.store.execute(
        "UPDATE items SET completed_at = ? WHERE id = ?",
        ("2026-11-15T10:00:00.000Z", names["Alpha"]),
    )
    recorded_only = await services.albums.list_albums(filter="recorded")
    assert [album.name for album in recorded_only.items] == ["Alpha"]
    assert recorded_only.items[0].status == "recorded"
    page = await services.albums.list_albums()
    assert page.summary.total == 3 and page.summary.recorded == 1 and page.summary.queued == 2
    queued = await services.albums.list_albums(filter="queued")
    assert sorted(album.name for album in queued.items) == ["Bravo", "Charlie"]


async def test_a_partial_album_is_marked_from_its_last_run(
    connected: None, services: Services, recorded: set[str]
) -> None:
    album_id = only_saved(services, "Patchy", tracks=2)
    await services.albums.add(ids=[album_id])
    await _last_run_with_a_failed_take(services, album_id, track_index=0)

    page = await services.albums.list_albums(filter="partial")

    assert [album.id for album in page.items] == [album_id]
    assert page.items[0].status == "partial"


# --- Tracks -------------------------------------------------------------------------------------


async def _last_run_with_a_failed_take(
    services: Services, album_id: str, *, track_index: int
) -> None:
    """A run that ended with one failed take of the album's track `track_index`."""
    track = await stored(
        services,
        "SELECT t.id FROM item_tracks it JOIN tracks t ON t.id = it.track_id "
        "WHERE it.item_id = ? AND it.position = ?",
        (album_id, track_index),
    )

    def write(conn: Any) -> None:
        run = conn.execute(
            "INSERT INTO runs (kind, trigger, state, outcome, started_at, ended_at) "
            "VALUES ('run', 'run_now', 'ended', 'completed_with_issues', "
            "'2026-11-15T09:00:00.000Z', '2026-11-15T09:30:00.000Z')"
        ).lastrowid
        item = conn.execute(
            "INSERT INTO run_items (run_id, item_id, queue_pos, state, failed, started_at, "
            "ended_at) "
            "VALUES (?, ?, 0, 'partial', 1, '2026-11-15T09:00:00.000Z', "
            "'2026-11-15T09:30:00.000Z')",
            (run, album_id),
        ).lastrowid
        conn.execute(
            "INSERT INTO track_results (run_item_id, take_id, track_id, artist, title, planned, "
            "result, reason, started_at) VALUES (?, 'take-1', ?, 'Test Artist', 'x', 1, "
            "'failed', 'recorder_error', '2026-11-15T09:10:00.000Z')",
            (item, track["id"]),
        )

    await services.store.transaction(write)


async def test_the_tracks_carry_their_state(
    connected: None,
    services: Services,
    recorded: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = world(services).catalog
    for album in catalog.albums.values():
        album.added_at = None
    album_id = catalog.add_album(
        "Mixed",
        artist="Test Artist",
        tracks=[("One", 90_000), ("Two", 60_000), ("Three", 120_000), ("Four", 30_000)],
        unplayable=(2,),
    ).album.id
    await services.albums.add(ids=[album_id])

    recorded.add(track_key("Test Artist", "One"))  # recorded: in Spytify's index
    await services.store.execute(
        "INSERT INTO files (spytify_key, path, bytes, duration_ms, format, counted, take_id, "
        "recorded_at) VALUES (?, 'Test Artist/Mixed/01 - One.m4a', 1234, 90000, 'aac', 1, "
        "'take-0', '2026-11-15T09:05:00.000Z')",
        (track_key("Test Artist", "One"),),
    )
    await _last_run_with_a_failed_take(services, album_id, track_index=1)

    listing = await services.albums.tracks(album_id)

    assert listing.item_access is True and listing.total == 3
    assert listing.duration_ms == 90_000 + 60_000 + 30_000  # the playable tracks only
    states = [(track.position, track.title, track.state) for track in listing.tracks]
    assert states == [
        (1, "One", "recorded"),
        (2, "Two", "failed"),
        (3, "Three", "unplayable"),
        (4, "Four", "missing"),
    ]
    one = listing.tracks[0]
    assert one.size_bytes == 1234 and one.path == "Test Artist/Mixed/01 - One.m4a"
    assert one.recorded_at is not None
    assert listing.tracks[1].reason == "recorder_error"


async def test_tracks_of_an_album_not_on_the_page_are_not_found(
    connected: None, services: Services, recorded: set[str]
) -> None:
    with pytest.raises(ApiError) as missing:
        await services.albums.tracks("4glBZ0bZMgkmFyi6TD4h69")
    assert missing.value.status == 404


# --- The album.item events ----------------------------------------------------------------------


async def test_publish_is_held_to_one_event_per_second(
    connected: None,
    running_app: FastAPI,
    services: Services,
    fake_clock: FakeClock,
    recorded: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    album_id = only_saved(services, "Busy")
    await services.albums.add(ids=[album_id])
    await fake_clock.advance(1.5)  # the add's own event is over: the next one goes at once
    events = spy_events(services, monkeypatch)

    await services.albums.publish(album_id)  # sent at once
    await services.albums.publish(album_id)  # held: the second isn't over
    await services.albums.publish(album_id)
    assert len(events) == 1

    await fake_clock.advance(1.5)  # the flush task sends the held one, once: its latest state
    assert len(events) == 2
    assert events[1][0] == "album.item" and events[1][1].id == album_id


# --- Endpoints ----------------------------------------------------------------------------------


async def test_the_endpoints_answer_in_the_contract(
    client: httpx.AsyncClient, connected: None, services: Services, recorded: set[str]
) -> None:
    album_id = only_saved(services, "Endpoint", tracks=2)

    page = await client.get("/api/albums")
    assert page.status_code == 200
    contract.assert_response(page, "/api/albums")

    saved = await client.get("/api/albums/saved")
    assert saved.status_code == 200
    contract.assert_response(saved, "/api/albums/saved")
    assert [item["id"] for item in saved.json()["items"]] == [album_id]

    added = await client.post("/api/albums", json={"ids": [album_id]})
    assert added.status_code == 200
    contract.assert_response(added, "/api/albums")
    assert [item["id"] for item in added.json()["added"]] == [album_id]

    tracks = await client.get(f"/api/albums/{album_id}/tracks")
    assert tracks.status_code == 200
    contract.assert_response(tracks, "/api/albums/{id}/tracks")
    assert len(tracks.json()["tracks"]) == 2

    removed = await client.delete(f"/api/albums/{album_id}")
    assert removed.status_code == 204
    again = await client.delete(f"/api/albums/{album_id}")
    assert again.status_code == 404
    assert again.json()["error"]["code"] == "not_found"


async def test_adding_while_not_connected_answers_409(
    client: httpx.AsyncClient, services: Services, recorded: set[str]
) -> None:
    response = await client.post("/api/albums", json={"all": True})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_connected"
    contract.assert_response(response, "/api/albums")


def test_covers_service_is_the_fake_one_in_fake_mode(services: Services) -> None:
    """Fake mode: covers come from the simulated CDN, so nothing reaches the network."""
    assert isinstance(services.covers, CoverService)
    assert type(services.ports.cdn).__name__ == "FakeImageCdn"
