"""fake/player.py and fake/mpris.py: the simulated client plays as FINDINGS.md found it does.

The run engine (S6) trusts these behaviours, so each is tested directly.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from fake_helpers import make_world
from portcheck import assert_implements
from spotivault import ports
from spotivault.config import Config
from spotivault.fake import FakeWorld
from spotivault.fake.catalog import CatalogAlbum
from spotivault.fake.clock import FakeClock
from spotivault.fake.mpris import SimMpris
from spotivault.ports import MprisChange, MprisNoClient


@pytest.fixture
def world(config: Config, fake_clock: FakeClock) -> FakeWorld:
    return make_world(config, fake_clock)


@pytest.fixture
def album(world: FakeWorld) -> CatalogAlbum:
    tracks = [("Passage", 87_000), ("Distant Peak", 90_000), ("Now And Then", 102_000)]
    return world.catalog.add_album("Elsewhere", artist="fakename", tracks=tracks)


class Changes:
    """The MPRIS changes a subscriber sees, as (kind, value) pairs."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, object]] = []

    def add(self, change: MprisChange) -> None:
        if change.metadata is not None:
            self.seen.append(("metadata", change.metadata.title))
        if change.playback_status is not None:
            self.seen.append(("status", change.playback_status))
        if change.seeked_ms is not None:
            self.seen.append(("seeked", change.seeked_ms))
        if change.owner_present is not None:
            self.seen.append(("owner", change.owner_present))


@pytest.fixture
async def changes(world: FakeWorld) -> AsyncIterator[Changes]:
    collected = Changes()

    async def read() -> None:
        async with world.mpris.subscribe() as stream:
            async for change in stream:
                collected.add(change)

    task = asyncio.ensure_future(read())
    await asyncio.sleep(0)
    yield collected
    task.cancel()


async def play(world: FakeWorld, album: CatalogAlbum, index: int = 0) -> None:
    track = album.entries[index].track
    assert track is not None
    await world.webapi.play(
        device_id=world.catalog.our_device.id, context_uri=album.album.uri, offset_uri=track.uri
    )


def test_it_implements_the_port() -> None:
    assert_implements(SimMpris, ports.Mpris)


async def test_tracks_play_in_clock_time(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, changes: Changes
) -> None:
    await play(world, album)
    await fake_clock.advance(10)
    assert await world.mpris.position_ms() == 10_000
    meta = await world.mpris.metadata()
    assert meta is not None and meta.title == "Passage" and meta.artists == ("fakename",)
    assert meta.trackid == f"/com/spotify/track/{meta.track_id}"
    await fake_clock.advance(80)
    assert (await world.mpris.metadata()).title == "Distant Peak"  # type: ignore[union-attr]
    assert changes.seen == [
        ("metadata", "Passage"),
        ("status", "Playing"),
        ("metadata", "Distant Peak"),
    ]


async def test_at_the_end_track_1_loads_paused_with_its_metadata_first(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, changes: Changes
) -> None:
    await play(world, album, 2)
    await fake_clock.advance(103)
    assert world.player.status == "Paused"
    assert (await world.mpris.metadata()).title == "Passage"  # type: ignore[union-attr]
    assert await world.mpris.position_ms() == 0
    assert changes.seen[-2:] == [("metadata", "Passage"), ("status", "Paused")]
    await fake_clock.advance(60)
    assert world.player.status == "Paused"  # never Stopped, and it stays there


async def test_next_on_the_paused_track_1_plays_track_2(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock
) -> None:
    await play(world, album, 2)
    await fake_clock.advance(103)
    await world.mpris.next()
    assert world.player.status == "Playing"  # Spytify bug 1's restart
    assert (await world.mpris.metadata()).title == "Distant Peak"  # type: ignore[union-attr]


async def test_next_on_the_last_track_ends_the_context(
    world: FakeWorld, album: CatalogAlbum
) -> None:
    await play(world, album, 2)
    await world.mpris.next()
    assert world.player.status == "Paused" and world.player.index == 0


async def test_a_one_track_album_stays_on_its_track_at_0(
    world: FakeWorld, fake_clock: FakeClock, changes: Changes
) -> None:
    single = world.catalog.add_album("Panspermia", tracks=[("Panspermia", 188_000)])
    await play(world, single)
    await fake_clock.advance(189)
    assert world.player.status == "Paused" and await world.mpris.position_ms() == 0
    await fake_clock.settle()
    assert changes.seen[-2:] == [("seeked", 0), ("status", "Paused")]
    await world.mpris.next()  # FINDINGS: Next at the end changes nothing
    assert world.player.status == "Paused" and world.player.index == 0


async def test_unplayable_entries_are_passed_over(world: FakeWorld, fake_clock: FakeClock) -> None:
    album = world.catalog.add_album("Gaps", tracks=3, unplayable=(1,))
    await play(world, album)
    await fake_clock.advance(91)
    assert world.player.index == 2


async def test_playing_the_loaded_track_again_only_seeks(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, changes: Changes
) -> None:
    await play(world, album, 1)
    await fake_clock.advance(5)
    await world.webapi.pause(device_id=world.catalog.our_device.id)
    await play(world, album, 1)  # the retry of an interrupted item
    await fake_clock.settle()
    assert changes.seen[-2:] == [("seeked", 0), ("status", "Playing")]  # no new metadata


async def test_open_uri(world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock) -> None:
    await world.mpris.open_uri(album.album.uri)
    assert world.player.status == "Playing" and world.player.index == 0
    track = album.entries[1].track
    assert track is not None
    await world.mpris.open_uri(track.uri)
    state = await world.webapi.player_state()
    assert state is not None and state.context_uri == album.album.uri  # its album (row 9)
    await fake_clock.advance(91)
    assert world.player.index == 1  # and it starts again at its end
    await world.mpris.open_uri("spotify:playlist:unknown")  # does nothing
    assert world.player.index == 1


async def test_previous(world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock) -> None:
    await play(world, album, 1)
    await fake_clock.advance(10)
    await world.mpris.previous()
    assert world.player.index == 1 and world.player.position_ms() == 0
    await world.mpris.previous()
    assert world.player.index == 0


async def test_repeat_and_shuffle(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock
) -> None:
    ours = world.catalog.our_device.id
    await world.webapi.set_repeat("context", device_id=ours)
    await play(world, album, 2)
    await fake_clock.advance(103)
    assert world.player.status == "Playing" and world.player.index == 0
    await world.webapi.set_repeat("track", device_id=ours)
    await fake_clock.advance(88)
    assert world.player.index == 0
    await world.webapi.set_repeat("off", device_id=ours)
    await world.webapi.set_shuffle(True, device_id=ours)
    await fake_clock.advance(88)
    assert world.player.index in (1, 2)


async def test_autoplay_moves_the_context_on(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock
) -> None:
    world.player.autoplay = True
    await play(world, album, 2)
    await fake_clock.advance(103)
    state = await world.webapi.player_state()
    assert state is not None and state.is_playing and state.context_uri != album.album.uri


async def test_another_device_takes_over_and_a_play_takes_it_back(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, changes: Changes
) -> None:
    await play(world, album)
    await fake_clock.advance(30)
    world.player.take_over("Pixel 9")
    await fake_clock.settle()
    assert changes.seen[-1] == ("status", "Paused")
    state = await world.webapi.player_state()
    assert state is not None and state.device is not None
    assert (state.device.name, state.is_playing, state.context_uri) == (
        "Pixel 9",
        True,
        album.album.uri,
    )
    await fake_clock.advance(5)
    assert state.progress_ms == 30_000 and (await world.webapi.player_state()).progress_ms == 35_000  # type: ignore[union-attr]
    actives = {d.name: d.is_active for d in await world.webapi.devices()}
    assert actives["Pixel 9"] and not actives["spotivault-test"]
    await play(world, album, 0)  # Resume
    state = await world.webapi.player_state()
    assert state is not None and state.device is not None and state.device.name == "spotivault-test"


async def test_another_device_already_playing(world: FakeWorld) -> None:
    world.player.play_elsewhere("Living Room")
    state = await world.webapi.player_state()
    assert state is not None and state.is_playing and state.device is not None
    assert state.device.name == "Living Room"
    assert world.player.status == "Stopped"
    world.player.stop_elsewhere()
    state = await world.webapi.player_state()
    assert state is not None and not state.is_playing


async def test_a_logged_out_client_is_on_the_bus_with_nothing_loaded(
    config: Config, fake_clock: FakeClock
) -> None:
    world = make_world(config, fake_clock)
    world.client.log_out()
    assert await world.mpris.owner_present()
    assert await world.mpris.playback_status() == "Stopped"
    assert await world.mpris.metadata() is None
    await world.mpris.play()  # nothing to play
    assert world.player.status == "Stopped"
    assert world.player.window_title() == "Spotify"


async def test_mpris_without_the_client(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, changes: Changes
) -> None:
    await play(world, album)
    world.client.stop()
    await fake_clock.settle()
    assert changes.seen[-1] == ("owner", False)
    assert await world.mpris.playback_status() is None and await world.mpris.metadata() is None
    with pytest.raises(MprisNoClient):
        await world.mpris.pause()


async def test_the_window_title_follows_the_player(world: FakeWorld, album: CatalogAlbum) -> None:
    assert world.player.window_title() == "Spotify Premium"
    await play(world, album)
    assert world.player.window_title() == "fakename - Passage"
    world.client.stop()
    assert world.player.window_title() is None


async def test_a_quit_client_comes_back_paused_where_it_was(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock
) -> None:
    await play(world, album)
    await fake_clock.advance(10)
    await world.mpris.quit()
    assert not await world.mpris.owner_present()
    await fake_clock.advance(world.client.restart_delay_s)
    assert await world.mpris.owner_present()
    assert world.player.status == "Paused" and world.player.position_ms() == 10_000
    assert world.mpris.calls == ["Quit"]
