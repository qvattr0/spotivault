"""Stand-ins for the real ports that later steps build: the Web API (S5) and the recorder (S6).

Real mode needs one implementation of every port to start, before those steps exist. These answer
as honestly as they can: the Web API is "not connected", and a recorder never starts. S5 and S6
replace them in services.py with the real ones, then delete this file.
"""

from spotivault.ports import (
    OTHER,
    SETUP,
    ApiScope,
    Device,
    NotConnected,
    Page,
    PlayerState,
    Playlist,
    PlaylistEntry,
    RecorderSession,
    RecorderSpec,
    RecorderStartError,
    RepeatState,
    SavedAlbum,
    SavedTrack,
    SpotifyUser,
    TokenExchangeFailed,
    TokenGrant,
    Track,
)

_WEBAPI = "the Web API client isn't built yet (S5)"


class UnbuiltWebApi:
    """`ports.WebApi` until S5: every call raises NotConnected."""

    async def exchange_code(
        self,
        *,
        client_id: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        scope: ApiScope = SETUP,
    ) -> TokenGrant:
        raise TokenExchangeFailed(_WEBAPI)

    async def me(self, *, scope: ApiScope = OTHER) -> SpotifyUser:
        raise NotConnected(_WEBAPI)

    async def my_playlists(
        self, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[Playlist]:
        raise NotConnected(_WEBAPI)

    async def playlist(self, playlist_id: str, *, scope: ApiScope = OTHER) -> Playlist:
        raise NotConnected(_WEBAPI)

    async def playlist_items(
        self, playlist_id: str, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[PlaylistEntry]:
        raise NotConnected(_WEBAPI)

    async def saved_tracks(
        self, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[SavedTrack]:
        raise NotConnected(_WEBAPI)

    async def saved_albums(
        self, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[SavedAlbum]:
        raise NotConnected(_WEBAPI)

    async def album_tracks(
        self, album_id: str, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[Track]:
        raise NotConnected(_WEBAPI)

    async def devices(self, *, scope: ApiScope = OTHER) -> list[Device]:
        raise NotConnected(_WEBAPI)

    async def player_state(self, *, scope: ApiScope = OTHER) -> PlayerState | None:
        raise NotConnected(_WEBAPI)

    async def play(
        self,
        *,
        device_id: str,
        context_uri: str,
        offset_uri: str | None = None,
        position_ms: int = 0,
        scope: ApiScope = OTHER,
    ) -> None:
        raise NotConnected(_WEBAPI)

    async def pause(self, *, device_id: str, scope: ApiScope = OTHER) -> None:
        raise NotConnected(_WEBAPI)

    async def seek(self, position_ms: int, *, device_id: str, scope: ApiScope = OTHER) -> None:
        raise NotConnected(_WEBAPI)

    async def set_shuffle(self, state: bool, *, device_id: str, scope: ApiScope = OTHER) -> None:
        raise NotConnected(_WEBAPI)

    async def set_repeat(
        self, state: RepeatState, *, device_id: str, scope: ApiScope = OTHER
    ) -> None:
        raise NotConnected(_WEBAPI)


class UnbuiltRecorder:
    """`ports.Recorder` until S6: nothing can be recorded yet."""

    async def start(self, spec: RecorderSpec) -> RecorderSession:
        raise RecorderStartError("the recorder isn't built yet (S6)", exit_code=None)

    async def version(self) -> str | None:
        return None

    async def kill_orphans(self) -> int:
        return 0
