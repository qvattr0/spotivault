"""webapi/parse.py: the Web API's 2026 JSON into the port's value types.

The S0 captures (fake/data/, sanitized) are real answers; the odd shapes are written out here.
"""

import pytest

from spotivault.fake.fixtures import load
from spotivault.ports import Device, Image, PlayerState
from spotivault.webapi.parse import (
    parse_album,
    parse_device,
    parse_image,
    parse_page,
    parse_player_state,
    parse_playlist,
    parse_playlist_entry,
    parse_saved_album,
    parse_saved_track,
    parse_token_grant,
    parse_track,
    parse_user,
)


def test_a_page_knows_where_the_next_one_starts() -> None:
    page = load("me-tracks-page.json")
    parsed = parse_page(page, [parse_saved_track(e) for e in page["items"]])
    assert parsed.offset == page["offset"]
    assert parsed.limit == page["limit"]
    assert parsed.total == page["total"]
    assert len(parsed.items) == len(page["items"])
    assert parsed.next_offset == page["offset"] + len(page["items"])


def test_the_last_page_and_an_empty_page_have_no_next() -> None:
    last = {"offset": 40, "limit": 20, "total": 45, "next": None, "items": [1, 2, 3, 4, 5]}
    assert parse_page(last, [1, 2, 3, 4, 5]).next_offset is None
    # An empty page that claims more would loop a caller forever: it ends here.
    empty = {"offset": 0, "limit": 20, "total": 3, "next": "https://x", "items": []}
    assert parse_page(empty, []).next_offset is None
    # Without `next` (a `fields` list can leave it out), the total decides.
    assert parse_page({"offset": 0, "total": 3, "items": [1, 2]}, [1, 2]).next_offset == 2


def test_a_null_entry_still_moves_the_next_offset_on() -> None:
    page = {"offset": 0, "limit": 3, "total": 5, "next": "n", "items": [{"a": 1}, None, {"b": 2}]}
    parsed = parse_page(page, ["a", "b"])
    assert parsed.items == ("a", "b")
    assert parsed.next_offset == 3


def test_playlists_read_items_total_and_linked_ones_have_none() -> None:
    page = load("me-playlists-page.json")
    first = parse_playlist(page["items"][0])
    assert first.total == page["items"][0]["items"]["total"]
    assert first.owner_id == "user1" and first.owner_name == "User One"
    assert first.images and first.images[0].url.startswith("https://")
    linked = {"id": "x" * 22, "uri": "spotify:playlist:" + "x" * 22, "name": "Linked"}
    assert parse_playlist(linked).total is None
    # The old name isn't read: `tracks` is not where a playlist's contents are in 2026.
    old = linked | {"tracks": {"total": 9}}
    assert parse_playlist(old).total is None


def test_a_playlist_entry_takes_its_track_from_item() -> None:
    page = load("playlist-items-page.json")
    entry = parse_playlist_entry(page["items"][0])
    raw = page["items"][0]["item"]
    assert entry.added_at == page["items"][0]["added_at"]
    assert entry.track is not None
    assert entry.track.id == raw["id"] and entry.track.uri == raw["uri"]
    assert entry.track.album_id == raw["album"]["id"]
    assert entry.track.is_playable is True and not entry.track.is_episode


def test_empty_local_and_episode_entries() -> None:
    assert parse_playlist_entry({"added_at": None, "item": None}).track is None
    assert parse_playlist_entry({"added_at": None}).track is None
    # The old `track` name isn't read for playlist entries.
    old = {"track": {"uri": "spotify:track:" + "a" * 22, "name": "x"}}
    assert parse_playlist_entry(old).track is None

    local = parse_playlist_entry(
        {
            "is_local": True,
            "item": {"id": None, "uri": "spotify:local:A:B:C:180", "name": "C", "type": "track"},
        }
    )
    assert local.track is not None and local.track.is_local and local.track.id is None

    episode = parse_playlist_entry(
        {
            "item": {
                "id": "e" * 22,
                "uri": "spotify:episode:" + "e" * 22,
                "type": "track",
                "episode": True,
                "name": "Ep",
            }
        }
    )
    assert episode.track is not None and episode.track.is_episode
    as_episode = parse_track({"uri": "spotify:episode:" + "e" * 22, "type": "episode"})
    assert as_episode.is_episode


def test_is_playable_is_none_without_a_market() -> None:
    track = parse_track({"id": "t" * 22, "uri": "spotify:track:" + "t" * 22, "name": "x"})
    assert track.is_playable is None
    assert track.duration_ms == 0 and track.artists == ()


def test_saved_tracks_keep_track_and_saved_albums_keep_album() -> None:
    tracks = load("me-tracks-page.json")
    saved = parse_saved_track(tracks["items"][0])
    assert saved.added_at == tracks["items"][0]["added_at"]
    assert saved.track.id == tracks["items"][0]["track"]["id"]

    albums = load("me-albums-page.json")
    raw = albums["items"][0]["album"]
    album = parse_saved_album(albums["items"][0]).album
    assert album.id == raw["id"] and album.total_tracks == raw["total_tracks"]
    assert album.tracks is not None
    assert len(album.tracks.items) == len(raw["tracks"]["items"])
    # An album's own tracks carry no `album`: the album they came in is filled in.
    assert {t.album_id for t in album.tracks.items} == {raw["id"]}
    assert {t.album_name for t in album.tracks.items} == {raw["name"]}


def test_an_album_without_tracks_has_no_first_page() -> None:
    album = parse_album({"id": "a" * 22, "uri": "spotify:album:" + "a" * 22, "name": "A"})
    assert album.tracks is None and album.total_tracks == 0 and album.images == ()


def test_album_tracks_from_their_own_listing() -> None:
    page = load("album-tracks-page.json")
    tracks = [parse_track(t, album={"id": "b" * 22}) for t in page["items"]]
    assert {t.album_id for t in tracks} == {"b" * 22}
    assert tracks[0].track_number == page["items"][0]["track_number"]


def test_images_users_devices() -> None:
    assert parse_image({"url": "https://i.scdn.co/image/x", "width": None, "height": None}) == (
        Image(url="https://i.scdn.co/image/x", width=None, height=None)
    )
    assert parse_user({"id": "u", "display_name": None}).display_name is None
    device = {
        "id": "d1",
        "is_active": True,
        "is_restricted": False,
        "name": "spotivault",
        "type": "Computer",
        "volume_percent": 80,
    }
    assert parse_device(device) == Device(
        id="d1",
        name="spotivault",
        type="Computer",
        is_active=True,
        is_restricted=False,
        volume_percent=80,
    )


def test_the_player_state() -> None:
    state = parse_player_state(
        {
            "device": {"id": "d1", "name": "spotivault", "type": "Computer", "is_active": True},
            "is_playing": True,
            "context": {"uri": "spotify:playlist:37i9dQZF1FLikedSongs01"},
            "item": {"id": "t" * 22},
            "progress_ms": 1200,
            "shuffle_state": False,
            "repeat_state": "context",
        }
    )
    assert isinstance(state, PlayerState)
    assert state.device is not None and state.device.id == "d1"
    assert state.context_uri == "spotify:playlist:37i9dQZF1FLikedSongs01"
    assert (state.track_id, state.progress_ms, state.shuffle, state.repeat) == (
        "t" * 22,
        1200,
        False,
        "context",
    )
    bare = parse_player_state({"is_playing": False, "context": None, "item": None})
    assert bare.device is None and bare.context_uri is None and bare.repeat is None


def test_a_token_grant_and_a_refresh_that_keeps_the_refresh_token() -> None:
    grant = parse_token_grant(
        {
            "access_token": "BQaccess",
            "refresh_token": "AQrefresh",
            "expires_in": 3600,
            "scope": "user-library-read playlist-read-private",
            "token_type": "Bearer",
        }
    )
    assert grant.scopes == ("user-library-read", "playlist-read-private")
    assert grant.expires_in_s == 3600
    kept = parse_token_grant({"access_token": "BQnew", "expires_in": 60}, refresh_token="AQold")
    assert kept.refresh_token == "AQold" and kept.scopes == ()
    with pytest.raises(ValueError):
        parse_token_grant({"access_token": "BQnew"})  # a code exchange must send one
    with pytest.raises(ValueError):
        parse_token_grant({"refresh_token": "AQx"}, refresh_token="AQx")
