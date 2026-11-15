"""The simulated Spotify Web API (`ports.WebApi`), over the Catalog and the SimPlayer.

It answers as the S0 captures did under the 2026 Development Mode rules (design.md § Web API
usage, prototype/FINDINGS.md rows 7, 17–22, 28, 29):
- **Listings** page by `offset` and `limit` (1–50, else 400), with the library's real totals.
- **Item access:** a playlist's items answer only for owned and collaborative ones; followed and
  linked ones give NoAccess (403). A Spotify-made playlist, or an unknown id, gives NotFound (404)
  on both the playlist and its items, though it plays by `context_uri`.
- **GET /playlists/{id}** of a followed or linked playlist has no `items`, so no total.
- **Player calls** drive the SimPlayer: our device is listed only while the client runs logged
  in, `play` takes playback over from another device, an `offset` at an unplayable entry plays a
  different one, `spotify:collection:tracks` answers but plays nothing, and Liked Songs is
  reported by its playlist alias.

The real client's tokens, scheduler, retries and usage log (S5) have no part here. Tests steer
it instead: `connected`, `expired`, and `failures` (errors the next calls raise, in order: a
RateLimited, a SpotifyUnavailable…). Every call is recorded in `calls` with its scope.

Owner: the fake agent.
"""

from dataclasses import dataclass, replace

from spotivault.fake.catalog import SPOTIFY_MADE_PREFIX, Catalog
from spotivault.fake.player import SimPlayer
from spotivault.ports import (
    OTHER,
    SETUP,
    ApiScope,
    Clock,
    ConnectionExpired,
    Device,
    NoAccess,
    NotConnected,
    NotFound,
    Page,
    PlayerState,
    Playlist,
    PlaylistEntry,
    RepeatState,
    SavedAlbum,
    SavedTrack,
    SpotifyUser,
    TokenExchangeFailed,
    TokenGrant,
    Track,
    WebApiError,
)

# The scopes wizard step 5 asks for (web-ui.md § 5).
SCOPES = (
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
    "user-read-playback-state",
    "user-modify-playback-state",
)


@dataclass(frozen=True, slots=True)
class FakeCall:
    """One call to the fake Web API: the endpoint template, and who it was for."""

    endpoint: str  # "GET /playlists/{id}/items"
    scope: ApiScope


class FakeWebApi:
    """`ports.WebApi` for fake mode. See the module docstring."""

    def __init__(self, clock: Clock, catalog: Catalog, player: SimPlayer) -> None:
        self.clock = clock
        self.catalog = catalog
        self.player = player
        self.connected = False  # a token is stored: exchange_code() connects
        self.expired = False  # every call raises ConnectionExpired (invalid_grant)
        self.failures: list[WebApiError] = []  # raised by the next calls, first one first
        self.calls: list[FakeCall] = []
        self.grants = 0
        self.world: object | None = None  # the FakeWorld it belongs to

    def endpoints(self) -> list[str]:
        """The endpoint of every call so far, in order."""
        return [call.endpoint for call in self.calls]

    # --- ports.WebApi --------------------------------------------------------------------------

    async def exchange_code(
        self,
        *,
        client_id: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        scope: ApiScope = SETUP,
    ) -> TokenGrant:
        """Any code works but one starting with "bad", and the client ID and verifier must be
        there."""
        self.calls.append(FakeCall("POST /api/token", scope))
        if self.failures:
            raise self.failures.pop(0)
        if not client_id or not code_verifier or code.startswith("bad"):
            raise TokenExchangeFailed("invalid_grant: Invalid authorization code", status=400)
        self.connected = True
        self.expired = False
        self.grants += 1
        return TokenGrant(
            access_token=f"fake-access-token-{self.grants}",
            refresh_token=f"fake-refresh-token-{self.grants}",
            expires_in_s=3600,
            scopes=SCOPES,
        )

    async def me(self, *, scope: ApiScope = OTHER) -> SpotifyUser:
        self._call("GET /me", scope)
        return self.catalog.user

    async def my_playlists(
        self, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[Playlist]:
        self._call("GET /me/playlists", scope)
        playlists = [item.playlist for item in self.catalog.library_playlists()]
        return _page(playlists, offset, limit)

    async def playlist(self, playlist_id: str, *, scope: ApiScope = OTHER) -> Playlist:
        self._call("GET /playlists/{id}", scope)
        item = self.catalog.playlists.get(playlist_id)
        if item is None or item.access == "spotify" or playlist_id.startswith(SPOTIFY_MADE_PREFIX):
            raise NotFound("Resource not found", status=404)
        if item.access in ("followed", "linked"):
            return replace(item.playlist, total=None)  # no `items` without item access
        return item.playlist

    async def playlist_items(
        self, playlist_id: str, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[PlaylistEntry]:
        self._call("GET /playlists/{id}/items", scope)
        item = self.catalog.playlists.get(playlist_id)
        if item is None or item.access == "spotify":
            raise NotFound("Resource not found", status=404)
        if item.access in ("followed", "linked"):
            raise NoAccess("Forbidden", status=403)
        entries = [PlaylistEntry(added_at=e.added_at, track=e.track) for e in item.entries]
        return _page(entries, offset, limit)

    async def saved_tracks(
        self, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[SavedTrack]:
        self._call("GET /me/tracks", scope)
        saved = [
            SavedTrack(added_at=entry.added_at or "", track=entry.track)
            for entry in self.catalog.liked
            if entry.track is not None
        ]
        return _page(saved, offset, limit)

    async def saved_albums(
        self, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[SavedAlbum]:
        self._call("GET /me/albums", scope)
        albums = []
        for item in self.catalog.saved_albums():
            tracks = [entry.track for entry in item.entries if entry.track is not None]
            first_page = _page(tracks, 0, 50)
            albums.append(
                SavedAlbum(
                    added_at=item.added_at or "", album=replace(item.album, tracks=first_page)
                )
            )
        return _page(albums, offset, limit)

    async def album_tracks(
        self, album_id: str, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[Track]:
        self._call("GET /albums/{id}/tracks", scope)
        item = self.catalog.albums.get(album_id)
        if item is None:
            raise NotFound("Resource not found", status=404)
        tracks = [entry.track for entry in item.entries if entry.track is not None]
        return _page(tracks, offset, limit)

    async def devices(self, *, scope: ApiScope = OTHER) -> list[Device]:
        self._call("GET /me/player/devices", scope)
        return self.player.devices()

    async def player_state(self, *, scope: ApiScope = OTHER) -> PlayerState | None:
        self._call("GET /me/player", scope)
        return self.player.player_state()

    async def play(
        self,
        *,
        device_id: str,
        context_uri: str,
        offset_uri: str | None = None,
        position_ms: int = 0,
        scope: ApiScope = OTHER,
    ) -> None:
        self._call("PUT /me/player/play", scope)
        self.player.api_play(device_id, context_uri, offset_uri, position_ms)

    async def pause(self, *, device_id: str, scope: ApiScope = OTHER) -> None:
        self._call("PUT /me/player/pause", scope)
        self.player.api_pause(device_id)

    async def seek(self, position_ms: int, *, device_id: str, scope: ApiScope = OTHER) -> None:
        self._call("PUT /me/player/seek", scope)
        self.player.api_seek(position_ms, device_id)

    async def set_shuffle(self, state: bool, *, device_id: str, scope: ApiScope = OTHER) -> None:
        self._call("PUT /me/player/shuffle", scope)
        self.player.api_shuffle(state, device_id)

    async def set_repeat(
        self, state: RepeatState, *, device_id: str, scope: ApiScope = OTHER
    ) -> None:
        self._call("PUT /me/player/repeat", scope)
        self.player.api_repeat(state, device_id)

    # --- Inside --------------------------------------------------------------------------------

    def _call(self, endpoint: str, scope: ApiScope) -> None:
        """Records the call, then raises what a disconnected, expired or failing API would."""
        self.calls.append(FakeCall(endpoint, scope))
        if not self.connected:
            raise NotConnected("not connected: connect the Web API first (wizard step 5)")
        if self.expired:
            raise ConnectionExpired("invalid_grant: Refresh token revoked", status=400)
        if self.failures:
            raise self.failures.pop(0)


def _page[T](items: list[T], offset: int, limit: int) -> Page[T]:
    if not 1 <= limit <= 50 or offset < 0:
        raise WebApiError(f"Invalid limit or offset ({limit}, {offset})", status=400)
    chunk = tuple(items[offset : offset + limit])
    total = len(items)
    end = offset + len(chunk)
    return Page(
        items=chunk,
        offset=offset,
        limit=limit,
        total=total,
        next_offset=end if end < total else None,
    )
