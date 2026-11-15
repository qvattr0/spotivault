"""The S0 Web API captures that the fake library is built from, and how to read them.

The JSON files in `data/` are copies of prototype/fixtures/webapi/ (real answers from a Development
Mode app, sanitized; see that folder's README). tests/test_fake_catalog.py checks the copies still
match the originals. They use the 2026 field names: a playlist's contents are under `items`, and a
playlist entry's track under `item`, while `/me/tracks` entries keep `track` and `/me/albums`
entries keep `album` (design.md § Web API usage).

The functions here turn those objects into the port's value types (`spotivault.ports`), the way
the real Web API client does for live answers.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

from spotivault.ports import Album, Image, Page, Playlist, Track

DATA_DIR = Path(__file__).parent / "data"

FIXTURE_FILES = (
    "me-playlists-page.json",
    "playlist-items-page.json",
    "me-tracks-page.json",
    "me-albums-page.json",
    "album-tracks-page.json",
    "offsets-7aUxnM625jyHAtd7b7xZLg.json",
)


@cache
def load(name: str) -> Any:
    """One fixture file, parsed. Read once per process: they're small and never change."""
    with (DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def parse_image(obj: dict[str, Any]) -> Image:
    return Image(url=obj["url"], width=obj.get("width"), height=obj.get("height"))


def parse_track(obj: dict[str, Any], *, album: dict[str, Any] | None = None) -> Track:
    """A track or episode object. An album's own track list leaves out `album`, so the album it
    came from is passed in."""
    album_obj = obj.get("album") or album or {}
    is_episode = obj.get("type") == "episode" or obj.get("episode") is True
    return Track(
        id=obj.get("id"),
        uri=obj["uri"],
        name=obj.get("name") or "",
        artists=tuple(artist["name"] for artist in obj.get("artists") or ()),
        album_id=album_obj.get("id"),
        album_name=album_obj.get("name"),
        track_number=obj.get("track_number"),
        disc_number=obj.get("disc_number"),
        duration_ms=int(obj.get("duration_ms") or 0),
        is_local=bool(obj.get("is_local")),
        is_playable=obj.get("is_playable"),
        is_episode=is_episode,
    )


def parse_playlist(obj: dict[str, Any]) -> Playlist:
    """A playlist object. `items.total` is absent for a linked playlist (Q10)."""
    owner = obj.get("owner") or {}
    contents = obj.get("items")
    return Playlist(
        id=obj["id"],
        uri=obj["uri"],
        name=obj.get("name") or "",
        owner_id=owner.get("id"),
        owner_name=owner.get("display_name"),
        collaborative=bool(obj.get("collaborative")),
        public=obj.get("public"),
        snapshot_id=obj.get("snapshot_id"),
        total=contents.get("total") if isinstance(contents, dict) else None,
        images=tuple(parse_image(image) for image in obj.get("images") or ()),
    )


def parse_album(obj: dict[str, Any]) -> Album:
    """An album object, with its first page of tracks when it carries `tracks`."""
    tracks = obj.get("tracks")
    page = None
    if isinstance(tracks, dict):
        items = tuple(parse_track(track, album=obj) for track in tracks.get("items") or ())
        offset = int(tracks.get("offset") or 0)
        total = int(tracks.get("total") or len(items))
        page = Page(
            items=items,
            offset=offset,
            limit=int(tracks.get("limit") or 50),
            total=total,
            next_offset=offset + len(items) if offset + len(items) < total else None,
        )
    return Album(
        id=obj["id"],
        uri=obj["uri"],
        name=obj.get("name") or "",
        artists=tuple(artist["name"] for artist in obj.get("artists") or ()),
        release_date=obj.get("release_date"),
        total_tracks=int(obj.get("total_tracks") or 0),
        images=tuple(parse_image(image) for image in obj.get("images") or ()),
        tracks=page,
    )
