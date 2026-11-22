"""The Spotify endpoints spotivault may call, and nothing else (design.md § Web API usage).

Every request the real port sends is built from one of these, so it can't reach an endpoint the
design doesn't allow (Spotify's internal endpoints included), and the usage log can name it by its
template without ever holding an id. The list matches the `api_endpoints` rows of
contracts/schema.sql exactly; a test checks it. A new endpoint needs a spec change in design.md,
then a migration that inserts its row, then an entry here.

    url = PLAYLIST_ITEMS.url(id=playlist_id)   # https://api.spotify.com/v1/playlists/<id>/items
    endpoint_for("GET", url)                   # PLAYLIST_ITEMS, as the mock and the log see it

The real port, the usage log and tests/spotify_mock.py all read it.
"""

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

API_BASE = "https://api.spotify.com/v1"
ACCOUNTS_BASE = "https://accounts.spotify.com"
AUTHORIZE_URL = ACCOUNTS_BASE + "/authorize"
TOKEN_URL = ACCOUNTS_BASE + "/api/token"

# Wizard step 5: the redirect URI pasted into the developer app, and the scopes asked for
# (web-ui.md § 5). The browser lands on this address and shows an error page; you paste it back.
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = (
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
    "user-read-playback-state",
    "user-modify-playback-state",
)

type Method = Literal["GET", "PUT", "POST", "DELETE"]
# catalog: listings, spaced 250 ms apart. playback: the player, never delayed. auth: the token.
type Lane = Literal["catalog", "playback", "auth"]

# A Spotify id in a path: base-62 only, so no id can add a path segment or a query.
_ID = re.compile(r"[0-9A-Za-z]{1,64}")


@dataclass(frozen=True, slots=True)
class Endpoint:
    """One allowed endpoint: its method, path template, and the scheduler lane it runs in."""

    method: Method
    template: str  # as in api_endpoints: "/playlists/{id}/items", "/api/token" for the token
    lane: Lane

    @property
    def name(self) -> str:
        """ "GET /playlists/{id}/items": how logs, the usage log and tests name it."""
        return f"{self.method} {self.template}"

    def url(self, *, id: str | None = None) -> str:
        """The full URL, without a query. `id` fills `{id}`; it must be a base-62 Spotify id.

        Raises ValueError for a missing, unexpected or malformed id.
        """
        needs_id = "{id}" in self.template
        if needs_id != (id is not None):
            raise ValueError(f"{self.name}: id {'needed' if needs_id else 'not expected'}")
        if id is not None and _ID.fullmatch(id) is None:
            raise ValueError(f"{self.name}: not a Spotify id")
        if self.lane == "auth":
            return ACCOUNTS_BASE + self.template
        path = self.template if id is None else self.template.replace("{id}", id)
        return API_BASE + path


TOKEN = Endpoint("POST", "/api/token", "auth")  # code exchange and refresh, accounts.spotify.com
ME = Endpoint("GET", "/me", "catalog")
MY_PLAYLISTS = Endpoint("GET", "/me/playlists", "catalog")
PLAYLIST = Endpoint("GET", "/playlists/{id}", "catalog")
PLAYLIST_ITEMS = Endpoint("GET", "/playlists/{id}/items", "catalog")
SAVED_TRACKS = Endpoint("GET", "/me/tracks", "catalog")
SAVED_ALBUMS = Endpoint("GET", "/me/albums", "catalog")
ALBUM_TRACKS = Endpoint("GET", "/albums/{id}/tracks", "catalog")
DEVICES = Endpoint("GET", "/me/player/devices", "playback")
PLAYER = Endpoint("GET", "/me/player", "playback")  # D10's fallback for track identity
PLAY = Endpoint("PUT", "/me/player/play", "playback")
PAUSE = Endpoint("PUT", "/me/player/pause", "playback")
SEEK = Endpoint("PUT", "/me/player/seek", "playback")  # seek to 0 before the recorder starts
SHUFFLE = Endpoint("PUT", "/me/player/shuffle", "playback")
REPEAT = Endpoint("PUT", "/me/player/repeat", "playback")

# In the order of the api_endpoints rows (contracts/schema.sql), so row ids follow it too.
ENDPOINTS: tuple[Endpoint, ...] = (
    TOKEN,
    ME,
    MY_PLAYLISTS,
    PLAYLIST,
    PLAYLIST_ITEMS,
    SAVED_TRACKS,
    SAVED_ALBUMS,
    ALBUM_TRACKS,
    DEVICES,
    PLAYER,
    PLAY,
    PAUSE,
    SEEK,
    SHUFFLE,
    REPEAT,
)

BY_NAME: dict[str, Endpoint] = {endpoint.name: endpoint for endpoint in ENDPOINTS}


def endpoint_for(method: str, url: str) -> Endpoint | None:
    """The allowed endpoint a request goes to, or None for anything else: another host, another
    path, or another method. The query is ignored. `url` is the full URL, as httpx sends it."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin == ACCOUNTS_BASE:
        return TOKEN if method == "POST" and parts.path == TOKEN.template else None
    if origin != "https://api.spotify.com" or not parts.path.startswith("/v1/"):
        return None
    path = parts.path[len("/v1") :]
    for endpoint in ENDPOINTS:
        if endpoint.method != method or endpoint.lane == "auth":
            continue
        if _path_matches(endpoint.template, path):
            return endpoint
    return None


def _path_matches(template: str, path: str) -> bool:
    want = template.split("/")
    got = path.split("/")
    if len(want) != len(got):
        return False
    for expected, actual in zip(want, got, strict=True):
        if expected == "{id}":
            if _ID.fullmatch(actual) is None:
                return False
        elif expected != actual:
            return False
    return True
