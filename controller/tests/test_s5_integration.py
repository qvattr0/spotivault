"""S5's parts together, on the fake ports: the catalog refresh, the Library, Albums, Spytify's index
and the backlog read the same facts. Each builder's own tests stand in for the others; these
don't."""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from spotivault.fake.world import FakeWorld, world_of
from spotivault.matching import track_key
from spotivault.ports import TokenGrant
from spotivault.services import Services
from test_catalog_refresh import PLAYLIST_3, warm

CLIENT_ID = "0123456789abcdef0123456789abcdef"
GRANT = TokenGrant(access_token="t" * 10, refresh_token="r" * 10, expires_in_s=3600, scopes=())
ARTIST = "Integration Artist"


@pytest.fixture
async def connected(running_app: FastAPI, services: Services) -> FakeWorld:
    """A stored connection and a first catalog refresh, as the end of wizard step 5 leaves them."""
    world = world_of(services.ports)
    warm(world.catalog)
    await services.auth.set_client_id(CLIENT_ID)
    await services.auth.save_grant(CLIENT_ID, GRANT)
    await services.auth.set_account(world.catalog.user)
    result = await services.catalog.refresh(trigger="setup")
    assert result.outcome == "ok"
    return world


def write_index(music_dir: Path, keys: list[str]) -> None:
    """Spytify's index with these keys, each with a file that exists."""
    lines = []
    for number, key in enumerate(keys):
        path = music_dir / f"recorded-{number}.ogg"
        path.write_bytes(b"audio")
        lines.append(json.dumps({"Key": key, "Path": str(path)}))
    index = music_dir / ".spytify" / "recorded.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def test_what_is_recorded_reaches_the_library_albums_and_the_backlog(
    connected: FakeWorld, services: Services, music_dir: Path
) -> None:
    album = connected.catalog.add_album(
        "Integration Album",
        artist=ARTIST,
        tracks=[("First Light", 100_000), ("Second Wind", 200_000)],
    )
    added = await services.albums.add(ids=[album.album.id])
    assert [item.id for item in added.added] == [album.album.id]

    playlist = await services.library.tracks(PLAYLIST_3)
    first = playlist.tracks[0]
    assert first.state == "new" and first.artists

    before = await services.backlog.update()

    write_index(
        services.config.music_dir,
        [track_key(ARTIST, "First Light"), track_key(first.artists[0], first.title)],
    )
    services.matching.invalidate()

    # Albums: the count and the track states come from the index.
    album_model = await services.albums.album(album.album.id)
    assert album_model is not None
    assert (album_model.total, album_model.recorded) == (2, 1)
    states = [track.state for track in (await services.albums.tracks(album.album.id)).tracks]
    assert states == ["recorded", "missing"]

    # The Library: the same index, for an owned playlist's stored list.
    item = await services.library.item(PLAYLIST_3)
    assert item is not None and item.recorded >= 1
    assert (await services.library.tracks(PLAYLIST_3)).tracks[0].state == "recorded"

    # The backlog counts both, and forgets the album once it leaves the page.
    after = await services.backlog.update()
    assert after.tracks_total == before.tracks_total
    assert after.tracks_recorded >= before.tracks_recorded + 2
    await services.albums.remove(album.album.id)
    removed = await services.backlog.snapshot()
    assert removed is not None
    assert removed.tracks_total == after.tracks_total - 2
    assert removed.tracks_recorded == after.tracks_recorded - 1


async def test_untracking_and_removing_change_the_backlog(
    connected: FakeWorld, services: Services
) -> None:
    before = await services.backlog.update()
    liked = await services.library.item("liked")
    assert liked is not None and liked.tracked and liked.total

    await services.library.set_tracked("liked", False)
    untracked = await services.backlog.snapshot()
    assert untracked is not None
    assert untracked.tracks_total < before.tracks_total
    assert untracked.items_to_record == before.items_to_record - 1
