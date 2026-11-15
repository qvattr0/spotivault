"""fake/webapi.py: the fake Web API answers as the S0 captures did (2026 Development Mode)."""

import pytest

from fake_helpers import make_world
from portcheck import assert_implements
from spotivault import ports
from spotivault.config import Config
from spotivault.fake import FakeWorld
from spotivault.fake.clock import FakeClock
from spotivault.fake.webapi import SCOPES, FakeWebApi
from spotivault.ports import (
    ConnectionExpired,
    NoAccess,
    NotConnected,
    NotFound,
    RateLimited,
    TokenExchangeFailed,
    WebApiError,
)

PLAYLIST_7 = "7aUxnM625jyHAtd7b7xZLg"


@pytest.fixture
def world(config: Config, fake_clock: FakeClock) -> FakeWorld:
    return make_world(config, fake_clock, library="fixtures")


def test_it_implements_the_port() -> None:
    assert_implements(FakeWebApi, ports.WebApi)


async def test_nothing_answers_before_the_code_is_exchanged(
    config: Config, fake_clock: FakeClock
) -> None:
    world = make_world(config, fake_clock, scenario="fresh", library="fixtures")
    api = world.webapi
    with pytest.raises(NotConnected):
        await api.me()
    with pytest.raises(TokenExchangeFailed):
        await api.exchange_code(
            client_id="id", code="bad-code", code_verifier="v", redirect_uri="r"
        )
    grant = await api.exchange_code(
        client_id="id", code="AQB-good", code_verifier="v", redirect_uri="r"
    )
    assert grant.scopes == SCOPES and grant.refresh_token
    assert (await api.me()).id == "user2"
    assert api.endpoints() == ["GET /me", "POST /api/token", "POST /api/token", "GET /me"]
    assert api.calls[1].scope == ports.SETUP


async def test_listings_page_with_the_real_totals(world: FakeWorld) -> None:
    api = world.webapi
    first = await api.my_playlists(limit=10)
    assert (first.total, len(first.items), first.next_offset) == (18, 10, 10)
    rest = await api.my_playlists(offset=10, limit=50)
    assert (len(rest.items), rest.next_offset) == (8, None)
    liked = await api.saved_tracks(limit=50)
    assert liked.total == 277 and liked.items[0].track.name == "Track 2"
    albums = await api.saved_albums(limit=2)
    album = albums.items[0].album
    assert albums.total == 124 and album.tracks is not None
    assert album.tracks.total == album.total_tracks == len(album.tracks.items)
    tracks = await api.album_tracks(album.id, limit=2)
    assert tracks.total == album.total_tracks and tracks.next_offset == 2
    with pytest.raises(WebApiError) as bad:
        await api.my_playlists(limit=51)
    assert bad.value.status == 400


async def test_item_access(world: FakeWorld) -> None:
    api = world.webapi
    items = await api.playlist_items(PLAYLIST_7, limit=50)
    assert items.total == 300 and items.items[2].track is not None
    assert items.items[2].track.is_playable is False
    followed = next(p for p in world.catalog.library_playlists() if p.access == "followed")
    with pytest.raises(NoAccess):
        await api.playlist_items(followed.playlist.id)
    assert (await api.playlist(followed.playlist.id)).total is None  # no `items` field
    assert followed.playlist.total == 35  # but /me/playlists has it (row 20)
    linked = next(p for p in world.catalog.playlists.values() if p.access == "linked")
    preview = await api.playlist(linked.playlist.id)
    assert preview.name == linked.playlist.name and preview.total is None
    with pytest.raises(NoAccess):
        await api.playlist_items(linked.playlist.id)
    made = next(p for p in world.catalog.playlists.values() if p.access == "spotify")
    for call in (api.playlist(made.playlist.id), api.playlist_items(made.playlist.id)):
        with pytest.raises(NotFound):
            await call
    with pytest.raises(NotFound):
        await api.album_tracks("nope")


async def test_devices_list_ours_only_while_the_client_runs_logged_in(world: FakeWorld) -> None:
    api = world.webapi
    names = [d.name for d in await api.devices()]
    assert names[0] == "spotivault-test" and "Pixel 9" in names
    world.client.log_out()
    assert "spotivault-test" not in [d.name for d in await api.devices()]
    world.client.log_in()
    world.client.stop()
    assert "spotivault-test" not in [d.name for d in await api.devices()]


async def test_play_reports_the_relinked_id_and_the_liked_alias(world: FakeWorld) -> None:
    api = world.webapi
    ours = world.catalog.our_device.id
    assert await api.player_state() is None
    entry = world.catalog.playlists[PLAYLIST_7].entries[0]
    assert entry.track is not None
    await api.play(device_id=ours, context_uri=f"spotify:playlist:{PLAYLIST_7}")
    state = await api.player_state()
    assert state is not None and state.is_playing and state.device is not None
    assert state.device.is_active and state.device.name == "spotivault-test"
    assert state.track_id == entry.relinked_id != entry.track.id  # row 18
    assert world.player.metadata().track_id == entry.track.id  # MPRIS has the entry's own
    await api.play(device_id=ours, context_uri=world.catalog.liked_uri)
    state = await api.player_state()
    assert state is not None and state.context_uri == "spotify:playlist:37i9dQZF1FLikedSongs01"


async def test_liked_songs_context_forms(world: FakeWorld) -> None:
    api = world.webapi
    ours = world.catalog.our_device.id
    await api.play(device_id=ours, context_uri="spotify:collection:tracks")
    assert world.player.status == "Stopped"  # 204, and nothing plays (row 17)
    with pytest.raises(WebApiError) as bad:
        await api.play(device_id=ours, context_uri="spotify:user:user2:collection:tracks")
    assert bad.value.status == 400


async def test_an_offset_at_an_unplayable_entry_plays_another(world: FakeWorld) -> None:
    api = world.webapi
    entries = world.catalog.playlists[PLAYLIST_7].entries
    assert entries[2].track is not None
    await api.play(
        device_id=world.catalog.our_device.id,
        context_uri=f"spotify:playlist:{PLAYLIST_7}",
        offset_uri=entries[2].track.uri,
    )
    assert world.player.index == 3


async def test_a_play_on_an_unknown_device_or_context_is_404(world: FakeWorld) -> None:
    api = world.webapi
    with pytest.raises(NotFound):
        await api.play(device_id="nope", context_uri=f"spotify:playlist:{PLAYLIST_7}")
    with pytest.raises(NotFound):
        await api.play(device_id=world.catalog.our_device.id, context_uri="spotify:album:nope")


async def test_tests_can_make_calls_fail(world: FakeWorld) -> None:
    api = world.webapi
    api.failures = [RateLimited("slow down", retry_after_s=7)]
    with pytest.raises(RateLimited) as limited:
        await api.my_playlists()
    assert limited.value.retry_after_s == 7
    assert (await api.my_playlists()).total == 18
    api.expired = True
    with pytest.raises(ConnectionExpired):
        await api.devices()


async def test_the_player_controls(world: FakeWorld) -> None:
    api = world.webapi
    ours = world.catalog.our_device.id
    album = world.catalog.saved_albums()[0]
    await api.set_shuffle(True, device_id=ours)
    await api.set_repeat("context", device_id=ours)
    assert (world.player.shuffle, world.player.repeat) == (True, "context")
    await api.set_shuffle(False, device_id=ours)
    await api.set_repeat("off", device_id=ours)
    await api.play(device_id=ours, context_uri=album.album.uri)
    await api.seek(30_000, device_id=ours)
    assert world.player.position_ms() == 30_000
    await api.pause(device_id=ours)
    assert world.player.status == "Paused"
    await api.pause(device_id=ours)  # pausing a paused player is no error
