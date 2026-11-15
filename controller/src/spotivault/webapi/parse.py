"""Web API JSON into the port's value types (`spotivault.ports`), with the 2026 field names.

Owner: webapi-core. Only client.py (and tokens.py, for the token answer) uses it.

- A playlist's contents are under `items` (`items.total`; absent for a linked playlist), and a
  playlist entry's track under `item` (absent or null for an empty entry). The old names
  (`tracks`, `track`) aren't read there.
- `/me/tracks` entries keep `track`; `/me/albums` entries keep `album`, with the album's first
  page of tracks under `album.tracks.items` (those tracks have no `album`: pass the album in).
- An episode is `type: "episode"`, or (without `additional_types`, as spotivault asks) a track
  object with `episode: true` and a `spotify:episode:` URI; a local file has `is_local: true` and
  no id.
- `is_playable` is only in answers asked with a `market`: None when it's absent.

Each function raises KeyError, TypeError or ValueError on an answer it can't read; client.py
turns those into a WebApiError naming the endpoint.
"""

from dataclasses import replace
from typing import Any

from spotivault.ports import (
    Album,
    Device,
    Image,
    Page,
    PlayerState,
    Playlist,
    PlaylistEntry,
    RepeatState,
    SavedAlbum,
    SavedTrack,
    SpotifyUser,
    TokenGrant,
    Track,
)

REPEAT_STATES: tuple[RepeatState, ...] = ("off", "track", "context")


def parse_page[T](obj: dict[str, Any], items: list[T]) -> Page[T]:
    """A Page from a paging object (`offset`, `limit`, `total`, `next`) and its already-parsed
    items. `next_offset` is None on the last page, and on an empty page (so a caller's loop always
    ends)."""
    # The next page starts after every entry Spotify sent, even one the caller left out (a null
    # entry, say), so no entry is skipped or asked for twice.
    raw = obj.get("items")
    sent = len(raw) if isinstance(raw, list) else len(items)
    offset = _int(obj.get("offset"), 0)
    total = _int(obj.get("total"), offset + sent)
    limit = _int(obj.get("limit"), sent)
    end = offset + sent
    if "next" in obj:
        more = obj["next"] is not None
    else:
        more = end < total
    return Page(
        items=tuple(items),
        offset=offset,
        limit=limit,
        total=total,
        next_offset=end if more and sent else None,
    )


def parse_image(obj: dict[str, Any]) -> Image:
    return Image(
        url=str(obj["url"]), width=_opt_int(obj.get("width")), height=_opt_int(obj.get("height"))
    )


def parse_track(obj: dict[str, Any], *, album: dict[str, Any] | None = None) -> Track:
    """A track or episode object. An album's own track list leaves out `album`, so the album it
    came from is passed in."""
    album_obj = obj.get("album") or album or {}
    uri = str(obj["uri"])
    is_episode = (
        obj.get("type") == "episode"
        or obj.get("episode") is True
        or uri.startswith("spotify:episode:")
    )
    is_playable = obj.get("is_playable")
    return Track(
        id=obj.get("id") or None,
        uri=uri,
        name=obj.get("name") or "",
        artists=tuple(str(artist.get("name") or "") for artist in obj.get("artists") or ()),
        album_id=album_obj.get("id") or None,
        album_name=album_obj.get("name"),
        track_number=_opt_int(obj.get("track_number")),
        disc_number=_opt_int(obj.get("disc_number")),
        duration_ms=_int(obj.get("duration_ms"), 0),
        is_local=bool(obj.get("is_local")),
        is_playable=is_playable if isinstance(is_playable, bool) else None,
        is_episode=is_episode,
    )


def parse_playlist(obj: dict[str, Any]) -> Playlist:
    """A playlist object, from /me/playlists or GET /playlists/{id}. `items.total` is absent for
    a linked playlist (S0 row 29), so `total` is None there."""
    owner = obj.get("owner") or {}
    contents = obj.get("items")
    total = contents.get("total") if isinstance(contents, dict) else None
    return Playlist(
        id=str(obj["id"]),
        uri=str(obj["uri"]),
        name=obj.get("name") or "",
        owner_id=owner.get("id"),
        owner_name=owner.get("display_name"),
        collaborative=bool(obj.get("collaborative")),
        public=obj.get("public") if isinstance(obj.get("public"), bool) else None,
        snapshot_id=obj.get("snapshot_id"),
        total=_opt_int(total),
        images=tuple(parse_image(image) for image in obj.get("images") or ()),
    )


def parse_playlist_entry(obj: dict[str, Any]) -> PlaylistEntry:
    """One entry of GET /playlists/{id}/items: the track under `item` (2026), None when the
    entry has none. The entry's own `is_local` counts too."""
    item = obj.get("item")
    track = parse_track(item) if isinstance(item, dict) else None
    if track is not None and obj.get("is_local") is True and not track.is_local:
        track = replace(track, is_local=True)
    return PlaylistEntry(added_at=obj.get("added_at"), track=track)


def parse_saved_track(obj: dict[str, Any]) -> SavedTrack:
    """One entry of GET /me/tracks: this endpoint kept `track`."""
    return SavedTrack(added_at=obj.get("added_at") or "", track=parse_track(obj["track"]))


def parse_album(obj: dict[str, Any]) -> Album:
    """An album object, with its first page of tracks when it carries `tracks`."""
    tracks = obj.get("tracks")
    page = None
    if isinstance(tracks, dict):
        items = [parse_track(track, album=obj) for track in tracks.get("items") or ()]
        page = parse_page(tracks, items)
    return Album(
        id=str(obj["id"]),
        uri=str(obj["uri"]),
        name=obj.get("name") or "",
        artists=tuple(str(artist.get("name") or "") for artist in obj.get("artists") or ()),
        release_date=obj.get("release_date"),
        total_tracks=_int(obj.get("total_tracks"), 0),
        images=tuple(parse_image(image) for image in obj.get("images") or ()),
        tracks=page,
    )


def parse_saved_album(obj: dict[str, Any]) -> SavedAlbum:
    """One entry of GET /me/albums: this endpoint kept `album`."""
    return SavedAlbum(added_at=obj.get("added_at") or "", album=parse_album(obj["album"]))


def parse_user(obj: dict[str, Any]) -> SpotifyUser:
    return SpotifyUser(id=str(obj["id"]), display_name=obj.get("display_name"))


def parse_device(obj: dict[str, Any]) -> Device:
    return Device(
        id=obj.get("id"),
        name=obj.get("name") or "",
        type=obj.get("type") or "",
        is_active=bool(obj.get("is_active")),
        is_restricted=bool(obj.get("is_restricted")),
        volume_percent=_opt_int(obj.get("volume_percent")),
    )


def parse_player_state(obj: dict[str, Any]) -> PlayerState:
    """GET /me/player. The context and the device are what's used; `item.id` may be a relinked
    id (D10)."""
    device = obj.get("device")
    context = obj.get("context")
    item = obj.get("item")
    repeat = obj.get("repeat_state")
    shuffle = obj.get("shuffle_state")
    return PlayerState(
        device=parse_device(device) if isinstance(device, dict) else None,
        is_playing=bool(obj.get("is_playing")),
        context_uri=context.get("uri") if isinstance(context, dict) else None,
        track_id=item.get("id") if isinstance(item, dict) else None,
        progress_ms=_opt_int(obj.get("progress_ms")),
        shuffle=shuffle if isinstance(shuffle, bool) else None,
        repeat=repeat if repeat in REPEAT_STATES else None,
    )


def parse_token_grant(obj: dict[str, Any], *, refresh_token: str | None = None) -> TokenGrant:
    """The token endpoint's answer. A refresh may leave out `refresh_token`: then the one given
    here is kept. ValueError when there's no access token or no refresh token at all."""
    access_token = obj.get("access_token")
    new_refresh = obj.get("refresh_token") or refresh_token
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("no access token in the answer")
    if not isinstance(new_refresh, str) or not new_refresh:
        raise ValueError("no refresh token in the answer")
    return TokenGrant(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_in_s=_int(obj.get("expires_in"), 3600),
        scopes=tuple(str(obj.get("scope") or "").split()),
    )


def _int(value: Any, default: int) -> int:
    return default if value is None else int(value)


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)
