"""The catalog refresh on the real Web API port and the mock Spotify (tests/spotify_mock.py): the
requests it really sends, with the 2026 JSON, the `fields` and `market` parameters, the 250 ms
spacing and the usage log's counts. The S5 exit criterion "a refresh with nothing changed costs
at most 3 requests" is proved here.

Everything runs on the FakeClock; `spotify_mock.run` moves it whenever something sleeps on it.
"""

from collections import Counter
from itertools import pairwise

import pytest
from fastapi import FastAPI

from spotify_mock import SpotifyMock, connect, run
from spotivault.catalog.refresh import LIKED_ID, RefreshResult, RefreshTrigger
from spotivault.errors import ApiError
from spotivault.fake.clock import FakeClock
from spotivault.services import Services
from spotivault.webapi.client import SpotifyWebApi
from test_catalog_refresh import (
    FOLLOWED,
    ITEMS,
    LIKED,
    LINKED,
    LISTING,
    PLAYLIST,
    PLAYLIST_3,
    PLAYLIST_4,
    add_run,
    liked_entry,
    owned_ids,
    pages,
    warm,
)


@pytest.fixture
def mock(spotify_mock: SpotifyMock) -> SpotifyMock:
    warm(spotify_mock.catalog)
    return spotify_mock


@pytest.fixture
async def on_mock(
    running_app: FastAPI, services: Services, mock: SpotifyMock, mock_webapi: SpotifyWebApi
) -> SpotifyMock:
    await connect(services, mock)
    mock.clear_log()
    return mock


async def refresh(
    services: Services, clock: FakeClock, trigger: RefreshTrigger, run_id: int | None = None
) -> RefreshResult:
    return await run(clock, services.catalog.refresh(trigger=trigger, run_id=run_id))


async def test_a_first_fetch_on_the_mock(
    services: Services, on_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    catalog = on_mock.catalog
    result = await refresh(services, fake_clock, "setup")

    assert result.outcome == "ok", result.error
    assert on_mock.unexpected == []
    owned = owned_ids(catalog)
    item_requests = sum(pages(len(catalog.playlists[i].entries)) for i in owned)
    assert Counter(on_mock.endpoints()) == {LISTING: 1, ITEMS: item_requests, LIKED: pages(277)}
    # The usage log counted every request against this refresh.
    assert result.api.requests == len(on_mock.requests) == 1 + item_requests + 6
    assert (result.api.retried, result.api.rate_limited) == (0, 0)
    rows = await services.store.fetchall(
        "SELECT DISTINCT scope_kind, scope_id FROM api_requests WHERE endpoint_id <> 1"
    )
    assert [(r["scope_kind"], r["scope_id"]) for r in rows] == [("refresh", result.refresh_id)]

    # A followed playlist's items are never asked for (403).
    assert not any(FOLLOWED in r.path for r in on_mock.requests)
    for request in on_mock.requests:
        if request.endpoint in (ITEMS, LIKED):
            assert request.params["market"] == "from_token"
            assert request.params["limit"] == "50"
        if request.endpoint == ITEMS:
            assert "fields" in request.params
    # One at a time, 250 ms apart.
    times = [r.at for r in on_mock.requests if r.at is not None]
    assert all(later - earlier >= 0.25 - 1e-6 for earlier, later in pairwise(times))

    assert (await services.store.fetchone("SELECT total FROM items WHERE id = ?", (PLAYLIST_3,)))[
        "total"
    ] == 13
    liked = await services.store.fetchone(
        "SELECT total, liked_newest_added_at FROM items WHERE id = ?", (LIKED_ID,)
    )
    assert (liked["total"], liked["liked_newest_added_at"]) == (277, catalog.liked[0].added_at)
    count = await services.store.fetchval(
        "SELECT COUNT(*) FROM item_tracks WHERE item_id = ?", (PLAYLIST_3,)
    )
    assert count == 16  # the local file, the episode and the empty entry keep their places


async def test_a_refresh_with_nothing_changed_costs_at_most_3_requests(
    services: Services, on_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    await refresh(services, fake_clock, "setup")
    on_mock.clear_log()

    result = await refresh(services, fake_clock, "page_open")

    assert len(on_mock.requests) <= 3
    assert on_mock.endpoints() == [LISTING, LIKED]
    assert result.api.requests == 2 and result.items_changed == 0
    row = await services.store.fetchone(
        "SELECT api_requests, api_retried, api_rate_limited FROM catalog_refreshes WHERE id = ?",
        (result.refresh_id,),
    )
    assert tuple(row) == (2, 0, 0)


async def test_a_changed_snapshot_refetches_only_that_playlist_on_the_mock(
    services: Services, on_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    catalog = on_mock.catalog
    await refresh(services, fake_clock, "setup")
    on_mock.clear_log()
    catalog.set_entries(PLAYLIST_4, catalog.playlists[PLAYLIST_4].entries[:60])

    result = await refresh(services, fake_clock, "page_open")

    assert on_mock.endpoints() == [LISTING, ITEMS, ITEMS, LIKED]
    assert all(PLAYLIST_4 in r.path for r in on_mock.requests if r.endpoint == ITEMS)
    assert result.items_changed == 1
    row = await services.store.fetchone(
        "SELECT total, snapshot_id FROM items WHERE id = ?", (PLAYLIST_4,)
    )
    assert (row["total"], row["snapshot_id"]) == (
        60,
        catalog.playlists[PLAYLIST_4].playlist.snapshot_id,
    )


async def test_liked_songs_are_read_incrementally_on_the_mock(
    services: Services, on_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    catalog = on_mock.catalog
    await refresh(services, fake_clock, "setup")
    on_mock.clear_log()
    catalog.liked.insert(0, liked_entry(catalog, "Fresh", "2026-11-14T10:00:00Z"))

    await refresh(services, fake_clock, "page_open")
    assert on_mock.endpoints() == [LISTING, LIKED]

    del catalog.liked[200]  # removed: the total no longer adds up
    on_mock.clear_log()
    await refresh(services, fake_clock, "page_open")
    assert on_mock.endpoints() == [LISTING] + [LIKED] * pages(277)
    stored = await services.store.fetchall(
        "SELECT track_id FROM item_tracks WHERE item_id = ? ORDER BY position", (LIKED_ID,)
    )
    assert [r["track_id"] for r in stored] == [e.track.id for e in catalog.liked if e.track]


async def test_linked_playlists_are_read_on_a_runs_refresh_on_the_mock(
    services: Services, on_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    await refresh(services, fake_clock, "setup")
    on_mock.clear_log()
    item = await run(fake_clock, services.library.add(f"spotify:playlist:{LINKED}"))
    assert (item.kind, item.total, item.item_access, item.name) == (
        "linked",
        None,
        False,
        "Linked Mix",
    )
    assert on_mock.endpoints() == [PLAYLIST]
    assert on_mock.requests[0].authorization is not None

    on_mock.clear_log()
    await refresh(services, fake_clock, "page_open")
    assert PLAYLIST not in on_mock.endpoints()

    on_mock.clear_log()
    run_id = await add_run(services)
    result = await refresh(services, fake_clock, "run", run_id)
    assert on_mock.endpoints() == [LISTING, PLAYLIST, LIKED]  # linked first: D13 needs them
    assert result.api.requests == 3
    assert result.snapshots_unread == ()
    scopes = await services.store.fetchall(
        "SELECT DISTINCT scope_kind, scope_id FROM api_requests WHERE scope_kind = 'refresh' "
        "AND scope_id = ?",
        (result.refresh_id,),
    )
    assert len(scopes) == 1


async def test_spotify_made_playlists_are_refused_without_asking_on_the_mock(
    services: Services, on_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    for call in (services.library.resolve, services.library.add):
        with pytest.raises(ApiError) as caught:
            await call("https://open.spotify.com/playlist/37i9dQZF1DXLnUtMmNIBbc")
        assert (caught.value.status, caught.value.code) == (422, "spotify_owned")
    assert on_mock.requests == []


async def test_an_unknown_link_is_not_found_on_the_mock(
    services: Services, on_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    with pytest.raises(ApiError) as caught:
        await run(fake_clock, services.library.resolve("spotify:playlist:" + "Z" * 22))
    assert (caught.value.status, caught.value.code) == (422, "not_found")
    assert on_mock.endpoints() == [PLAYLIST]


async def test_tokens_never_reach_the_refresh_rows(
    services: Services, on_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    row = await services.auth.load()
    on_mock.fail(LISTING, status=500, times=4)
    result = await refresh(services, fake_clock, "page_open")
    assert result.outcome == "failed" and result.error is not None
    assert result.api.retried == 3
    stored = await services.store.fetchone(
        "SELECT error FROM catalog_refreshes WHERE id = ?", (result.refresh_id,)
    )
    for secret in (row.access_token, row.refresh_token):
        assert secret is not None and secret not in stored["error"]
