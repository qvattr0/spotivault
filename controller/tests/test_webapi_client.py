"""webapi/client.py: the real Web API port on the mock Spotify (tests/spotify_mock.py).

The exit criteria of S5's webapi-core part: 429 waits Retry-After, 5xx waits 5, 10, then 20 s
and gives up, the longer Retry-After wins, a 401 refreshes once, invalid_grant expires the
connection, 403 and 404 are answers, timeouts, the 250 ms catalog spacing, playback first, and
the usage-log rows (templates, never ids). Everything runs on the FakeClock; `drive` moves it.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from portcheck import assert_implements
from spotify_mock import SpotifyMock, drive, our_device_id, run
from spotivault import ports
from spotivault.config import Config
from spotivault.fake.catalog import SPOTIFY_MADE_PREFIX
from spotivault.fake.clock import FakeClock
from spotivault.ports import (
    ApiScope,
    ConnectionExpired,
    NoAccess,
    NotConnected,
    NotFound,
    RateLimited,
    SpotifyUnavailable,
    TokenExchangeFailed,
    TokenGrant,
    WebApiError,
)
from spotivault.store import Store
from spotivault.webapi.auth_store import AuthStore
from spotivault.webapi.client import (
    PLAYLIST_FIELDS,
    PLAYLIST_ITEMS_FIELDS,
    RATE_LIMIT_MAX_WAIT_S,
    SpotifyWebApi,
)
from spotivault.webapi.endpoints import REDIRECT_URI, SCOPES

# Ids from the mock's fixtures library (fake/catalog.py).
# Playlist 3: a local file (4), an episode (8) and an empty entry (11).
OWNED = "BcBk6G1xxldO5YUpUExUnE"
FOLLOWED = "a9poFNKiHX6sRmXWJ3e0mn"  # Playlist 1: 403 on its items
LINKED = "gT7JiQHe0CjfUwwctmONus"  # Linked Mix: no `items` on GET /playlists/{id}
SPOTIFY_MADE = SPOTIFY_MADE_PREFIX + "DXLnUtMmNIBbc"  # Editorial Picks: 404
ALBUM = "2CmcfbEF5FiI1h7J1F1ast"


async def until(condition: Callable[[], bool], *, within_s: float = 2.0) -> None:
    """Waits in real time (the database thread) until `condition()` is true."""
    for _ in range(int(within_s / 0.002)):
        if condition():
            return
        await asyncio.sleep(0.002)
    raise TimeoutError("condition still false")


# --- Fixtures --------------------------------------------------------------------------------


@pytest.fixture
async def store(config: Config) -> AsyncIterator[Store]:
    store = Store(config.db_path)
    await store.open()
    yield store
    await store.close()


@pytest.fixture
def auth(store: Store, fake_clock: FakeClock) -> AuthStore:
    return AuthStore(store, fake_clock)


@pytest.fixture
async def api(
    config: Config, fake_clock: FakeClock, store: Store, auth: AuthStore, spotify_mock: SpotifyMock
) -> AsyncIterator[SpotifyWebApi]:
    api = SpotifyWebApi(config, fake_clock, store, auth, transport=spotify_mock.transport())
    yield api
    await api.aclose()


@pytest.fixture
async def tokens(auth: AuthStore, spotify_mock: SpotifyMock) -> tuple[str, str]:
    """A working connection, as wizard step 5 leaves it. Returns (access, refresh)."""
    access, refresh = spotify_mock.issue_tokens()
    await auth.set_client_id(spotify_mock.client_id)
    grant = TokenGrant(access, refresh, spotify_mock.access_token_ttl_s, SCOPES)
    await auth.save_grant(spotify_mock.client_id, grant)
    return access, refresh


async def usage_rows(store: Store) -> list[dict[str, Any]]:
    rows = await store.fetchall(
        "SELECT r.*, e.method || ' ' || e.template AS endpoint FROM api_requests r "
        "JOIN api_endpoints e ON e.id = r.endpoint_id ORDER BY r.id"
    )
    return [dict(row) for row in rows]


async def warnings(store: Store) -> list[dict[str, Any]]:
    return [dict(r) for r in await store.fetchall("SELECT * FROM api_warnings ORDER BY id")]


def times(mock: SpotifyMock, start: float) -> list[float]:
    """When each request reached the mock, in seconds after `start`."""
    return [round((request.at or 0.0) - start, 3) for request in mock.requests]


# --- The port --------------------------------------------------------------------------------


def test_it_implements_the_port() -> None:
    assert_implements(SpotifyWebApi, ports.WebApi)


async def test_building_it_sends_nothing_and_closing_it_works(
    config: Config, fake_clock: FakeClock, store: Store, auth: AuthStore
) -> None:
    api = SpotifyWebApi(config, fake_clock, store, auth)
    assert api._http is None
    await api.aclose()
    await api.aclose()


@pytest.mark.usefixtures("tokens")
async def test_me_and_the_request_it_sends(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, tokens: tuple[str, str]
) -> None:
    user = await api.me()
    assert user == spotify_mock.catalog.user
    [request] = spotify_mock.requests
    assert request.endpoint == "GET /me"
    assert request.authorization == f"Bearer {tokens[0]}"
    assert request.params == {}
    assert spotify_mock.unexpected == []


@pytest.mark.usefixtures("tokens")
async def test_my_playlists_reads_items_total_for_every_kind(
    api: SpotifyWebApi, spotify_mock: SpotifyMock
) -> None:
    page = await api.my_playlists()
    assert page.total == 18 and len(page.items) == 18 and page.next_offset is None
    by_id = {p.id: p for p in page.items}
    assert by_id[FOLLOWED].total == 35  # a followed playlist's total is there (S0 row 20)
    assert by_id[OWNED].total == 16 and by_id[OWNED].snapshot_id
    assert spotify_mock.requests[0].params == {"offset": "0", "limit": "50"}


@pytest.mark.usefixtures("tokens")
async def test_a_playlist_with_fields_and_a_linked_one_without_a_total(
    api: SpotifyWebApi, fake_clock: FakeClock, spotify_mock: SpotifyMock
) -> None:
    owned = await run(fake_clock, api.playlist(OWNED))
    assert owned.total == 16 and owned.owner_id == "user2" and owned.images
    linked = await run(fake_clock, api.playlist(LINKED))
    assert linked.name == "Linked Mix" and linked.total is None and linked.snapshot_id
    assert {r.params["fields"] for r in spotify_mock.requests} == {PLAYLIST_FIELDS}
    assert all("market" not in r.params for r in spotify_mock.requests)


@pytest.mark.usefixtures("tokens")
async def test_playlist_items_with_fields_market_and_odd_entries(
    api: SpotifyWebApi, spotify_mock: SpotifyMock
) -> None:
    page = await api.playlist_items(OWNED)
    assert page.total == 16 and len(page.items) == 16
    request = spotify_mock.requests[0]
    assert request.params["market"] == "from_token"
    assert request.params["fields"] == PLAYLIST_ITEMS_FIELDS
    expected = spotify_mock.catalog.playlists[OWNED].entries
    for got, want in zip(page.items, expected, strict=True):
        if want.track is None:
            assert got.track is None
            continue
        assert got.track is not None
        assert (got.track.id, got.track.uri, got.track.name, got.track.artists) == (
            want.track.id,
            want.track.uri,
            want.track.name,
            want.track.artists,
        )
        assert got.track.is_local == want.track.is_local
        assert got.track.is_episode == want.track.is_episode  # `episode` is in the fields
        assert got.track.duration_ms == want.track.duration_ms
        if not want.track.is_local:
            assert got.track.is_playable is not None  # asked with a market
    assert page.items[4].track is not None and page.items[4].track.is_local
    assert page.items[8].track is not None and page.items[8].track.is_episode
    assert page.items[11].track is None


@pytest.mark.usefixtures("tokens")
async def test_liked_songs_page_by_page(
    api: SpotifyWebApi, fake_clock: FakeClock, spotify_mock: SpotifyMock
) -> None:
    offset: int | None = 0
    seen = []
    while offset is not None:
        page = await run(fake_clock, api.saved_tracks(offset=offset))
        seen.extend(page.items)
        offset = page.next_offset
    assert len(seen) == 277
    assert all(saved.track.is_playable is not None for saved in seen)
    assert spotify_mock.count("GET /me/tracks") == 6
    assert {r.params["market"] for r in spotify_mock.requests} == {"from_token"}


@pytest.mark.usefixtures("tokens")
async def test_saved_albums_carry_their_first_page_and_album_tracks_their_album(
    api: SpotifyWebApi, fake_clock: FakeClock, spotify_mock: SpotifyMock
) -> None:
    page = await run(fake_clock, api.saved_albums(limit=5))
    assert page.total == 124 and len(page.items) == 5 and page.next_offset == 5
    album = page.items[0].album
    assert album.tracks is not None and album.tracks.items
    assert {t.album_id for t in album.tracks.items} == {album.id}
    tracks = await run(fake_clock, api.album_tracks(ALBUM, limit=2))
    assert len(tracks.items) == 2 and tracks.next_offset == 2
    assert {t.album_id for t in tracks.items} == {ALBUM}
    assert spotify_mock.requests[-1].params == {
        "offset": "0",
        "limit": "2",
        "market": "from_token",
    }


@pytest.mark.usefixtures("tokens")
async def test_devices_and_the_player(api: SpotifyWebApi, spotify_mock: SpotifyMock) -> None:
    devices = await api.devices()
    ours = our_device_id(spotify_mock)
    assert devices[0].id == ours and devices[0].name == spotify_mock.device_name
    assert await api.player_state() is None  # 204: nothing playing anywhere
    spotify_mock.player_state = {
        "device": {"id": ours, "name": spotify_mock.device_name, "type": "Computer"},
        "is_playing": True,
        "context": {"uri": f"spotify:playlist:{OWNED}"},
        "item": {"id": "t" * 22},
        "progress_ms": 10,
        "shuffle_state": False,
        "repeat_state": "off",
    }
    state = await api.player_state()
    assert state is not None and state.context_uri == f"spotify:playlist:{OWNED}"


@pytest.mark.usefixtures("tokens")
async def test_the_player_controls(api: SpotifyWebApi, spotify_mock: SpotifyMock) -> None:
    ours = our_device_id(spotify_mock)
    track_uri = "spotify:track:" + "t" * 22
    await api.play(device_id=ours, context_uri=f"spotify:playlist:{OWNED}", offset_uri=track_uri)
    await api.play(device_id=ours, context_uri=f"spotify:album:{ALBUM}", position_ms=0)
    await api.pause(device_id=ours)
    await api.seek(0, device_id=ours)
    await api.set_shuffle(False, device_id=ours)
    await api.set_repeat("off", device_id=ours)
    play, play2, pause, seek, shuffle, repeat = spotify_mock.requests
    assert play.json == {
        "context_uri": f"spotify:playlist:{OWNED}",
        "position_ms": 0,
        "offset": {"uri": track_uri},  # by URI, never by position
    }
    assert play2.json == {"context_uri": f"spotify:album:{ALBUM}", "position_ms": 0}
    assert play.params == {"device_id": ours}
    assert pause.params == {"device_id": ours}
    assert seek.params == {"position_ms": "0", "device_id": ours}
    assert shuffle.params == {"state": "false", "device_id": ours}
    assert repeat.params == {"state": "off", "device_id": ours}
    assert [r.status for r in spotify_mock.requests] == [204] * 6
    with pytest.raises(NotFound):  # a device Spotify doesn't list
        await api.pause(device_id="0" * 40)


@pytest.mark.usefixtures("tokens")
async def test_bad_arguments_send_nothing(api: SpotifyWebApi, spotify_mock: SpotifyMock) -> None:
    with pytest.raises(ValueError):
        await api.saved_tracks(limit=51)
    with pytest.raises(ValueError):
        await api.saved_tracks(offset=-1)
    with pytest.raises(ValueError):
        await api.playlist("../me")  # an id can't add a path
    assert spotify_mock.requests == []


# --- Answers that aren't retried ---------------------------------------------------------------


@pytest.mark.usefixtures("tokens")
async def test_403_and_404_are_answers(
    api: SpotifyWebApi, fake_clock: FakeClock, spotify_mock: SpotifyMock, store: Store
) -> None:
    with pytest.raises(NoAccess) as no_access:
        await run(fake_clock, api.playlist_items(FOLLOWED))
    assert no_access.value.status == 403
    # Spotify-made playlists answer 404 (S0 row 28).
    with pytest.raises(NotFound):
        await run(fake_clock, api.playlist(SPOTIFY_MADE))
    with pytest.raises(NotFound):
        await run(fake_clock, api.playlist_items(SPOTIFY_MADE))
    spotify_mock.fail("GET /me", status=400)
    with pytest.raises(WebApiError) as bad:
        await run(fake_clock, api.me())
    assert bad.value.status == 400 and type(bad.value) is WebApiError
    assert [r.status for r in spotify_mock.requests] == [403, 404, 404, 400]
    assert [row["attempt"] for row in await usage_rows(store)] == [1, 1, 1, 1]


# --- Retries -----------------------------------------------------------------------------------


@pytest.mark.usefixtures("tokens")
async def test_a_429_waits_retry_after(
    api: SpotifyWebApi,
    spotify_mock: SpotifyMock,
    store: Store,
    fake_clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    start = fake_clock.monotonic()
    spotify_mock.fail("GET /me/tracks", status=429, retry_after_s=3)
    [page] = await drive(fake_clock, api.saved_tracks())
    assert page.total == 277
    assert times(spotify_mock, start) == [0.0, 3.0]
    rows = await usage_rows(store)
    assert [(r["status"], r["attempt"], r["retry_after_s"]) for r in rows] == [
        (429, 1, 3),
        (200, 2, None),
    ]
    [warning] = await warnings(store)
    assert warning["kind"] == "rate_limited"
    assert warning["message"] == "Web API: 429 on GET /me/tracks, Retry-After 3 s"
    assert "Web API: 429 on GET /me/tracks, Retry-After 3 s" in caplog.text


@pytest.mark.usefixtures("tokens")
async def test_a_429_holds_every_lane(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    start = fake_clock.monotonic()
    spotify_mock.fail("GET /me/tracks", status=429, retry_after_s=10)
    catalog = asyncio.ensure_future(api.saved_tracks())
    await until(lambda: spotify_mock.count() == 1)
    await drive(fake_clock, catalog, api.devices())  # a playback call waits for the hold too
    devices = [r for r in spotify_mock.requests if r.endpoint == "GET /me/player/devices"]
    assert devices[0].at is not None and devices[0].at - start >= 10.0
    assert times(spotify_mock, start)[0] == 0.0


@pytest.mark.usefixtures("tokens")
async def test_a_429_without_retry_after_waits_like_a_5xx(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    start = fake_clock.monotonic()
    spotify_mock.fail("GET /me", status=429)
    await drive(fake_clock, api.me())
    assert times(spotify_mock, start) == [0.0, 5.0]


@pytest.mark.usefixtures("tokens")
async def test_429s_give_up_after_three_retries(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    start = fake_clock.monotonic()
    spotify_mock.fail("GET /me", status=429, retry_after_s=2, times=4)
    with pytest.raises(RateLimited) as error:
        await drive(fake_clock, api.me())
    assert error.value.retry_after_s == 2
    assert times(spotify_mock, start) == [0.0, 2.0, 4.0, 6.0]


@pytest.mark.usefixtures("tokens")
async def test_a_retry_after_too_long_to_wait_raises_at_once_and_holds_the_rest(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock, store: Store
) -> None:
    start = fake_clock.monotonic()
    spotify_mock.fail("GET /me/playlists", status=429, retry_after_s=600)
    with pytest.raises(RateLimited) as error:
        await drive(fake_clock, api.my_playlists())
    assert error.value.retry_after_s == 600
    assert spotify_mock.count() == 1
    assert fake_clock.monotonic() == start  # nothing was waited out
    # While the hold lasts more than RATE_LIMIT_MAX_WAIT_S, calls are refused unsent.
    with pytest.raises(RateLimited) as refused:
        await api.devices()
    assert refused.value.retry_after_s == 600
    assert spotify_mock.count() == 1
    assert len(await usage_rows(store)) == 1
    # Once it's shorter, a call waits its turn instead.
    await fake_clock.advance(600 - RATE_LIMIT_MAX_WAIT_S + 1)
    await drive(fake_clock, api.devices())
    assert times(spotify_mock, start) == [0.0, 600.0]


@pytest.mark.usefixtures("tokens")
async def test_calls_waiting_for_their_turn_are_refused_once_a_long_hold_starts(
    config: Config,
    fake_clock: FakeClock,
    store: Store,
    auth: AuthStore,
    spotify_mock: SpotifyMock,
) -> None:
    # The listing stays in flight until the test lets it answer, so the other calls queue up
    # behind it: a catalog call and a playback call (S6's pause() would be one).
    in_flight = asyncio.Event()
    answer = asyncio.Event()
    inner = spotify_mock.transport()

    async def gated(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/me/playlists"):
            in_flight.set()
            await answer.wait()
        return await inner.handle_async_request(request)

    api = SpotifyWebApi(config, fake_clock, store, auth, transport=httpx.MockTransport(gated))
    start = fake_clock.monotonic()
    spotify_mock.fail("GET /me/playlists", status=429, retry_after_s=600)
    listing = asyncio.ensure_future(api.my_playlists())
    await asyncio.wait_for(in_flight.wait(), 2)
    liked = asyncio.ensure_future(api.saved_tracks())
    devices = asyncio.ensure_future(api.devices())
    await until(lambda: api.scheduler.waiting == 2)

    answer.set()  # the 429 with Retry-After 600 arrives
    for call in (listing, liked, devices):
        with pytest.raises(RateLimited) as error:
            await asyncio.wait_for(call, 2)
        assert error.value.retry_after_s == 600
    assert spotify_mock.endpoints() == ["GET /me/playlists"]  # the others were never sent
    assert fake_clock.monotonic() == start  # and nobody waited the hold out
    assert api.scheduler.waiting == 0
    assert len(await usage_rows(store)) == 1
    await api.aclose()


@pytest.mark.usefixtures("tokens")
async def test_the_resend_after_a_401_goes_on_with_the_same_retry_budget(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock, store: Store
) -> None:
    spotify_mock.fail("GET /me", status=503, times=3)
    spotify_mock.fail("GET /me", status=401)  # the token is refused mid-call: refreshed once
    spotify_mock.fail("GET /me", status=503, times=3)
    with pytest.raises(SpotifyUnavailable):
        await drive(fake_clock, api.me())
    rows = await usage_rows(store)
    assert [(r["endpoint"], r["status"], r["attempt"]) for r in rows] == [
        ("GET /me", 503, 1),
        ("GET /me", 503, 2),
        ("GET /me", 503, 3),
        ("GET /me", 401, 4),
        ("POST /api/token", 200, 1),
        ("GET /me", 503, 5),  # 3 retries were spent before the 401: no more after it
    ]


@pytest.mark.usefixtures("tokens")
async def test_5xx_waits_5_10_20_s_then_spotify_is_unavailable(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock, store: Store
) -> None:
    start = fake_clock.monotonic()
    spotify_mock.fail("GET /me/playlists", status=503, times=4)
    with pytest.raises(SpotifyUnavailable) as error:
        await drive(fake_clock, api.my_playlists())
    assert error.value.status == 503
    assert times(spotify_mock, start) == [0.0, 5.0, 15.0, 35.0]
    rows = await usage_rows(store)
    assert [(r["status"], r["attempt"]) for r in rows] == [(503, 1), (503, 2), (503, 3), (503, 4)]


@pytest.mark.usefixtures("tokens")
async def test_a_5xx_then_an_answer(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    start = fake_clock.monotonic()
    spotify_mock.fail("GET /me/playlists", status=502, times=2)
    [page] = await drive(fake_clock, api.my_playlists())
    assert page.total == 18
    assert times(spotify_mock, start) == [0.0, 5.0, 15.0]


@pytest.mark.usefixtures("tokens")
async def test_the_longer_wait_wins(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    start = fake_clock.monotonic()
    spotify_mock.fail("GET /me", status=503, retry_after_s=30)  # longer than 5 s: 30 s
    spotify_mock.fail("GET /me", status=503, retry_after_s=2)  # shorter than 10 s: 10 s
    spotify_mock.fail("GET /me", status=429, retry_after_s=40)  # a 429's Retry-After: 40 s
    await drive(fake_clock, api.me())
    assert times(spotify_mock, start) == [0.0, 30.0, 40.0, 80.0]


@pytest.mark.usefixtures("tokens")
async def test_timeouts_and_network_errors_are_retried(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock, store: Store
) -> None:
    start = fake_clock.monotonic()
    spotify_mock.timeout("GET /me/player/devices")
    spotify_mock.network_error("GET /me/player/devices")
    await drive(fake_clock, api.devices())
    assert times(spotify_mock, start) == [0.0, 5.0, 15.0]
    rows = await usage_rows(store)
    assert [(r["status"], r["error"], r["attempt"]) for r in rows] == [
        (None, "timeout", 1),
        (None, "network", 2),
        (200, None, 3),
    ]


@pytest.mark.usefixtures("tokens")
async def test_timeouts_give_up_too(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    spotify_mock.timeout("GET /me", times=4)
    with pytest.raises(SpotifyUnavailable) as error:
        await drive(fake_clock, api.me())
    assert error.value.status is None
    assert spotify_mock.count() == 4


# --- Tokens ------------------------------------------------------------------------------------


async def test_without_a_connection_nothing_is_sent(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, auth: AuthStore
) -> None:
    with pytest.raises(NotConnected):
        await api.me()
    await auth.set_client_id(spotify_mock.client_id)  # a Client ID, but no token yet
    with pytest.raises(NotConnected):
        await api.devices()
    assert spotify_mock.requests == []


async def test_a_401_refreshes_the_token_once_and_retries(
    api: SpotifyWebApi,
    fake_clock: FakeClock,
    spotify_mock: SpotifyMock,
    auth: AuthStore,
    store: Store,
    tokens: tuple[str, str],
) -> None:
    access, refresh = tokens
    spotify_mock.expire_access_tokens()
    assert (await run(fake_clock, api.me())).id == spotify_mock.catalog.user.id
    assert spotify_mock.endpoints() == ["GET /me", "POST /api/token", "GET /me"]
    assert [r.status for r in spotify_mock.requests] == [401, 200, 200]
    form = spotify_mock.requests[1].form
    assert form == {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": spotify_mock.client_id,
    }
    row = await auth.load()
    assert row.access_token != access and row.access_token in spotify_mock.access_tokens
    assert row.refresh_token != refresh  # Spotify rotated it, and the new one is kept
    assert row.refresh_token in spotify_mock.refresh_tokens
    assert spotify_mock.requests[2].authorization == f"Bearer {row.access_token}"
    rows = await usage_rows(store)
    assert [(r["endpoint"], r["status"], r["attempt"]) for r in rows] == [
        ("GET /me", 401, 1),
        ("POST /api/token", 200, 1),
        ("GET /me", 200, 2),
    ]
    # The rotated refresh token works for the next refresh.
    spotify_mock.expire_access_tokens()
    await run(fake_clock, api.me())
    assert spotify_mock.count("POST /api/token") == 2


async def test_a_second_401_is_not_refreshed_again(
    api: SpotifyWebApi, fake_clock: FakeClock, spotify_mock: SpotifyMock, tokens: tuple[str, str]
) -> None:
    spotify_mock.fail("GET /me", status=401, times=2)
    with pytest.raises(WebApiError) as error:
        await run(fake_clock, api.me())
    assert error.value.status == 401
    assert spotify_mock.endpoints() == ["GET /me", "POST /api/token", "GET /me"]


async def test_the_token_is_refreshed_before_it_expires(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock, tokens: tuple[str, str]
) -> None:
    await api.me()
    await fake_clock.advance(spotify_mock.access_token_ttl_s - 59)  # 59 s left: under 60 s
    await api.me()
    assert spotify_mock.endpoints() == ["GET /me", "POST /api/token", "GET /me"]
    assert [r.status for r in spotify_mock.requests] == [200, 200, 200]


async def test_a_refresh_without_a_new_refresh_token_keeps_the_old_one(
    api: SpotifyWebApi,
    fake_clock: FakeClock,
    spotify_mock: SpotifyMock,
    auth: AuthStore,
    tokens: tuple[str, str],
) -> None:
    spotify_mock.rotate_refresh_tokens = False
    spotify_mock.expire_access_tokens()
    await run(fake_clock, api.me())
    assert (await auth.load()).refresh_token == tokens[1]


async def test_concurrent_callers_share_one_refresh(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock, tokens: tuple[str, str]
) -> None:
    spotify_mock.expire_access_tokens()
    await drive(fake_clock, api.me(), api.devices(), api.my_playlists())
    assert spotify_mock.count("POST /api/token") == 1
    assert spotify_mock.count() == 1 + 3 + 3  # three 401s, one refresh, three answers


async def test_a_refresh_is_retried_on_5xx(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock, tokens: tuple[str, str]
) -> None:
    start = fake_clock.monotonic()
    spotify_mock.expire_access_tokens()
    spotify_mock.fail("POST /api/token", status=503)
    await drive(fake_clock, api.me())
    assert spotify_mock.endpoints() == [
        "GET /me",
        "POST /api/token",
        "POST /api/token",
        "GET /me",
    ]
    assert times(spotify_mock, start) == [0.0, 0.0, 5.0, 5.0]


async def reconnect_while_the_refresh_waits(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, auth: AuthStore
) -> tuple[asyncio.Future[ports.SpotifyUser], str, str]:
    """GET /me's token is refused, and the refresh's first answer is a 503: it waits 5 s to try
    again, outside any lock. Step 5 stores a new authorization meanwhile. Returns the call and
    the new (access, refresh) pair."""
    spotify_mock.expire_access_tokens()
    spotify_mock.fail("POST /api/token", status=503)
    call = asyncio.ensure_future(api.me())
    await until(lambda: spotify_mock.count("POST /api/token") == 1)
    access, refresh = spotify_mock.issue_tokens()
    grant = TokenGrant(access, refresh, spotify_mock.access_token_ttl_s, SCOPES)
    await auth.save_grant(spotify_mock.client_id, grant)
    return call, access, refresh


async def test_an_old_tokens_invalid_grant_leaves_a_reconnect_alone(
    api: SpotifyWebApi,
    spotify_mock: SpotifyMock,
    fake_clock: FakeClock,
    auth: AuthStore,
    tokens: tuple[str, str],
) -> None:
    spotify_mock.revoke_refresh_tokens()  # the old authorization is over: why you reconnect
    call, access, refresh = await reconnect_while_the_refresh_waits(api, spotify_mock, auth)

    user = await run(fake_clock, call)

    assert user.id == spotify_mock.catalog.user.id
    row = await auth.load()
    assert row.invalid_grant_at is None  # the new connection isn't marked expired
    assert (row.access_token, row.refresh_token) == (access, refresh)
    assert spotify_mock.endpoints() == ["GET /me", "POST /api/token", "POST /api/token", "GET /me"]
    assert spotify_mock.requests[-1].authorization == f"Bearer {access}"


async def test_a_refresh_that_ends_after_a_reconnect_does_not_overwrite_it(
    api: SpotifyWebApi,
    spotify_mock: SpotifyMock,
    fake_clock: FakeClock,
    auth: AuthStore,
    tokens: tuple[str, str],
) -> None:
    call, access, refresh = await reconnect_while_the_refresh_waits(api, spotify_mock, auth)

    await run(fake_clock, call)  # the old token's refresh succeeds, but comes too late

    row = await auth.load()
    assert (row.access_token, row.refresh_token) == (access, refresh)
    assert spotify_mock.requests[-1].authorization == f"Bearer {access}"


async def test_invalid_grant_expires_the_connection(
    api: SpotifyWebApi,
    spotify_mock: SpotifyMock,
    auth: AuthStore,
    store: Store,
    tokens: tuple[str, str],
) -> None:
    changes: list[str] = []

    async def listen(change: str) -> None:
        changes.append(change)

    auth.add_listener(listen)
    spotify_mock.expire_access_tokens()
    spotify_mock.revoke_refresh_tokens()  # the 6-month authorization is over
    with pytest.raises(ConnectionExpired):
        await api.me()
    assert changes == ["expired"]
    row = await auth.load()
    assert row.invalid_grant_at is not None and row.has_token
    usage = await usage_rows(store)
    assert [(r["endpoint"], r["status"], r["error"]) for r in usage] == [
        ("GET /me", 401, None),
        ("POST /api/token", 400, "invalid_grant"),
    ]
    # From now on, nothing is sent until you reconnect.
    with pytest.raises(ConnectionExpired):
        await api.devices()
    assert spotify_mock.count() == 2
    assert changes == ["expired"]


async def test_another_refusal_of_the_refresh_is_an_error_but_not_an_expiry(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, auth: AuthStore, tokens: tuple[str, str]
) -> None:
    spotify_mock.expire_access_tokens()
    spotify_mock.fail(
        "POST /api/token",
        status=400,
        body={"error": "invalid_client", "error_description": "Invalid client"},
    )
    with pytest.raises(WebApiError) as error:
        await api.me()
    assert type(error.value) is WebApiError and error.value.status == 400
    assert "invalid_client" in str(error.value)
    assert (await auth.load()).invalid_grant_at is None


async def test_exchange_code_on_the_mock(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, store: Store
) -> None:
    import base64
    import hashlib

    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    code = spotify_mock.authorize(code_challenge=challenge.decode().rstrip("="))
    grant = await api.exchange_code(
        client_id=spotify_mock.client_id,
        code=code,
        code_verifier=verifier,
        redirect_uri=REDIRECT_URI,
    )
    assert grant.access_token in spotify_mock.access_tokens
    assert grant.refresh_token in spotify_mock.refresh_tokens
    assert grant.scopes == SCOPES and grant.expires_in_s == 3600
    with pytest.raises(TokenExchangeFailed) as error:  # a code works once
        await api.exchange_code(
            client_id=spotify_mock.client_id,
            code=code,
            code_verifier=verifier,
            redirect_uri=REDIRECT_URI,
        )
    assert error.value.status == 400
    assert code not in str(error.value) and verifier not in str(error.value)
    rows = await usage_rows(store)
    assert [(r["endpoint"], r["status"], r["scope_kind"]) for r in rows] == [
        ("POST /api/token", 200, "setup"),
        ("POST /api/token", 400, "setup"),
    ]


# --- The scheduler, through the port -------------------------------------------------------------


@pytest.mark.usefixtures("tokens")
async def test_catalog_calls_start_250_ms_apart(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    start = fake_clock.monotonic()
    await drive(fake_clock, *(api.saved_tracks(offset=50 * n) for n in range(4)))
    assert times(spotify_mock, start) == [0.0, 0.25, 0.5, 0.75]


@pytest.mark.usefixtures("tokens")
async def test_playback_calls_jump_the_catalog_queue(
    api: SpotifyWebApi, spotify_mock: SpotifyMock, fake_clock: FakeClock
) -> None:
    start = fake_clock.monotonic()
    catalog = [asyncio.ensure_future(api.saved_tracks(offset=50 * n)) for n in range(3)]
    await until(lambda: spotify_mock.count() == 1)  # the first catalog call is answered
    ours = our_device_id(spotify_mock)
    playback = asyncio.ensure_future(api.pause(device_id=ours))
    await until(lambda: spotify_mock.count() == 2)
    await drive(fake_clock, *catalog, playback)
    assert spotify_mock.endpoints() == [
        "GET /me/tracks",
        "PUT /me/player/pause",
        "GET /me/tracks",
        "GET /me/tracks",
    ]
    # The playback call wasn't delayed by the catalog spacing.
    assert times(spotify_mock, start) == [0.0, 0.0, 0.25, 0.5]


# --- The usage log -----------------------------------------------------------------------------


async def test_rows_name_templates_never_ids_or_tokens(
    api: SpotifyWebApi,
    fake_clock: FakeClock,
    spotify_mock: SpotifyMock,
    store: Store,
    tokens: tuple[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    scope = ApiScope("refresh", 7)
    await run(fake_clock, api.playlist(OWNED, scope=scope))
    await run(fake_clock, api.playlist_items(OWNED, scope=scope))
    await run(fake_clock, api.album_tracks(ALBUM, scope=scope))
    for _ in range(5):  # five 404s in a row: a warning that names the endpoint
        with pytest.raises(NotFound):
            await run(fake_clock, api.playlist(SPOTIFY_MADE, scope=scope))
    spotify_mock.expire_access_tokens()
    await run(fake_clock, api.me(scope=scope))
    rows = await usage_rows(store)
    assert [r["endpoint"] for r in rows[:3]] == [
        "GET /playlists/{id}",
        "GET /playlists/{id}/items",
        "GET /albums/{id}/tracks",
    ]
    assert {(r["scope_kind"], r["scope_id"]) for r in rows} == {("refresh", 7)}
    stored = await store.fetchall("SELECT * FROM api_requests")
    stored += await store.fetchall("SELECT * FROM api_warnings")
    row = await auth_row(store)
    secrets = [OWNED, ALBUM, SPOTIFY_MADE, *tokens, *row]
    for value in (v for r in stored for v in tuple(r)):
        assert not any(secret in str(value) for secret in secrets), value
    assert not any(token in caplog.text for token in [*tokens, *row])
    messages = [w["message"] for w in await warnings(store)]
    assert messages == [
        "Web API: 5 4xx answers in a row from GET /playlists/{id} (the last one 404)"
    ]


async def auth_row(store: Store) -> list[str]:
    """The tokens stored now."""
    row = await store.fetchone("SELECT access_token, refresh_token FROM spotify_auth")
    assert row is not None
    return [row["access_token"], row["refresh_token"]]


async def test_a_usage_log_that_cannot_be_written_does_not_fail_the_call(
    api: SpotifyWebApi,
    spotify_mock: SpotifyMock,
    store: Store,
    tokens: tuple[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await store.execute("DROP TABLE api_warnings")
    await store.execute("ALTER TABLE api_requests RENAME TO api_requests_gone")
    assert (await api.me()).id == spotify_mock.catalog.user.id
    assert "the usage log couldn't record GET /me" in caplog.text
