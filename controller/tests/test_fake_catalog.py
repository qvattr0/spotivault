"""fake/catalog.py and fake/fixtures.py: the fake library is the S0 capture, filled out."""

from pathlib import Path

import pytest

from spotivault.fake import fixtures
from spotivault.fake.catalog import LIKED_ALIAS_ID, USER_ID, Catalog

PROTOTYPE_FIXTURES = Path(__file__).parents[2] / "prototype" / "fixtures" / "webapi"
PLAYLIST_7 = "7aUxnM625jyHAtd7b7xZLg"
S0_UNPLAYABLE = {2, 20, 70, 96, 123, 136, 156, 161, 170, 185, 187, 225, 236, 239, 257, 269}
S0_UNPLAYABLE |= {274, 275, 282, 288}


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog(device_name="spotivault-test")


@pytest.mark.parametrize("name", fixtures.FIXTURE_FILES)
def test_the_packaged_fixtures_match_the_s0_captures(name: str) -> None:
    original = PROTOTYPE_FIXTURES / name
    if not original.exists():
        pytest.skip("prototype/ isn't checked out next to controller/")
    assert (fixtures.DATA_DIR / name).read_bytes() == original.read_bytes()


def test_the_library_has_the_captured_totals(catalog: Catalog) -> None:
    library = catalog.library_playlists()
    assert len(library) == 18
    assert [p.access for p in library].count("followed") == 1
    assert all(p.playlist.owner_id == USER_ID for p in library if p.access == "owned")
    for item in library:
        assert len(item.entries) == item.playlist.total
    assert len(catalog.liked) == 277
    assert len(catalog.saved_albums()) == 124
    for album in catalog.saved_albums()[:5]:
        assert len(album.entries) == album.album.total_tracks


def test_saved_albums_and_liked_songs_are_newest_first(catalog: Catalog) -> None:
    albums = catalog.saved_albums()
    assert [a.album.name for a in albums[:2]] == ["Album 1", "Album 2"]  # the captured ones
    dates = [a.added_at or "" for a in albums]
    assert dates == sorted(dates, reverse=True)
    liked = [e.added_at or "" for e in catalog.liked]
    assert liked == sorted(liked, reverse=True)
    assert catalog.liked[0].track is not None and catalog.liked[0].track.name == "Track 2"


def test_playlist_7_has_s0s_unplayable_entries_and_a_relinked_first_entry(
    catalog: Catalog,
) -> None:
    entries = catalog.playlists[PLAYLIST_7].entries
    assert len(entries) == 300
    unplayable = {i for i, e in enumerate(entries) if not e.playable}
    assert unplayable == S0_UNPLAYABLE
    assert entries[0].track is not None and entries[0].track.name == "Track 26"  # captured
    assert entries[0].relinked_id is not None and entries[0].relinked_id != entries[0].track.id
    assert entries[22].relinked_id is None


def test_playlist_3_has_a_local_file_an_episode_and_an_empty_entry(catalog: Catalog) -> None:
    item = next(p for p in catalog.playlists.values() if p.playlist.name == "Playlist 3")
    local, episode, empty = item.entries[4], item.entries[8], item.entries[11]
    assert local.track is not None and local.track.is_local and not local.playable
    assert episode.track is not None and episode.track.is_episode and episode.playable
    assert empty.track is None and not empty.playable


def test_generated_ids_are_the_same_on_every_build(catalog: Catalog) -> None:
    again = Catalog(device_name="spotivault-test")
    assert [p.id for p in (i.playlist for i in again.library_playlists())] == [
        i.playlist.id for i in catalog.library_playlists()
    ]
    assert [e.track.id for e in again.liked if e.track] == [
        e.track.id for e in catalog.liked if e.track
    ]
    first = next(iter(again.playlists))
    assert [e.track.uri for e in again.playlists[first].entries if e.track] == [
        e.track.uri for e in catalog.playlists[first].entries if e.track
    ]
    assert again.our_device.id == catalog.our_device.id


def test_contexts(catalog: Catalog) -> None:
    liked = catalog.context(f"spotify:user:{USER_ID}:collection")
    assert liked is not None and liked.kind == "liked"
    assert liked.reported_uri == f"spotify:playlist:{LIKED_ALIAS_ID}"
    album = catalog.saved_albums()[0]
    context = catalog.context(album.album.uri)
    assert context is not None and context.entries is album.entries
    assert catalog.context("spotify:playlist:nothere") is None
    assert catalog.context("spotify:collection:tracks") is None


def test_links_reach_playlists_outside_the_library(catalog: Catalog) -> None:
    by_access = {p.access: p for p in catalog.playlists.values() if not p.in_library}
    assert set(by_access) == {"linked", "spotify"}
    assert by_access["spotify"].playlist.id.startswith("37i9dQZF1")
    assert by_access["linked"].playlist.total is None


def test_tests_can_shape_the_library() -> None:
    catalog = Catalog(device_name="x", library="empty")
    assert catalog.library_playlists() == [] and catalog.liked == []
    album = catalog.add_album("Elsewhere", artist="fakename", tracks=3, unplayable=(1,))
    later = catalog.add_album("Later", tracks=1)
    assert [a.album.name for a in catalog.saved_albums()] == ["Later", "Elsewhere"]
    assert [e.playable for e in album.entries] == [True, False, True]
    assert album.entries[0].album_artist == "fakename" and later.entries[0].art_url
    playlist = catalog.add_playlist("Mine", entries=[catalog.entry("A"), catalog.entry("B")])
    before = playlist.playlist.snapshot_id
    catalog.set_entries(playlist.playlist.id, [catalog.entry("A")])
    assert playlist.playlist.snapshot_id != before and playlist.playlist.total == 1
    catalog.clear()
    assert catalog.playlists == {} and catalog.albums == {}
