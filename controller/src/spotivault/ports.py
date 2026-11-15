"""Interfaces for everything outside the controller, so real and fake implementations swap.

Each Protocol below has a real implementation (talking to the session bus, the Spotify client,
spytifyd, the Web API, the file system) and a fake one in `spotivault.fake`, used by fake mode
and the tests. `services.Ports` holds one of each. The engine and the routers only ever see these
types, never the implementations.

Rules for every implementation:
- **Never block the loop** (design.md § Stack): async libraries, subprocesses through asyncio,
  file work through `asyncio.to_thread`.
- **Times** are aware datetimes in UTC.
- **Errors** are the exception classes defined here, so callers handle real and fake alike.

Value types are frozen dataclasses: plain data, built by the implementation from what the outside
world returned, already in the controller's own names (the 2026 Web API names are read by the
WebApi implementation, never by its callers).
"""

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

# ================================================================================================
# Clock
# ================================================================================================


class Clock(Protocol):
    """Wall time, a monotonic timer and sleeping. The fake one moves only when a test says so."""

    def now(self) -> datetime:
        """The current time, aware, in UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds from an arbitrary start, never going back. For timeouts and intervals."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Waits `seconds` of this clock's time."""
        ...


# ================================================================================================
# MPRIS: the Spotify client on the D-Bus session bus
# ================================================================================================

type PlaybackStatus = Literal["Playing", "Paused", "Stopped"]


@dataclass(frozen=True, slots=True)
class TrackMetadata:
    """MPRIS `Metadata` of the loaded track.

    `track_id` is the id inside `mpris:trackid` (`/com/spotify/track/<id>`): the context entry's
    own id, which is how the engine identifies the loaded track (plan D10). Spotify's MPRIS gives
    only the first artist.
    """

    trackid: str | None  # mpris:trackid, as given
    track_id: str | None  # the 22-character Spotify id taken from it
    title: str | None  # xesam:title
    artists: tuple[str, ...]  # xesam:artist
    album: str | None  # xesam:album
    length_ms: int | None  # mpris:length (microseconds) / 1000
    url: str | None  # xesam:url
    art_url: str | None  # mpris:artUrl


@dataclass(frozen=True, slots=True)
class MprisChange:
    """One change seen on the bus. Fields that didn't change are None."""

    at: datetime
    playback_status: PlaybackStatus | None = None  # PropertiesChanged
    metadata: TrackMetadata | None = None  # PropertiesChanged
    seeked_ms: int | None = None  # the Seeked signal, in ms
    owner_present: bool | None = None  # NameOwnerChanged: the client appeared or went away


class Mpris(Protocol):
    """The client's `org.mpris.MediaPlayer2` interface (config.mpris_name) on the session bus.

    Only what the engine and the client manager need. MPRIS `Stop` is left out: Spotify ignores it.
    Methods that read a property return None when the client isn't on the bus. Player methods and
    `quit` raise MprisNoClient when the call can't have reached the client, and MprisUnavailable
    for any other D-Bus error or no answer in time. `subscribe()` raises MprisUnavailable on entry
    when the bus can't be reached, and its iterator raises it when the bus closes the connection.
    """

    async def owner_present(self) -> bool:
        """The MPRIS name has an owner. A logged-out client publishes it too (Q2), so this alone
        never means logged in."""
        ...

    async def playback_status(self) -> PlaybackStatus | None: ...

    async def metadata(self) -> TrackMetadata | None: ...

    async def position_ms(self) -> int | None:
        """`Position`, in ms."""
        ...

    async def play(self) -> None: ...

    async def pause(self) -> None: ...

    async def play_pause(self) -> None: ...

    async def next(self) -> None: ...

    async def previous(self) -> None: ...

    async def open_uri(self, uri: str) -> None:
        """`OpenUri`: the fallback way to start a context (FINDINGS row 9)."""
        ...

    async def quit(self) -> None:
        """`org.mpris.MediaPlayer2.Quit`: closes the client cleanly; it saves its prefs on the way
        out, and s6 starts it again (a restart)."""
        ...

    def subscribe(self) -> AbstractAsyncContextManager[AsyncIterator[MprisChange]]:
        """Changes as they happen, from the moment the context is entered:

            async with mpris.subscribe() as changes:
                async for change in changes:
                    ...

        Each subscriber gets every change. Leaving the context removes the D-Bus match rules.
        """
        ...


# ================================================================================================
# The Spotify client: install, process, login signals, prefs
# ================================================================================================


@dataclass(frozen=True, slots=True)
class InstallProgress:
    """One JSON line from `spotify-install` (design.md § The Spotify client).

    `stage` is the script's: release, download, verify, unpack, libraries, switch, done or error;
    or `log`: a line that isn't JSON (the script's stderr), from LocalClientControl.
    The last line has stage `done` or `error`. The client manager maps stages to the contract's
    `ClientInstall.phase`, and an error's `step` and message to its error code.
    """

    stage: str
    message: str
    percent: int | None = None  # download
    bytes: int | None = None  # download
    total: int | None = None  # download
    version: str | None = None  # done
    previous: str | None = None  # done: the version it replaced
    changed: bool | None = None  # done: false when that version was already installed
    step: str | None = None  # error: the step that failed (release, packages, space, ...)
    raw: Mapping[str, Any] = field(default_factory=dict)  # the whole line, for the log


@dataclass(frozen=True, slots=True)
class LoginSignals:
    """What shows the client is logged in (Q2, resolved in S0; web-ui.md step 3).

    Logged in means `user_folder` and a window title other than plain "Spotify". The MPRIS name
    is no signal: a logged-out client publishes it too. The client manager combines these.
    """

    user_folder: bool  # a /config/home/.config/spotify/Users/*-user/ folder exists
    window_title: str | None  # the client's main window title; None if no window was found


class ClientControl(Protocol):
    """The Spotify Linux client as a program: installing it, its process, its files."""

    def install(
        self, *, version: str | None = None, force: bool = False
    ) -> AsyncIterator[InstallProgress]:
        """Runs `spotify-install` and yields each progress line as it's printed.

        An async generator: iterate it to the end (the last item has stage `done` or `error`), or
        close it early (`contextlib.aclosing`) to stop the install. Raises InstallInProgress if
        another install holds the lock.
        """
        ...

    async def installed_version(self) -> str | None:
        """The version `/config/spotify/current` points to, or None when not installed."""
        ...

    async def is_running(self) -> bool:
        """The client's process is running."""
        ...

    async def restart(self) -> None:
        """Quits the client (MPRIS Quit, killed after 15 s) and returns once it's gone; s6 starts
        it again. For "Reset login screen" and the Player's Restart client."""
        ...

    async def login_signals(self) -> LoginSignals: ...

    async def prefs(self) -> dict[str, str] | None:
        """The logged-in user's prefs file (`Users/*-user/prefs`) as key → raw value, or None
        when there is none or it can't be read. A missing key means the setting is at its
        default (web-ui.md step 4)."""
        ...


# ================================================================================================
# The recorder: one spytifyd process per item
# ================================================================================================


@dataclass(frozen=True, slots=True)
class RecorderSpec:
    """Everything one `spytifyd --once --serve` process needs (plan § Starting Spytify for an item).

    The engine builds it; the recorder turns it into the command line:

        spytifyd --once --serve --idle-exit <idle_exit_s>s --wait-target <wait_target_s>s
          --log-file <log_file> --events <events_file> --set <key>=<value> …
        env SPYTIFY_SOCKET=<socket_path>, SPYTIFY_CONFIG and SPYTIFY_FFMPEG from the config
        cwd <work_dir> (empty: Spytify loads .env from its cwd), its own process group,
        umask <umask>
    """

    run_id: int
    item_id: str
    settings: Sequence[tuple[str, str]]  # every --set, in order, values as Spytify takes them
    log_file: Path
    events_file: Path
    socket_path: Path
    work_dir: Path
    umask: int
    idle_exit_s: int = 20
    wait_target_s: int = 60
    socket_timeout_s: float = 15.0  # the socket must appear within this, or the start fails


@dataclass(frozen=True, slots=True)
class RecorderNotification:
    """One JSON-RPC notification from spytifyd: `track.started`, `level`, `session.state`, …"""

    method: str
    params: Mapping[str, Any]
    received_at: datetime


class RecorderSession(Protocol):
    """A running spytifyd for one item."""

    @property
    def pid(self) -> int: ...

    @property
    def returncode(self) -> int | None:
        """The exit code once the process has exited, else None."""
        ...

    async def call(
        self, method: str, params: Mapping[str, Any] | None = None, *, timeout_s: float = 15.0
    ) -> Any:
        """One JSON-RPC 2.0 request with an integer id; returns its `result`.

        Raises RecorderRpcError for an error answer, TimeoutError when none comes in time, and
        RecorderGone when the socket is closed.
        """
        ...

    def notifications(self) -> AsyncIterator[RecorderNotification]:
        """Every notification, in order, for one consumer. It ends once the process has exited
        and every notification it sent before exiting has been read (the last take's
        `track.finished` arrives as it exits)."""
        ...

    async def wait(self) -> int:
        """Waits for the process to exit (the idle exit) and returns its exit code."""
        ...

    async def terminate(self, *, first_grace_s: float = 45.0, second_grace_s: float = 15.0) -> int:
        """SIGTERM (finish the current take), then a second SIGTERM after `first_grace_s` (stop at
        once), then SIGKILL after `second_grace_s`, to the process group. Returns the exit code."""
        ...

    async def kill(self) -> int:
        """SIGKILL to the process group at once. Returns the exit code."""
        ...

    async def events_file(self) -> list[RecorderNotification]:
        """The records in the spec's `--events` file, read after the exit, to check against the
        socket's notifications (it holds the last `track.finished` too)."""
        ...


class Recorder(Protocol):
    """Starts spytifyd processes, and cleans up after ones a crash left behind."""

    async def start(self, spec: RecorderSpec) -> RecorderSession:
        """Spawns spytifyd for one item and returns once its socket answers.

        Raises RecorderStartError when it exits first (2: a bad setting; 1: ffmpeg, the output
        folder, or the socket in use) or the socket doesn't appear within `socket_timeout_s`.
        """
        ...

    async def version(self) -> str | None:
        """`spytifyd --version`, such as "2.0.2", or None if it can't be run."""
        ...

    async def kill_orphans(self) -> int:
        """Kills spytifyd processes left from before a controller restart (start-up recovery).
        Returns how many."""
        ...


# ================================================================================================
# The Spotify Web API
# ================================================================================================


@dataclass(frozen=True, slots=True)
class ApiScope:
    """Who a request is for, for the usage log: `api_requests.scope_kind` and `scope_id`."""

    kind: Literal["refresh", "run", "setup", "other"]
    id: int | None = None  # catalog_refreshes.id or runs.id; required for refresh and run


OTHER = ApiScope("other")
SETUP = ApiScope("setup")


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of a paged listing. Ask for the next with `offset=next_offset`."""

    items: tuple[T, ...]
    offset: int
    limit: int
    total: int
    next_offset: int | None  # None on the last page


@dataclass(frozen=True, slots=True)
class Image:
    url: str  # use straight away, never store: playlist image URLs expire within a day
    width: int | None
    height: int | None


@dataclass(frozen=True, slots=True)
class Track:
    """A track or episode as a listing gives it. Everything the controller needs comes with the
    listings (no batch lookups since 2026), so it's stored when fetched."""

    id: str | None  # None for local files
    uri: str
    name: str
    artists: tuple[str, ...]  # names, in order; Spytify's key uses the first
    album_id: str | None
    album_name: str | None
    track_number: int | None
    disc_number: int | None
    duration_ms: int
    is_local: bool
    is_playable: bool | None  # with market=from_token; None when the answer didn't say
    is_episode: bool


@dataclass(frozen=True, slots=True)
class PlaylistEntry:
    """One entry of GET /playlists/{id}/items. The 2026 API puts the track under `item`."""

    added_at: str | None
    track: Track | None  # None for an entry with no `item`


@dataclass(frozen=True, slots=True)
class SavedTrack:
    """One entry of GET /me/tracks (Liked Songs), newest first. This endpoint kept `track`."""

    added_at: str
    track: Track


@dataclass(frozen=True, slots=True)
class Playlist:
    """A playlist from GET /me/playlists or GET /playlists/{id}."""

    id: str
    uri: str
    name: str
    owner_id: str | None
    owner_name: str | None
    collaborative: bool
    public: bool | None
    snapshot_id: str | None
    total: int | None  # `items.total`; None when absent (a linked playlist has none)
    images: tuple[Image, ...]


@dataclass(frozen=True, slots=True)
class Album:
    """An album. From GET /me/albums it carries its first page of tracks (`album.tracks`)."""

    id: str
    uri: str
    name: str
    artists: tuple[str, ...]
    release_date: str | None
    total_tracks: int
    images: tuple[Image, ...]
    tracks: Page[Track] | None  # the first page, when the listing includes it


@dataclass(frozen=True, slots=True)
class SavedAlbum:
    """One entry of GET /me/albums, most recently saved first. This endpoint kept `album`."""

    added_at: str
    album: Album


@dataclass(frozen=True, slots=True)
class SpotifyUser:
    id: str
    display_name: str | None


@dataclass(frozen=True, slots=True)
class Device:
    """A Connect device from GET /me/player/devices. Ours is the one named DEVICE_NAME."""

    id: str | None
    name: str
    type: str
    is_active: bool
    is_restricted: bool
    volume_percent: int | None


type RepeatState = Literal["off", "track", "context"]


@dataclass(frozen=True, slots=True)
class PlayerState:
    """GET /me/player. Used for the context and the device only: `track_id` can be a relinked id
    (D10), so the loaded track comes from MPRIS. Liked Songs is reported as a playlist alias
    (`spotify:playlist:37i9dQZF1F…`), which the engine treats as the same context."""

    device: Device | None
    is_playing: bool
    context_uri: str | None
    track_id: str | None
    progress_ms: int | None
    shuffle: bool | None
    repeat: RepeatState | None


@dataclass(frozen=True, slots=True)
class TokenGrant:
    """The answer to an authorization-code exchange (PKCE)."""

    access_token: str
    refresh_token: str
    expires_in_s: int
    scopes: tuple[str, ...]


class WebApi(Protocol):
    """The Spotify Web API, as design.md § Web API usage allows it, with the 2026 field names.

    Only these endpoints exist here; anything else needs a spec change first. The real one owns the
    tokens (in the store), the request scheduler (one request at a time, catalog calls 250 ms
    apart, playback calls first), retries (429 waits Retry-After; 5xx and timeouts after 5, 10,
    20 s; 401 refreshes once) and the usage log.

    Errors: NotConnected (no token), ConnectionExpired (`invalid_grant`), NoAccess (403),
    NotFound (404), RateLimited and SpotifyUnavailable (after the retries).

    Listings take `offset` and `limit` (50 at most) and return a Page. Track listings ask for
    `market=from_token`, so `is_playable` is set. Every call takes the `scope` it counts against.
    """

    async def exchange_code(
        self,
        *,
        client_id: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        scope: ApiScope = SETUP,
    ) -> TokenGrant:
        """POST accounts.spotify.com/api/token, grant_type authorization_code. The only call that
        works without a stored token; the caller stores the grant."""
        ...

    async def me(self, *, scope: ApiScope = OTHER) -> SpotifyUser:
        """GET /me: the display name for "Connected as …"."""
        ...

    async def my_playlists(
        self, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[Playlist]:
        """GET /me/playlists: owned, collaborative and followed, with `snapshot_id` and total."""
        ...

    async def playlist(self, playlist_id: str, *, scope: ApiScope = OTHER) -> Playlist:
        """GET /playlists/{id}: name, owner, images and snapshot_id, for a pasted link."""
        ...

    async def playlist_items(
        self, playlist_id: str, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[PlaylistEntry]:
        """GET /playlists/{id}/items. NoAccess (403) for playlists you neither own nor
        collaborate on."""
        ...

    async def saved_tracks(
        self, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[SavedTrack]:
        """GET /me/tracks: Liked Songs, newest first."""
        ...

    async def saved_albums(
        self, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[SavedAlbum]:
        """GET /me/albums, each album with its first page of tracks."""
        ...

    async def album_tracks(
        self, album_id: str, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[Track]:
        """GET /albums/{id}/tracks: the rest of an album longer than its first page."""
        ...

    async def devices(self, *, scope: ApiScope = OTHER) -> list[Device]:
        """GET /me/player/devices."""
        ...

    async def player_state(self, *, scope: ApiScope = OTHER) -> PlayerState | None:
        """GET /me/player, or None when nothing is playing anywhere (204)."""
        ...

    async def play(
        self,
        *,
        device_id: str,
        context_uri: str,
        offset_uri: str | None = None,
        position_ms: int = 0,
        scope: ApiScope = OTHER,
    ) -> None:
        """PUT /me/player/play on our device: the context, from `offset_uri` (by URI, never by
        position: positions skip unplayable entries). It also moves playback to `device_id`."""
        ...

    async def pause(self, *, device_id: str, scope: ApiScope = OTHER) -> None:
        """PUT /me/player/pause."""
        ...

    async def seek(self, position_ms: int, *, device_id: str, scope: ApiScope = OTHER) -> None:
        """PUT /me/player/seek: seek to 0 before the recorder starts (Spytify bug 2)."""
        ...

    async def set_shuffle(self, state: bool, *, device_id: str, scope: ApiScope = OTHER) -> None:
        """PUT /me/player/shuffle."""
        ...

    async def set_repeat(
        self, state: RepeatState, *, device_id: str, scope: ApiScope = OTHER
    ) -> None:
        """PUT /me/player/repeat."""
        ...


# ================================================================================================
# Storage: the music and config volumes
# ================================================================================================


@dataclass(frozen=True, slots=True)
class VolumeInfo:
    """What the storage check sees of one folder (GET /api/storage, wizard step 6)."""

    path: Path
    exists: bool
    mounted: bool  # a separate mount, not the container's own filesystem
    writable: bool  # a probe file could be written and removed by this process
    free_bytes: int | None
    total_bytes: int | None


class StorageProbe(Protocol):
    """The file system facts behind the storage check and Settings › Container."""

    async def volume(self, path: Path) -> VolumeInfo:
        """Checks one folder. Writes and removes a probe file to test `writable`."""
        ...

    async def mount_source(self, path: Path) -> str | None:
        """Where the mount at `path` comes from, from /proc/self/mountinfo, if it can be read: the
        folder's path inside its own file system (`/Music` for the NAS's `/volume6/Music`), or the
        source of a whole file system. Never the host's full path: the container can't see it."""
        ...


# ================================================================================================
# Desktop: the virtual screen, the sound server and the VNC server
# ================================================================================================


class Desktop(Protocol):
    """Xvfb, PulseAudio and x11vnc, which the client runs on. For the health check and WS /vnc."""

    async def display_ok(self) -> bool:
        """The X server answers on config.display."""
        ...

    async def audio_ok(self) -> bool:
        """PulseAudio answers on config.pulse_server."""
        ...

    async def open_vnc(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """A connection to the VNC server (x11vnc on 127.0.0.1:5900), as `asyncio.open_connection`
        returns it. Raises OSError when nothing is listening."""
        ...


# ================================================================================================
# Errors
# ================================================================================================


class PortError(Exception):
    """Base of every error a port raises on purpose."""


class MprisUnavailable(PortError):
    """An MPRIS call failed: the client isn't on the session bus, or the call got an error or no
    answer in time. Only MprisNoClient means the client can't have got the call."""


class MprisNoClient(MprisUnavailable):
    """The call can't have reached the client: the session bus can't be reached, or nobody owns
    the client's name. Any other MprisUnavailable (no answer in time, the client leaving the bus
    before it answered) may follow a call the client did get, such as a Quit it's acting on."""


class InstallInProgress(PortError):
    """Another spotify-install holds the lock."""


class RecorderStartError(PortError):
    """spytifyd exited, or its socket didn't appear, before it was ready."""

    def __init__(
        self, message: str, *, exit_code: int | None, log_tail: Sequence[str] = ()
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code  # 2: a bad setting; 1: ffmpeg, output folder or socket in use
        self.log_tail = list(log_tail)


class RecorderRpcError(PortError):
    """spytifyd answered a JSON-RPC request with an error, such as -32005 (the player doesn't
    accept that command) or -32007 (the output folder isn't writable)."""

    def __init__(self, method: str, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"{method}: {code} {message}")
        self.method = method
        self.code = code
        self.message = message
        self.data = data


class RecorderGone(PortError):
    """The recorder's socket closed, so no more requests can be made."""


class WebApiError(PortError):
    """Base of the Web API's errors. `status` is the HTTP status, when there was one."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class NotConnected(WebApiError):
    """No Client ID or no token: connect the Web API first (wizard step 5)."""


class ConnectionExpired(WebApiError):
    """Spotify answered `invalid_grant`: the 6-month authorization is over. Reconnect."""


class NoAccess(WebApiError):
    """403: no item access (a playlist you neither own nor collaborate on). Not retried."""


class NotFound(WebApiError):
    """404: the item is gone, or made by Spotify. An answer, not retried."""


class RateLimited(WebApiError):
    """429 that outlasted the scheduler's patience. `retry_after_s` is Spotify's Retry-After."""

    def __init__(
        self, message: str, *, retry_after_s: int | None, status: int | None = 429
    ) -> None:
        super().__init__(message, status=status)
        self.retry_after_s = retry_after_s


class SpotifyUnavailable(WebApiError):
    """5xx or timeouts after every retry."""


class TokenExchangeFailed(WebApiError):
    """Spotify refused the authorization code (`exchange_code`)."""


# ================================================================================================
# All of them together
# ================================================================================================


@dataclass(slots=True)
class Ports:
    """One implementation of each port. `services.build_services` picks real or fake ones."""

    clock: Clock
    mpris: Mpris
    client: ClientControl
    recorder: Recorder
    webapi: WebApi
    storage: StorageProbe
    desktop: Desktop
