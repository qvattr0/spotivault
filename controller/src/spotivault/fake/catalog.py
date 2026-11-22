"""The simulated Spotify account: its library, the playlists it can see, and its Connect devices.

One Catalog is shared by the fake Web API (which lists it) and the simulated player (which plays
it), so the two always agree: an entry the Web API lists is the entry the player loads, with the
same id in `mpris:trackid`.

The "fixtures" library is the S0 capture (`fixtures.py`) filled out to its real totals:
- 18 playlists from `/me/playlists`: 17 owned and 1 followed (403 on its items, Q10);
- "Playlist 7" has 300 entries, 20 of them unplayable at the positions S0 found (row 19), and
  its entry 0 is relinked (GET /me/player reports another id, row 18);
- "Playlist 3" has a local file, a podcast episode and an empty entry, which runs leave out;
- Liked Songs (277), and 124 saved albums;
- two linked playlists (public, not followed: 200 on the playlist, 403 on its items) and one made
  by Spotify (404 on both, but it plays), for pasting links.

Entries beyond what S0 captured are generated, the same on every run, so ids stay stable across
restarts of the dev server. Tests can shape the library with the `add_*` methods, or start from
`Catalog(library="empty")`.
"""

import dataclasses
import hashlib
import random
import string
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from spotivault.fake import fixtures
from spotivault.ports import Album, Image, Playlist, SpotifyUser, Track

USER_ID = "user2"  # the account's id in the fixtures: it owns 17 of the 18 playlists
USER_NAME = "User One"  # the sanitized display name the fixtures give it
LIKED_ALIAS_ID = "37i9dQZF1FLikedSongs01"  # what GET /me/player names Liked Songs (row 17)
SPOTIFY_MADE_PREFIX = "37i9dQZF1"  # every playlist made by Spotify starts so (row 28)

type Access = Literal["owned", "collaborative", "followed", "linked", "spotify"]
type ContextKind = Literal["album", "playlist", "liked", "radio", "track"]

_ID_CHARS = string.ascii_letters + string.digits
_WORDS_A = (
    "Quiet Amber Broken Silver Hollow Northern Paper Golden Velvet Distant Midnight Crystal "
    "Wild Lonely Electric Faded Burning Gentle Restless Endless Bright Frozen Secret Open"
).split()
_WORDS_B = (
    "Harbour Lights Rivers Window Engines Gardens Signals Shadows Horizon Stations Letters "
    "Mirrors Fields Voices Machines Islands Echoes Seasons Bridges Highways Clouds Tides Rooms"
).split()


@dataclass(slots=True)
class Entry:
    """One entry of a context, as the Web API lists it and the player plays it."""

    track: Track | None  # None: a playlist entry with no `item`
    added_at: str | None = None
    relinked_id: str | None = None  # the id GET /me/player reports instead of track.id (D10)
    album_artist: str | None = None  # the album's first artist: Spytify's artist folder
    art_url: str | None = None  # mpris:artUrl

    @property
    def playable(self) -> bool:
        """Whether the container's client can play it: not unplayable, local or empty."""
        track = self.track
        return track is not None and not track.is_local and track.is_playable is not False


class LazyEntries:
    """Entries made on first use, so a world with thousands of them builds in no time."""

    def __init__(
        self,
        entries: list[Entry] | None = None,
        make_entries: Callable[[], list[Entry]] | None = None,
    ) -> None:
        self._entries = entries
        self._make_entries = make_entries

    @property
    def entries(self) -> list[Entry]:
        if self._entries is None:
            self._entries = self._make_entries() if self._make_entries else []
        return self._entries

    @entries.setter
    def entries(self, entries: list[Entry]) -> None:
        self._entries = entries


class CatalogPlaylist(LazyEntries):
    """A playlist the account can see."""

    def __init__(
        self,
        playlist: Playlist,
        access: Access,
        *,
        in_library: bool,
        entries: list[Entry] | None = None,
        make_entries: Callable[[], list[Entry]] | None = None,
    ) -> None:
        super().__init__(entries, make_entries)
        self.playlist = playlist
        self.access = access
        self.in_library = in_library  # listed by GET /me/playlists


class CatalogAlbum(LazyEntries):
    """An album the catalog knows. `album.tracks` is None: listings page `entries` themselves."""

    def __init__(
        self,
        album: Album,
        added_at: str | None,
        *,
        entries: list[Entry] | None = None,
        make_entries: Callable[[], list[Entry]] | None = None,
    ) -> None:
        super().__init__(entries, make_entries)
        self.album = album
        self.added_at = added_at  # when it was saved; None for an album not in the library


@dataclass(frozen=True, slots=True, eq=False)
class Context:
    """Something the player can play: an album, a playlist, Liked Songs, autoplay's radio."""

    uri: str  # the context_uri to play it with
    reported_uri: str  # what GET /me/player names it (Liked Songs: a playlist alias)
    kind: ContextKind
    entries: list[Entry]


@dataclass(frozen=True, slots=True)
class DeviceSpec:
    """A Connect device on the account. Ours is listed only while our client is logged in."""

    id: str
    name: str
    type: str
    volume_percent: int | None = 100


class Catalog:
    """The account's library and devices. See the module docstring."""

    def __init__(
        self, *, device_name: str, library: Literal["fixtures", "empty"] = "fixtures"
    ) -> None:
        self.user = SpotifyUser(id=USER_ID, display_name=USER_NAME)
        self.our_device = DeviceSpec(id=device_id(device_name), name=device_name, type="Computer")
        self.other_devices: list[DeviceSpec] = [
            DeviceSpec(id=device_id("Pixel 9"), name="Pixel 9", type="Smartphone"),
            DeviceSpec(id=device_id("Living Room"), name="Living Room", type="Speaker"),
            DeviceSpec(id=device_id("Desktop PC"), name="Desktop PC", type="Computer"),
        ]
        self.playlists: dict[str, CatalogPlaylist] = {}  # in /me/playlists order
        self.albums: dict[str, CatalogAlbum] = {}  # saved ones in /me/albums order
        self._liked = LazyEntries([])  # newest first, as /me/tracks
        self._snapshots = 0
        self._added = 0  # albums added by tests, so each is saved a second later
        if library == "fixtures":
            self._load_fixtures()

    # --- What the Web API lists ----------------------------------------------------------------

    def library_playlists(self) -> list[CatalogPlaylist]:
        """GET /me/playlists: owned, collaborative and followed, in the library's order."""
        return [item for item in self.playlists.values() if item.in_library]

    def saved_albums(self) -> list[CatalogAlbum]:
        """GET /me/albums: most recently saved first."""
        saved = [album for album in self.albums.values() if album.added_at is not None]
        return sorted(saved, key=lambda album: album.added_at or "", reverse=True)

    @property
    def liked(self) -> list[Entry]:
        """Liked Songs, newest first, as /me/tracks."""
        return self._liked.entries

    # --- Contexts ------------------------------------------------------------------------------

    @property
    def liked_uri(self) -> str:
        """Liked Songs as a context (row 17)."""
        return f"spotify:user:{self.user.id}:collection"

    def context(self, uri: str) -> Context | None:
        """The context a context_uri names, or None if there's no such thing."""
        kind, ident = _split_uri(uri)
        if uri in (self.liked_uri, f"spotify:playlist:{LIKED_ALIAS_ID}"):
            alias = f"spotify:playlist:{LIKED_ALIAS_ID}"
            return Context(uri=self.liked_uri, reported_uri=alias, kind="liked", entries=self.liked)
        if kind == "playlist" and ident in self.playlists:
            entries = self.playlists[ident].entries
            return Context(uri=uri, reported_uri=uri, kind="playlist", entries=entries)
        if kind == "album" and ident in self.albums:
            entries = self.albums[ident].entries
            return Context(uri=uri, reported_uri=uri, kind="album", entries=entries)
        return None

    def track_context(self, uri: str) -> tuple[Context, int] | None:
        """For MPRIS OpenUri of a track: its album and its index there, or a context of that
        track alone when its album isn't known (row 9: the Web API reports the album)."""
        for album in self.albums.values():
            for index, entry in enumerate(album.entries):
                if entry.track is not None and entry.track.uri == uri:
                    return Context(album.album.uri, album.album.uri, "album", album.entries), index
        for entry in self._all_entries():
            track = entry.track
            if track is not None and track.uri == uri:
                album_uri = f"spotify:album:{track.album_id}" if track.album_id else uri
                return Context(album_uri, album_uri, "track", [entry]), 0
        return None

    def radio(self, after: Context) -> Context:
        """What autoplay plays once a context ends: similar songs, in a context of its own."""
        rng = _rng(f"radio:{after.uri}")
        ident = "37i9dQZF1E" + _random_id(rng, 12)
        entries = [_generated_entry(rng, artist_pool=(400, 600)) for _ in range(10)]
        uri = f"spotify:playlist:{ident}"
        return Context(uri=uri, reported_uri=uri, kind="radio", entries=entries)

    # --- Shaping the library (tests) -----------------------------------------------------------

    def clear(self) -> None:
        """An empty library: no playlists, albums or Liked Songs."""
        self.playlists.clear()
        self.albums.clear()
        self._liked = LazyEntries([])

    def add_album(
        self,
        name: str,
        *,
        artist: str = "Test Artist",
        tracks: int | list[tuple[str, int]] = 5,
        saved: bool = True,
        unplayable: tuple[int, ...] = (),
        album_id: str | None = None,
    ) -> CatalogAlbum:
        """Adds an album. `tracks` is a count (titles "Track 1"…, 90 s each) or a list of
        (title, duration_ms). `unplayable` lists 0-based positions."""
        ident = album_id or _random_id(_rng(f"album:{name}:{artist}"))
        specs = (
            tracks
            if isinstance(tracks, list)
            else [(f"Track {n}", 90_000) for n in range(1, tracks + 1)]
        )
        album = Album(
            id=ident,
            uri=f"spotify:album:{ident}",
            name=name,
            artists=(artist,),
            release_date="2026-01-01",
            total_tracks=len(specs),
            images=_album_images(ident),
            tracks=None,
        )
        entries = []
        for position, (title, duration_ms) in enumerate(specs):
            track = make_track(
                title,
                artist=artist,
                album=album,
                track_number=position + 1,
                duration_ms=duration_ms,
                is_playable=position not in unplayable,
            )
            entries.append(_entry_for(track, album))
        added_at = None
        if saved:
            self._added += 1
            added_at = f"2026-11-14T12:{self._added // 60:02d}:{self._added % 60:02d}Z"
        catalog_album = CatalogAlbum(album, added_at, entries=entries)
        self.albums[ident] = catalog_album
        return catalog_album

    def add_playlist(
        self,
        name: str,
        *,
        entries: list[Entry] | None = None,
        tracks: int = 0,
        access: Access = "owned",
        playlist_id: str | None = None,
    ) -> CatalogPlaylist:
        """Adds a playlist with these entries, or `tracks` generated ones. Owned and
        collaborative ones are in the library; so are followed ones; linked and Spotify-made
        ones are only reachable by their id."""
        rng = _rng(f"playlist:{name}")
        if playlist_id is None:
            prefix = SPOTIFY_MADE_PREFIX + "DX" if access == "spotify" else ""
            playlist_id = prefix + _random_id(rng, 22 - len(prefix))
        if entries is None:
            entries = [_generated_entry(rng) for _ in range(tracks)]
        owner_id, owner_name = (
            (self.user.id, self.user.display_name)
            if access in ("owned", "collaborative")
            else (("spotify", "Spotify") if access == "spotify" else ("user7", "Someone Else"))
        )
        playlist = Playlist(
            id=playlist_id,
            uri=f"spotify:playlist:{playlist_id}",
            name=name,
            owner_id=owner_id,
            owner_name=owner_name,
            collaborative=access == "collaborative",
            public=access != "collaborative",
            snapshot_id=self._new_snapshot(),
            total=None if access in ("linked", "spotify") else len(entries),
            images=_playlist_images(playlist_id),
        )
        item = CatalogPlaylist(
            playlist,
            access,
            in_library=access in ("owned", "collaborative", "followed"),
            entries=entries,
        )
        self.playlists[playlist_id] = item
        return item

    def set_entries(self, playlist_id: str, entries: list[Entry]) -> None:
        """Replaces a playlist's entries; its snapshot_id and total change, as Spotify's do."""
        item = self.playlists[playlist_id]
        item.entries = entries
        total = None if item.playlist.total is None else len(entries)
        item.playlist = dataclasses.replace(
            item.playlist, snapshot_id=self._new_snapshot(), total=total
        )

    def entry(self, title: str, *, artist: str = "Test Artist", duration_ms: int = 90_000) -> Entry:
        """A standalone entry for `add_playlist(entries=...)` or `set_entries`."""
        track = make_track(title, artist=artist, duration_ms=duration_ms)
        return Entry(track=track, added_at="2026-11-14T12:00:00Z", album_artist=artist)

    # --- Inside --------------------------------------------------------------------------------

    def _new_snapshot(self) -> str:
        self._snapshots += 1
        digest = hashlib.sha1(f"snapshot:{self._snapshots}".encode()).hexdigest()
        return f"snapshot-{digest[:12]}"

    def _all_entries(self) -> list[Entry]:
        entries = list(self.liked)
        for playlist in self.playlists.values():
            entries += playlist.entries
        return entries

    def _load_fixtures(self) -> None:
        self._load_albums()
        self._load_liked()
        self._load_playlists()
        self._add_reachable_by_link()

    def _load_albums(self) -> None:
        page = fixtures.load("me-albums-page.json")
        for item in page["items"]:
            obj = item["album"]
            album = fixtures.parse_album(obj)
            entries = (
                [_entry_for(track, album) for track in album.tracks.items] if album.tracks else []
            )
            stripped = dataclasses.replace(album, tracks=None)
            self.albums[album.id] = CatalogAlbum(stripped, item["added_at"], entries=entries)
        rng = _rng("saved-albums")
        for n in range(len(self.albums), int(page["total"])):
            album = _generated_album(rng)
            added_at = _days_before("2025-07-31T19:00:00Z", (n - 1) * 9)
            self.albums[album.id] = CatalogAlbum(album, added_at, make_entries=_album_maker(album))

    def _load_liked(self) -> None:
        page = fixtures.load("me-tracks-page.json")

        def make() -> list[Entry]:
            liked = []
            for item in page["items"]:
                images = item["track"]["album"].get("images") or ()
                liked.append(
                    Entry(
                        track=fixtures.parse_track(item["track"]),
                        added_at=item["added_at"],
                        album_artist=_first(item["track"]["album"].get("artists")),
                        art_url=images[0]["url"] if images else None,
                    )
                )
            rng = _rng("liked")
            for n in range(len(liked), int(page["total"])):
                entry = _generated_entry(rng)
                entry.added_at = _days_before("2026-09-27T14:56:57Z", n * 3)
                liked.append(entry)
            return liked

        self._liked = LazyEntries(make_entries=make)

    def _load_playlists(self) -> None:
        page = fixtures.load("me-playlists-page.json")
        items_page = fixtures.load("playlist-items-page.json")
        offsets = fixtures.load("offsets-7aUxnM625jyHAtd7b7xZLg.json")
        captured_id = "7aUxnM625jyHAtd7b7xZLg"  # the playlist the items and offsets came from
        for obj in page["items"]:
            playlist = fixtures.parse_playlist(obj)
            if playlist.owner_id == USER_ID:
                access: Access = "collaborative" if playlist.collaborative else "owned"
            else:
                access = "followed"
            make = _playlist_maker(playlist)
            if playlist.id == captured_id:
                make = _captured_playlist_maker(playlist, items_page, set(offsets["unplayable"]))
            elif playlist.name == "Playlist 3":
                make = _odd_entries_maker(playlist)
            self.playlists[playlist.id] = CatalogPlaylist(
                playlist, access, in_library=True, make_entries=make
            )

    def _add_reachable_by_link(self) -> None:
        """Playlists that aren't in the library but can be pasted as a link (Q10, row 28)."""
        self.add_playlist("Linked Mix", tracks=20, access="linked")
        self.add_playlist("Friday Finds", tracks=12, access="linked")
        self.add_playlist("Editorial Picks", tracks=30, access="spotify")


# --- Building blocks ----------------------------------------------------------------------------


def device_id(name: str) -> str:
    """A Connect device id, stable for a name (the real one survives restarts: row 8)."""
    return hashlib.sha1(f"device:{name}".encode()).hexdigest()


def make_track(
    title: str,
    *,
    artist: str | tuple[str, ...] = "Test Artist",
    album: Album | None = None,
    track_number: int | None = 1,
    duration_ms: int = 90_000,
    is_playable: bool | None = True,
    track_id: str | None = None,
) -> Track:
    """A track with sensible defaults, for tests that shape the library."""
    artists = (artist,) if isinstance(artist, str) else artist
    ident = track_id or _random_id(_rng(f"track:{title}:{artists}:{album.id if album else ''}"))
    return Track(
        id=ident,
        uri=f"spotify:track:{ident}",
        name=title,
        artists=artists,
        album_id=album.id if album else None,
        album_name=album.name if album else None,
        track_number=track_number,
        disc_number=1,
        duration_ms=duration_ms,
        is_local=False,
        is_playable=is_playable,
        is_episode=False,
    )


def _split_uri(uri: str) -> tuple[str, str]:
    """ "spotify:playlist:ID" → ("playlist", "ID"); anything else → ("", "")."""
    parts = uri.split(":")
    if len(parts) == 3 and parts[0] == "spotify":
        return parts[1], parts[2]
    return "", ""


def _rng(seed: str) -> random.Random:
    # A str seed is hashed with SHA-512 (seed version 2), so it's the same on every run.
    return random.Random(seed)


def _random_id(rng: random.Random, length: int = 22) -> str:
    return "".join(rng.choices(_ID_CHARS, k=length))


def _hex(seed: str, length: int) -> str:
    return hashlib.sha1(seed.encode()).hexdigest()[:length]


def _album_images(album_id: str) -> tuple[Image, ...]:
    digest = _hex(f"cover:{album_id}", 24)
    base = "https://i.scdn.co/image/"
    return (
        Image(url=f"{base}ab67616d0000b273{digest}", width=640, height=640),
        Image(url=f"{base}ab67616d00001e02{digest}", width=300, height=300),
        Image(url=f"{base}ab67616d00004851{digest}", width=64, height=64),
    )


def _playlist_images(playlist_id: str) -> tuple[Image, ...]:
    url = f"https://image-cdn-ak.spotifycdn.com/image/{_hex(f'mosaic:{playlist_id}', 40)}"
    return (Image(url=url, width=None, height=None),)


def _first(artists: list[dict[str, str]] | None) -> str | None:
    return artists[0]["name"] if artists else None


def _entry_for(track: Track, album: Album) -> Entry:
    """An album's own entry: its album artist and cover come from the album."""
    return Entry(
        track=track,
        album_artist=album.artists[0] if album.artists else None,
        art_url=album.images[0].url if album.images else None,
    )


def _days_before(moment: str, days: int) -> str:
    """An ISO time `days` days before `moment` (for generated added_at dates)."""
    when = datetime.fromisoformat(moment.replace("Z", "+00:00")) - timedelta(days=days)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _generated_entry(
    rng: random.Random, *, artist_pool: tuple[int, int] = (11, 400), relink_share: float = 0.0
) -> Entry:
    """A believable track from an album the catalog doesn't hold."""
    artist = f"Artist {rng.randint(*artist_pool)}"
    album_id = _random_id(rng)
    album_name = f"{rng.choice(_WORDS_B)} of {rng.choice(_WORDS_B)}"
    ident = _random_id(rng)
    track = Track(
        id=ident,
        uri=f"spotify:track:{ident}",
        name=f"{rng.choice(_WORDS_A)} {rng.choice(_WORDS_B)}",
        artists=(artist,)
        if rng.random() < 0.8
        else (artist, f"Artist {rng.randint(*artist_pool)}"),
        album_id=album_id,
        album_name=album_name,
        track_number=rng.randint(1, 12),
        disc_number=1,
        duration_ms=rng.randint(120_000, 330_000),
        is_local=False,
        is_playable=True,
        is_episode=False,
    )
    relinked = _random_id(rng) if rng.random() < relink_share else None
    return Entry(
        track=track,
        added_at="2024-03-01T12:00:00Z",
        relinked_id=relinked,
        album_artist=artist,
        art_url=_album_images(album_id)[0].url,
    )


def _generated_album(rng: random.Random) -> Album:
    """A saved album's header. Its tracks come from `_album_maker`, on first use."""
    ident = _random_id(rng)
    year = rng.randint(1968, 2026)
    return Album(
        id=ident,
        uri=f"spotify:album:{ident}",
        name=f"{rng.choice(_WORDS_A)} {rng.choice(_WORDS_B)}",
        artists=(f"Artist {rng.randint(11, 400)}",),
        release_date=f"{year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
        total_tracks=rng.choice((3, 4, 6, 8, 9, 10, 11, 12, 14)),
        images=_album_images(ident),
        tracks=None,
    )


def _album_maker(album: Album) -> Callable[[], list[Entry]]:
    """A generated album's tracks; about one album in ten has an unplayable one."""

    def make() -> list[Entry]:
        rng = _rng(f"album-tracks:{album.id}")
        count = album.total_tracks
        unplayable = rng.randrange(count) if rng.random() < 0.1 else None
        entries = []
        for position in range(count):
            track = make_track(
                f"{rng.choice(_WORDS_A)} {rng.choice(_WORDS_B)}",
                artist=album.artists,
                album=album,
                track_number=position + 1,
                duration_ms=rng.randint(60_000, 300_000),
                is_playable=position != unplayable,
                track_id=_random_id(rng),
            )
            entries.append(_entry_for(track, album))
        return entries

    return make


def _playlist_maker(playlist: Playlist) -> Callable[[], list[Entry]]:
    """Entries for a captured playlist header: `total` of them, about 4 in 9 relinked."""

    def make() -> list[Entry]:
        rng = _rng(f"entries:{playlist.id}")
        return [_generated_entry(rng, relink_share=4 / 9) for _ in range(playlist.total or 0)]

    return make


def _captured_playlist_maker(
    playlist: Playlist, items_page: dict, unplayable: set[int]
) -> Callable[[], list[Entry]]:
    """Playlist 7: its first entries as captured, then generated ones, with S0's 20 unplayable
    positions (0-based) and entry 0 relinked (offsets fixture)."""

    def make() -> list[Entry]:
        rng = _rng(f"entries:{playlist.id}")
        entries = []
        for item in items_page["items"]:
            obj = item["item"]
            images = obj["album"].get("images") or ()
            entries.append(
                Entry(
                    track=fixtures.parse_track(obj),
                    added_at=item["added_at"],
                    album_artist=_first(obj["album"].get("artists")),
                    art_url=images[0]["url"] if images else None,
                )
            )
        while len(entries) < (playlist.total or 0):
            entries.append(_generated_entry(rng, relink_share=4 / 9))
        for position in unplayable:
            track = entries[position].track
            if track is not None:
                entries[position].track = dataclasses.replace(track, is_playable=False)
        entries[0].relinked_id = _random_id(rng)
        entries[22].relinked_id = None
        return entries

    return make


def _odd_entries_maker(playlist: Playlist) -> Callable[[], list[Entry]]:
    """Playlist 3: a local file (4), a podcast episode (8) and an entry with no item (11)."""

    def make() -> list[Entry]:
        entries = _playlist_maker(playlist)()
        entries[4] = Entry(
            track=Track(
                id=None,
                uri="spotify:local:Some+Band:Home+Demos:Garage+Take:201",
                name="Garage Take",
                artists=("Some Band",),
                album_id=None,
                album_name="Home Demos",
                track_number=None,
                disc_number=None,
                duration_ms=201_000,
                is_local=True,
                is_playable=None,
                is_episode=False,
            ),
            added_at="2024-03-01T12:00:00Z",
        )
        episode_id = _random_id(_rng("episode"))
        entries[8] = Entry(
            track=Track(
                id=episode_id,
                uri=f"spotify:episode:{episode_id}",
                name="Episode 12: Tape Machines",
                artists=("A Podcast",),
                album_id=None,
                album_name="A Podcast",
                track_number=None,
                disc_number=None,
                duration_ms=1_830_000,
                is_local=False,
                is_playable=True,
                is_episode=True,
            ),
            added_at="2024-03-01T12:00:00Z",
        )
        entries[11] = Entry(track=None, added_at="2024-03-01T12:00:00Z")
        return entries

    return make
