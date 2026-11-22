# Generated from contracts/openapi.yaml by scripts/gen_models.py. Do not edit by hand.

from __future__ import annotations

from typing import Annotated, Any, Literal
from pydantic import AnyUrl, AwareDatetime, BaseModel, ConfigDict, Field
from datetime import date


type SpotifyId = Annotated[
    str, Field(examples=["4glBZ0bZMgkmFyi6TD4h69"], pattern="^[0-9A-Za-z]{22}$")
]
"""
A Spotify base-62 id.
"""


type ItemId = Annotated[str, Field(pattern="^(liked|[0-9A-Za-z]{22})$")]
"""
A Library item id or an album id. Playlist and album ids are both Spotify base-62 ids; the controller looks in the Library first, then in Albums.
"""


class HealthChecks(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    db: Literal["ok", "fail"]
    display: Literal["ok", "fail"]
    pulseaudio: Literal["ok", "fail"]
    client: Literal["not_installed", "installing", "stopped", "running"]


class Health(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    status: Literal["ok", "starting", "degraded"]
    """
    `degraded` when a check below fails; the container stays healthy (200) so you can still reach the UI.
    """
    version: str
    boot_id: str
    """
    Changes on every controller start. The WS `hello` carries it too.
    """
    uptime_s: Annotated[int, Field(ge=0)]
    checks: HealthChecks


class SetupStep(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Literal[
        "tos",
        "client",
        "login",
        "client_settings",
        "webapi",
        "output",
        "playlists",
        "albums",
        "done",
    ]
    """
    Wizard steps 1 to 9, in order.
    """
    state: Literal["todo", "active", "done", "failed"]
    message: str | None = None
    """
    Why a step failed, when it did.
    """


class Setup(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    steps: Annotated[list[SetupStep], Field(max_length=9, min_length=9)]
    first_unfinished: (
        Literal[
            "tos",
            "client",
            "login",
            "client_settings",
            "webapi",
            "output",
            "playlists",
            "albums",
            "done",
        ]
        | None
    )
    completed: bool
    """
    Until true, every UI route redirects to the wizard.
    """
    tos_acknowledged_at: AwareDatetime | None


class ClientInstallError(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: Literal["network", "signature", "checksum", "disk_full", "missing_libraries", "unknown"]
    """
    `missing_libraries` means the image is too old for this client: update the image.
    """
    message: str


class ClientInstall(BaseModel):
    """
    The runtime install of the Spotify client into `/config/spotify`, by `spotify-install`. Q13, resolved in S0: it takes about 18 s, so it's a wizard step.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    state: Literal["not_started", "installing", "installed", "failed"]
    phase: Literal["release", "packages", "download", "unpack", "libraries", "switch"] | None
    progress: Annotated[float | None, Field(ge=0.0, le=1.0)]
    """
    Overall progress, when known.
    """
    bytes_done: Annotated[int | None, Field(ge=0)]
    bytes_total: Annotated[int | None, Field(ge=0)]
    version: str | None
    previous_version: str | None
    """
    The one previous version kept for rollback.
    """
    error: ClientInstallError | None
    log_tail: Annotated[list[str], Field(max_length=50)]
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None


class ClientStatusLoginSignals(BaseModel):
    """
    The raw signals behind `logged_in`, for the UI's diagnostics.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    mpris: bool
    """
    The client's MPRIS name is on the bus. Reported, but not part of `logged_in`.
    """
    user_folder: bool
    window_title: str | None
    """
    The client's main window title, or null when there's no window.
    """


class ClientStatus(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    installed: bool
    version: str | None
    running: bool
    logged_in: bool
    """
    Q2, resolved in S0: true when a `Users/*-user/` folder exists **and** the client's main window has a title other than plain "Spotify" ("Spotify Premium" when idle, "Artist - Title" while playing). A logged-out client still publishes MPRIS, so MPRIS isn't a signal. Wizard step 5 and the pre-run check also require the Web API device list to show our device.
    """
    login_signals: ClientStatusLoginSignals
    """
    The raw signals behind `logged_in`, for the UI's diagnostics.
    """
    device_name: str
    """
    `DEVICE_NAME`, the Connect device name.
    """
    restartable: bool
    """
    False during a run. The Player disables Restart client with its tooltip.
    """
    install: ClientInstall


class ChecklistRow(BaseModel):
    """
    One row of the step 4 table. Q3, resolved in S0: automix, normalization, equalizer, mono, streaming quality and auto adjust are `auto`, read from the prefs file. Crossfade, gapless and autoplay are stored on Spotify's servers, so they're `confirm`. Volume is `set_for_you`. The UI still reads `check` rather than assuming it.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: Literal[
        "crossfade",
        "gapless",
        "automix",
        "autoplay",
        "normalization",
        "equalizer",
        "mono",
        "streaming_quality",
        "auto_adjust_quality",
        "volume",
    ]
    section: Literal["playback", "audio_quality", "player"]
    required: str
    """
    The value to set, as the client labels it.
    """
    check: Literal["auto", "confirm", "set_for_you"]
    state: Literal["ok", "needs_change", "unknown"] | None
    """
    For `auto` rows. Null for the others.
    """
    confirmed: bool | None
    """
    For `confirm` rows. Null for the others.
    """
    blocker: bool
    """
    False for autoplay (the context-change check covers it) and volume (set for you).
    """


class AuthStart(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    authorize_url: AnyUrl
    redirect_uri: Literal["http://127.0.0.1:8888/callback"]
    expires_at: AwareDatetime
    """
    When the pending PKCE verifier is dropped (15 minutes).
    """


class Connection(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    state: Literal["not_configured", "disconnected", "ok", "expiring", "expired"]
    """
    `not_configured`: no Client ID. `disconnected`: a Client ID but no token. `expiring`: within 4 weeks of `expires_at` (the yellow banner). `expired`: past it, or Spotify answered `invalid_grant` (the red banner; scheduled runs are held).
    """
    display_name: str | None
    user_id: str | None
    client_id_masked: str | None
    """
    The first and last 4 characters.
    """
    authorized_at: AwareDatetime | None
    expires_at: AwareDatetime | None
    """
    `authorized_at` + 6 months. Refreshing never moves it.
    """
    scopes: list[str]


class Device(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str | None
    name: str
    type: str
    is_active: bool


class Devices(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    devices: list[Device]
    ours: Device | None
    device_name: str


class Volume(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    path: str
    mounted: bool
    """
    A separate mount, not the container's own filesystem.
    """
    writable: bool
    free_bytes: Annotated[int | None, Field(ge=0)]
    total_bytes: Annotated[int | None, Field(ge=0)]
    error: Literal["not_mounted", "not_writable", "not_found"] | None


class Storage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    music: Volume
    config: Volume
    min_free_bytes: Literal[2000000000]
    """
    A run refuses to start below this much free space in `/music` (2 GB).
    """
    ok: bool
    """
    `/music` is mounted, writable, and has at least `min_free_bytes` free.
    """


class Layout(BaseModel):
    """
    How new recordings are named. Maps to Spytify's `output.*` settings; the rules and the mapping are in `vectors/layouts.json`.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    pattern: Annotated[str, Field(max_length=200)]
    """
    Between the fixed `Music/` and the extension. Default `{album_artist}/{album}/{track} - {title}`.
    """
    prefix: Literal["none", "counter", "track_number"]
    underscores: bool
    strip_accents: bool


class Settings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["aac", "mp3", "flac", "wav"]
    bitrate: Literal[256, 320] | None
    """
    Offered pairs: aac 256 (default), aac 320, mp3 320, flac null, wav null.
    """
    extension: Literal["m4a", "mp3", "flac", "wav"]
    """
    Read-only, from `format`.
    """
    write_m3u: bool
    save_spotify_covers: bool
    auto_track_owned: bool
    layout: Layout


class SettingsUpdate(BaseModel):
    """
    Any subset of Settings. `format` and `bitrate` go together.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["aac", "mp3", "flac", "wav"] | None = None
    bitrate: Literal[256, 320] | None = None
    write_m3u: bool | None = None
    save_spotify_covers: bool | None = None
    auto_track_owned: bool | None = None
    layout: Layout | None = None


class ContainerVersions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    image: str
    controller: str
    spytify: str
    client: str | None


class Container(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    device_name: str
    tz: str
    music_source: str | None
    """
    Where `/music` comes from, as the container's `/proc/self/mountinfo` shows it: the mounted folder's path inside its own file system. That's the host's full path only when the folder is on the host's root file system: a share at `/volume6/Music`, on a volume mounted at `/volume6`, shows as `/Music`. A whole file system mounted at `/music` shows its source, such as a device. Null when it can't be read. The container can't see the host's own mounts.
    """
    umask: Annotated[str, Field(pattern="^[0-7]{3,4}$")]
    ui_password_env_set: bool
    """
    `UI_PASSWORD` is set but not enforced in M1 (D11). Settings shows a warning.
    """
    versions: ContainerVersions


class LibrarySummary(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    owned_count: Annotated[int, Field(ge=0)]
    """
    Playlists you created. Step 7's "You have 23 playlists".
    """
    owned_tracked: Annotated[int, Field(ge=0)]
    liked_tracked: bool
    added_count: Annotated[int, Field(ge=0)]
    """
    Followed and linked playlists in the Library.
    """
    tracked_count: Annotated[int, Field(ge=0)]
    """
    Every tracked item, Liked Songs included.
    """
    auto_track_owned: bool


class LibraryRefresh(BaseModel):
    """
    The answer to the Library's Refresh button. The refresh runs after it; its `catalog.refresh` events (events.md) tell how it went.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    state: Literal["started", "running"]
    """
    `started`: this press asked for a refresh, and it starts at once. `running`: a refresh was already going or asked for, and this press joins it.
    """
    refresh_id: Annotated[int | None, Field(ge=1)]
    """
    The refresh that's going, once it has started; its `catalog.refresh` events carry the same id. Null while it waits for its turn: then its events carry the trigger `manual`.
    """


class UrlBody(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    url: Annotated[str, Field(max_length=500)]


class PlaylistPreview(BaseModel):
    """
    A playlist that can be added. A followed one comes from the last catalog refresh's `GET /me/playlists`, with its total. A linked one comes from `GET /playlists/{id}`, which answers with its name, owner, cover and `snapshot_id` but no `items`, so its total is null, and its `/items` answers 403 (S0, Q10).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(examples=["4glBZ0bZMgkmFyi6TD4h69"], pattern="^[0-9A-Za-z]{22}$")]
    """
    A Spotify base-62 id.
    """
    uri: str
    name: str
    owner: str
    """
    The owner's display name, or their id when Spotify gives none.
    """
    cover: str | None
    """
    A Spotify CDN URL, used straight away and never stored. Null when the playlist has no image, or (a suggestion) when no refresh since the controller started has seen one.
    """
    kind: Literal["followed", "linked"]
    item_access: bool
    """
    False for a linked playlist, and for a followed one you don't collaborate on.
    """
    total: Annotated[int | None, Field(ge=0)]
    """
    `items.total` for a followed playlist; null for a linked one (unknown).
    """
    already_added: bool


class ItemTrack(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    position: Annotated[int | None, Field(ge=1)]
    """
    Web API order, from 1. Null for tracks of a playlist without item access.
    """
    track_id: SpotifyId | None
    title: str
    artists: list[str]
    album: str | None
    duration_ms: Annotated[int | None, Field(ge=0)]
    state: Literal["recorded", "skipped_duplicate", "missing", "failed", "new", "unplayable"]
    """
    A track's state on a detail page. `missing`: not recorded and not new. `new`: added since the last backup. `unplayable`: a local file or `is_playable: false`; never recorded, left out of totals.
    """
    size_bytes: Annotated[int | None, Field(ge=0)]
    path: str | None
    """
    Relative to the music folder, for the hover.
    """
    reason: str | None
    """
    The failure reason, for `failed`. Same values as TrackResult's `reason`.
    """
    recorded_at: AwareDatetime | None


class TrackList(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    item_id: Annotated[str, Field(pattern="^(liked|[0-9A-Za-z]{22})$")]
    """
    A Library item id or an album id. Playlist and album ids are both Spotify base-62 ids; the controller looks in the Library first, then in Albums.
    """
    item_access: bool
    total: Annotated[int | None, Field(ge=0)]
    duration_ms: Annotated[int | None, Field(ge=0)]
    """
    Sum over playable tracks. Null when unknown.
    """
    tracks: list[ItemTrack]


class AlbumsSummary(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    total: Annotated[int, Field(ge=0)]
    recorded: Annotated[int, Field(ge=0)]
    queued: Annotated[int, Field(ge=0)]
    partial: Annotated[int, Field(ge=0)]


class SavedAlbum(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(examples=["4glBZ0bZMgkmFyi6TD4h69"], pattern="^[0-9A-Za-z]{22}$")]
    """
    A Spotify base-62 id.
    """
    uri: str
    name: str
    artist: str
    year: int | None
    cover: str | None
    total: Annotated[int, Field(ge=0)]
    saved_at: AwareDatetime


class Backlog(BaseModel):
    """
    design.md § Backlog estimate, with D13. `seconds_*` are whole seconds (milliseconds summed, then rounded half up). `seconds_left` adds 35 s per item with something to record; the other `seconds_*` are music only. `finish_at` is null with Manual only, or when nothing is left.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    tracks_total: Annotated[int, Field(ge=0)]
    tracks_recorded: Annotated[int, Field(ge=0)]
    seconds_total: Annotated[int, Field(ge=0)]
    seconds_recorded: Annotated[int, Field(ge=0)]
    seconds_left: Annotated[int, Field(ge=0)]
    items_to_record: Annotated[int, Field(ge=0)]
    unknown_items: Annotated[int, Field(ge=0)]
    """
    Tracked playlists without item access that will play whole (not Up to date by D13).
    """
    finish_at: AwareDatetime | None
    as_of: AwareDatetime


class Counters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    recorded: Annotated[int, Field(ge=0)]
    skipped_duplicate: Annotated[int, Field(ge=0)]
    skipped_other: Annotated[int, Field(ge=0)]
    """
    Ads, Spytify's other skip reasons, and a take dropped because the backup was stopped mid-track (Stop now, or the container stopping): not failures.
    """
    failed: Annotated[int, Field(ge=0)]
    bytes_added: Annotated[int, Field(ge=0)]


class RunTimeLeft(BaseModel):
    """
    How long this run still records, worked out by the controller from what it has stored, with no Web API request. Only this run's items count: the whole backlog's time left is `Backlog.seconds_left`, the Full backup card's.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    seconds: Annotated[int, Field(ge=0)]
    """
    Recording time left at `as_of`, of the items whose length is known. It adds up the rest of the take recording now (its length less the time it has recorded), the current item's planned tracks that haven't started, and each waiting item's missing tracks (Up next, and interrupted items that will retry), from their stored durations, plus 35 s for each waiting item with a track to record, as the backlog estimate counts. A track two items share counts once, as Spytify records it once, and a track this run already recorded doesn't count again. Removed items don't count. A scheduled or start-up run stops at its window's end, so until a stop is asked for, it's at most the time from `as_of` to `window_end`. After Stop after this track, it's just the rest of that track, even past the window's end; after Stop now, 0. While the run is paused, it's what the run records once resumed: the paused item counts as waiting, as it runs again.
    """
    unknown_items: Annotated[int, Field(ge=0)]
    """
    Items still to run whose length isn't known, so they're left out of `seconds`: playlists played whole (followed and linked ones that aren't Up to date by D13, and any whose track list this run can't trust). The current item counts here while it plays whole. 0 once a stop is asked for, and when the window's end caps `seconds`, since nothing runs past it.
    """
    as_of: AwareDatetime
    """
    When `seconds` was worked out. While the run is running, finishing or stopping, the time since then counts down: show `seconds` less it, never under 0, and, until a stop is asked for, never more than the time left to `window_end` (then without `unknown_items`). While it's paused, the figure stands still, still capped at `window_end`. The controller works it out again at each planned track's start and end, each phase of the current item, each change to the queue, each change of the run's state and each move of `window_end`, and sends a `run.state` when it moved by 5 s or more from what the last one shows (its count-down; paused, the figure itself), or `unknown_items` changed.
    """


class QueueItemExpect(BaseModel):
    """
    The Up next row's "84 new", "11 tracks" or "checking".
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["new_tracks", "tracks", "checking"]
    count: Annotated[int | None, Field(ge=0)]


class QueueItemCounts(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    recorded: Annotated[int, Field(ge=0)]
    skipped: Annotated[int, Field(ge=0)]
    failed: Annotated[int, Field(ge=0)]


class QueueItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    item_id: Annotated[str, Field(pattern="^(liked|[0-9A-Za-z]{22})$")]
    """
    A Library item id or an album id. Playlist and album ids are both Spotify base-62 ids; the controller looks in the Library first, then in Albums.
    """
    kind: Literal["owned", "liked", "followed", "linked", "album"]
    name: str
    cover: str | None
    state: Literal[
        "up_next",
        "planning",
        "preflight",
        "preparing",
        "starting",
        "playing",
        "finishing",
        "interrupted",
        "done",
        "up_to_date",
        "partial",
        "stopped",
        "carried_over",
        "failed",
        "unavailable",
        "removed",
    ]
    """
    An item's state in a run. While it's the current item: `planning`, `preflight`, `preparing`,
    `starting`, `playing`, `finishing` (the M1 plan's item states). Waiting: `up_next`, or
    `interrupted` (re-queued at the end after its first stall; "Interrupted · will retry"). Outcomes:
    - `done`: everything planned was recorded.
    - `up_to_date`: nothing to record (also D13's unchanged followed playlists); no recorder started.
    - `partial`: a second stall, failed takes, or a Spytify error; the run went on.
    - `stopped`: the run was stopped during or before it.
    - `carried_over`: cut off by the end of a window.
    - `failed`: the item couldn't run (recorder exit, timeout).
    - `unavailable`: 404 or 403 on a playlist that was available before.
    - `removed`: removed from the run while Up next.

    """
    attempt: Annotated[int, Field(ge=1, le=2)]
    """
    2 after an interruption. A second interruption ends it as `partial`.
    """
    planned: Annotated[int | None, Field(ge=0)]
    """
    Tracks planned, once planning is done. Null while unknown or when it plays whole.
    """
    expect: QueueItemExpect
    """
    The Up next row's "84 new", "11 tracks" or "checking".
    """
    counts: QueueItemCounts
    badges: list[
        Literal[
            "up_to_date",
            "interrupted_retried",
            "interrupted_twice",
            "carried_over_in",
            "carried_over_out",
            "removed",
            "stopped",
        ]
    ]
    reason: str | None
    """
    Why it ended as it did, in English ("2 tracks failed: low volume").
    """


class RunTrack(BaseModel):
    """
    A row of the current item's live track table.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    position: Annotated[int | None, Field(ge=1)]
    track_id: SpotifyId | None
    title: str
    artists: list[str]
    duration_ms: Annotated[int | None, Field(ge=0)]
    state: Literal["pending", "recording", "recorded", "skipped_duplicate", "skipped", "failed"]
    size_bytes: Annotated[int | None, Field(ge=0)]
    reason: str | None
    take_id: str | None
    """
    Spytify's take id, once a take started.
    """


class NowPlaying(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    take_id: str
    track_id: SpotifyId | None
    title: str
    artist: str
    """
    The first artist, as MPRIS gives it.
    """
    album: str | None
    cover_url: str | None
    length_ms: Annotated[int, Field(ge=0)]
    started_at: AwareDatetime
    position: Annotated[int | None, Field(ge=1)]
    """
    The track's position in the item, when matched.
    """


class RunCreated(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    run_id: Annotated[int, Field(ge=1)]
    started: bool
    """
    True when a new run started; false when the items joined the current run.
    """
    added: list[ItemId]
    """
    A new run: the `items` given, or empty for Run now. Joining a run: the items that now wait right after the current item, in the given order, both new ones and ones already waiting that moved there. The current item, and items that already ended or were removed in this run, are left out: a run has one row per item.
    """


class HistoryRowWindow(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    start: AwareDatetime
    end: AwareDatetime


class HistoryRow(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[int, Field(ge=1)]
    kind: Literal["run", "missed", "skipped", "held"]
    """
    `missed`: spotivault was not running. `skipped`: the previous run was paused. `held`: the Spotify connection expired, or the client was logged out. Only `run` rows have counts.
    """
    trigger: Literal["scheduled", "run_now", "startup"]
    """
    `run_now` covers Run now, Back up now, Record now and Retry failed.
    """
    started_at: AwareDatetime
    """
    For rows with no run, the window's start.
    """
    ended_at: AwareDatetime | None
    duration_s: Annotated[int | None, Field(ge=0)]
    outcome: (
        Literal["completed", "completed_with_issues", "window_ended", "stopped", "failed"] | None
    )
    counters: Counters | None
    reason: str | None
    """
    A machine reason for `failed` and the no-run rows: `container_restarted`, `setting_drifted`, `client_logged_out`, `connection_expired`, `not_running`, `previous_paused`, `storage`, `device_missing`, `recorder`.
    """
    window: HistoryRowWindow | None


class RunItemCounts(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    recorded: Annotated[int, Field(ge=0)]
    skipped: Annotated[int, Field(ge=0)]
    failed: Annotated[int, Field(ge=0)]


class RunItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    item_id: Annotated[str, Field(pattern="^(liked|[0-9A-Za-z]{22})$")]
    """
    A Library item id or an album id. Playlist and album ids are both Spotify base-62 ids; the controller looks in the Library first, then in Albums.
    """
    kind: Literal["owned", "liked", "followed", "linked", "album"]
    name: str
    cover: str | None
    order: Annotated[int, Field(ge=1)]
    """
    The order it ran in.
    """
    state: Literal[
        "up_next",
        "planning",
        "preflight",
        "preparing",
        "starting",
        "playing",
        "finishing",
        "interrupted",
        "done",
        "up_to_date",
        "partial",
        "stopped",
        "carried_over",
        "failed",
        "unavailable",
        "removed",
    ]
    """
    An item's state in a run. While it's the current item: `planning`, `preflight`, `preparing`,
    `starting`, `playing`, `finishing` (the M1 plan's item states). Waiting: `up_next`, or
    `interrupted` (re-queued at the end after its first stall; "Interrupted · will retry"). Outcomes:
    - `done`: everything planned was recorded.
    - `up_to_date`: nothing to record (also D13's unchanged followed playlists); no recorder started.
    - `partial`: a second stall, failed takes, or a Spytify error; the run went on.
    - `stopped`: the run was stopped during or before it.
    - `carried_over`: cut off by the end of a window.
    - `failed`: the item couldn't run (recorder exit, timeout).
    - `unavailable`: 404 or 403 on a playlist that was available before.
    - `removed`: removed from the run while Up next.

    """
    badges: list[
        Literal[
            "up_to_date",
            "interrupted_retried",
            "interrupted_twice",
            "carried_over_in",
            "carried_over_out",
            "removed",
            "stopped",
        ]
    ]
    counts: RunItemCounts
    bytes: Annotated[int, Field(ge=0)]
    started_at: AwareDatetime | None
    ended_at: AwareDatetime | None
    reason: str | None
    can_retry: bool
    """
    It has failed tracks, and it's still in the Library or Albums. Shows Retry failed.
    """


class RunDetail(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    run: HistoryRow
    items: list[RunItem]


class TrackResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    position: Annotated[int | None, Field(ge=1)]
    track_id: SpotifyId | None
    title: str
    artists: list[str]
    result: Literal["recorded", "skipped", "failed"]
    reason: str | None
    """
    - `skipped`: Spytify's skip reason: `duplicate`, `ad`, `too_short`, `incomplete`, `seeked`,
      `low_quality` or `silent`; or `discarded`: the backup was stopped mid-track (Stop now,
      or the container stopping), so the take was dropped. It's recorded next time.
    - `failed`: `low_volume`, `recorder_error`, `unavailable`, `interrupted` or `discarded`:
      a partial take, which has a file; with no file, a take Stop now cut in an older run,
      from before such a take was skipped.

    """
    size_bytes: Annotated[int | None, Field(ge=0)]
    path: str | None
    """
    Relative to the music folder.
    """
    take_id: str | None
    at: AwareDatetime


class LastRunIssue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    item_id: Annotated[str, Field(pattern="^(liked|[0-9A-Za-z]{22})$")]
    """
    A Library item id or an album id. Playlist and album ids are both Spotify base-62 ids; the controller looks in the Library first, then in Albums.
    """
    name: str
    message: str
    """
    One line: "2 tracks failed: low volume".
    """


class LastRun(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    run: HistoryRow | None
    issues: Annotated[list[LastRunIssue], Field(max_length=3)]


type DayHoursDayHour = Annotated[int, Field(ge=0, le=23)]


class ScheduleNext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    at: AwareDatetime | None
    """
    The start of the first window that hasn't ended. Null with Manual only.
    """
    window_end: AwareDatetime | None
    in_progress: bool
    """
    Now is inside that window.
    """
    playlists_to_check: Annotated[int, Field(ge=0)]
    albums_queued: Annotated[int, Field(ge=0)]
    """
    Queued and Partial albums.
    """
    held_reason: (
        Literal[
            "connection_expired",
            "not_connected",
            "client_logged_out",
            "run_paused",
            "setup_incomplete",
        ]
        | None
    )
    """
    Why the next scheduled run won't start. The card turns red.
    """


class WebApiUsageTotals(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    requests: Annotated[int, Field(ge=0)]
    retried: Annotated[int, Field(ge=0)]
    """
    Rows with attempt > 1.
    """
    rate_limited: Annotated[int, Field(ge=0)]
    errors_4xx: Annotated[int, Field(ge=0)]
    errors_5xx: Annotated[int, Field(ge=0)]


class WebApiUsageByDayItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    day: date
    method: Literal["GET", "PUT", "POST", "DELETE"]
    endpoint: str
    """
    An endpoint template, never an id.
    """
    lane: Literal["catalog", "playback", "auth"]
    requests: Annotated[int, Field(ge=0)]
    retried: Annotated[int, Field(ge=0)]
    rate_limited: Annotated[int, Field(ge=0)]
    status_2xx: Annotated[int, Field(ge=0)]
    status_4xx: Annotated[int, Field(ge=0)]
    status_5xx: Annotated[int, Field(ge=0)]
    p50_ms: Annotated[int | None, Field(ge=0)]
    p95_ms: Annotated[int | None, Field(ge=0)]


class WebApiUsageRateLimit(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    at: AwareDatetime
    method: str
    endpoint: str
    retry_after_s: Annotated[int | None, Field(ge=0)]
    scope: str
    """
    `run:<id>`, `refresh:<id>`, `setup` (the code exchange in wizard step 5) or `other`.
    """


class WebApiUsageWarning(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    at: AwareDatetime
    kind: Literal["rate_limited", "burst", "repeated_4xx", "above_median"]
    """
    `burst`: more than the threshold (default 30) in 30 s. `repeated_4xx`: five or more 4xx in a row from one endpoint. `above_median`: a refresh or run with more than twice its 7-day median of requests.
    """
    message: str


class WebApiUsage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    days: Annotated[int, Field(ge=1, le=90)]
    from_: Annotated[date, Field(alias="from")]
    to: date
    totals: WebApiUsageTotals
    by_day: list[WebApiUsageByDayItem]
    rate_limits: list[WebApiUsageRateLimit]
    """
    Every 429 in the period, newest first.
    """
    warnings: list[WebApiUsageWarning]
    """
    The usage-log warnings raised in the period (also in the controller log).
    """


class AcknowledgeTosRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    understood: Literal[True]


class ConfirmChecklistRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rows: dict[
        Literal[
            "crossfade",
            "gapless",
            "automix",
            "autoplay",
            "normalization",
            "equalizer",
            "mono",
            "streaming_quality",
            "auto_adjust_quality",
            "volume",
        ],
        bool,
    ]
    """
    Row id to ticked (true) or unticked (false).
    """


class SetSpotifyAppRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    client_id: Annotated[str, Field(pattern="^[0-9a-f]{32}$")]


class FinishSpotifyAuthRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    redirect_url: Annotated[str, Field(max_length=4096)]


class ListLibraryParametersQuery(BaseModel):
    filter: Literal["all", "tracked", "not_tracked", "owned", "added"] = "all"
    q: Annotated[str | None, Field(max_length=200)] = None
    sort: Literal["recently_backed_up", "name", "recently_added", "track_count"] = (
        "recently_backed_up"
    )


class GetLibrarySuggestionsParametersQuery(BaseModel):
    q: Annotated[str | None, Field(max_length=200)] = None


class GetLibrarySuggestionsResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    items: list[PlaylistPreview]


class PatchLibraryItemRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    tracked: bool


class GetLibraryItemCoverParametersQuery(BaseModel):
    size: Literal["thumb", "full"] = "thumb"


class ListAlbumsParametersQuery(BaseModel):
    filter: Literal["all", "recorded", "queued", "partial"] = "all"
    q: Annotated[str | None, Field(max_length=200)] = None
    sort: Literal["recently_added", "album", "artist", "year"] = "recently_added"


class AddAlbumsRequestAddAlbumsRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ids: Annotated[list[SpotifyId], Field(max_length=500, min_length=1)]


class AddAlbumsRequestAddAlbumsRequest1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    all: Literal[True]


type AddAlbumsRequest = AddAlbumsRequestAddAlbumsRequest | AddAlbumsRequestAddAlbumsRequest1


class AddAlbumsResponseSkippedItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(examples=["4glBZ0bZMgkmFyi6TD4h69"], pattern="^[0-9A-Za-z]{22}$")]
    """
    A Spotify base-62 id.
    """
    reason: Literal["already_added", "not_saved", "not_found"]


class GetSavedAlbumsResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    saved_total: Annotated[int, Field(ge=0)]
    """
    Every saved album, added or not. Step 8's "You have 42 saved albums".
    """
    items: list[SavedAlbum]


class GetAlbumCoverParametersQuery(BaseModel):
    size: Literal["thumb", "full"] = "thumb"


class ListRunsParametersQuery(BaseModel):
    cursor: Annotated[str | None, Field(max_length=200)] = None
    filter: Literal["all", "with_issues", "scheduled", "run_now"] = "all"
    limit: Annotated[int, Field(ge=1, le=100)] = 50


class ListRunsResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    runs: list[HistoryRow]
    next_cursor: str | None


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    items: Annotated[list[ItemId] | None, Field(max_length=500, min_length=1)] = None


class StopCurrentRunRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    mode: Literal["after_track", "now"]


class GetRunItemTracksResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    tracks: list[TrackResult]


class GetWebApiUsageParametersQuery(BaseModel):
    days: Annotated[int, Field(ge=1, le=90)] = 7


class ErrorError(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: Literal[
        "validation_failed",
        "not_found",
        "invalid_url",
        "private",
        "spotify_owned",
        "already_added",
        "not_removable",
        "invalid_layout",
        "run_active",
        "no_run",
        "not_paused",
        "item_is_current",
        "setup_incomplete",
        "no_client_id",
        "not_connected",
        "connection_expired",
        "client_not_installed",
        "client_logged_out",
        "install_in_progress",
        "invalid_redirect",
        "access_denied",
        "state_mismatch",
        "no_pending_auth",
        "token_exchange_failed",
        "rate_limited",
        "spotify_unavailable",
        "internal",
        "forbidden",
    ]
    """
    Every error code the API returns. New codes are additions, never renames.
    """
    message: str
    """
    English, for logs. The UI words known codes itself.
    """
    details: dict[str, Any] | None
    """
    Facts for the code, such as `field`, `reason`, `placeholder`, `ids` or `retry_after_s`.
    """


class Error(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: ErrorError


class Checklist(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rows: list[ChecklistRow]
    ready: bool
    """
    Every blocker row is OK (Auto) or ticked (Confirm). Step 4's Continue, and the pre-run check.
    """
    checked_at: AwareDatetime


class ItemProgress(BaseModel):
    """
    Set while the item is in the current run; null otherwise.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    run_id: int
    state: Literal[
        "up_next",
        "planning",
        "preflight",
        "preparing",
        "starting",
        "playing",
        "finishing",
        "interrupted",
        "done",
        "up_to_date",
        "partial",
        "stopped",
        "carried_over",
        "failed",
        "unavailable",
        "removed",
    ]
    """
    An item's state in a run. While it's the current item: `planning`, `preflight`, `preparing`,
    `starting`, `playing`, `finishing` (the M1 plan's item states). Waiting: `up_next`, or
    `interrupted` (re-queued at the end after its first stall; "Interrupted · will retry"). Outcomes:
    - `done`: everything planned was recorded.
    - `up_to_date`: nothing to record (also D13's unchanged followed playlists); no recorder started.
    - `partial`: a second stall, failed takes, or a Spytify error; the run went on.
    - `stopped`: the run was stopped during or before it.
    - `carried_over`: cut off by the end of a window.
    - `failed`: the item couldn't run (recorder exit, timeout).
    - `unavailable`: 404 or 403 on a playlist that was available before.
    - `removed`: removed from the run while Up next.

    """
    recorded: Annotated[int, Field(ge=0)]
    """
    Tracks recorded in this run so far.
    """
    planned: Annotated[int | None, Field(ge=0)]
    """
    Tracks this run plans to record. Null when the item plays whole (no item access).
    """


class LibraryItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(pattern="^(liked|[0-9A-Za-z]{22})$")]
    """
    A Spotify playlist id, or `liked` for Liked Songs.
    """
    kind: Literal["owned", "liked", "followed", "linked"]
    """
    A followed playlist you collaborate on has item access and behaves like `owned`, but keeps its kind.
    """
    uri: str
    name: str
    """
    The playlist's name, or "Liked Songs". Always known: a linked playlist's comes from `GET /playlists/{id}` (S0, Q10).
    """
    owner: str
    """
    The owner's display name (their id when Spotify gives none), or `you`.
    """
    cover: str | None
    """
    A thumbnail URL under `/api/library/{id}/cover`. Null for Liked Songs, which shows its tile.
    """
    cover_source: Literal["custom", "spotify", "none"]
    """
    `custom` is deferred, so M1 only sends `spotify` or `none`.
    """
    tracked: bool
    item_access: bool
    """
    False for followed and linked playlists you don't collaborate on. Their track list is unknown.
    """
    total: Annotated[int | None, Field(ge=0)]
    """
    The playable tracks of its stored track list. Without one, a followed playlist's `items.total` from `GET /me/playlists` (every entry, playable or not: web-ui.md's "32 / 35 recorded"). Null for a linked playlist, whose total is unknown.
    """
    recorded: Annotated[int, Field(ge=0)]
    new: Annotated[int | None, Field(ge=0)]
    """
    Tracks added since the last backup. Null when unknown.
    """
    last_backup_at: AwareDatetime | None
    status: Literal[
        "not_tracked",
        "never_backed_up",
        "up_to_date",
        "new",
        "partial",
        "queued",
        "recording",
        "unavailable",
    ]
    """
    The pill. `new` goes with the `new` count ("n new").
    """
    removable: bool
    """
    True for followed and linked items only.
    """
    progress: ItemProgress | None


class Album(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(examples=["4glBZ0bZMgkmFyi6TD4h69"], pattern="^[0-9A-Za-z]{22}$")]
    """
    A Spotify base-62 id.
    """
    uri: str
    name: str
    artist: str
    year: int | None
    cover: str | None
    total: Annotated[int, Field(ge=0)]
    """
    Playable tracks. Album totals are always known.
    """
    recorded: Annotated[int, Field(ge=0)]
    status: Literal["queued", "recording", "recorded", "partial", "unavailable"]
    added_at: AwareDatetime
    completed_at: AwareDatetime | None
    progress: ItemProgress | None


class RunSummary(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[int, Field(ge=1)]
    trigger: Literal["scheduled", "run_now", "startup"]
    """
    `run_now` covers Run now, Back up now, Record now and Retry failed.
    """
    state: Literal["idle", "starting", "running", "paused", "stopping", "finishing"]
    """
    `starting`: the pre-run check and catalog refresh. `finishing`: the ~25–30 s after an item, while the recorder saves the last track. `stopping`: a stop was asked for and is being carried out.
    """
    started_at: AwareDatetime
    window_end: AwareDatetime | None
    """
    The window's end, for scheduled and start-up runs ("stops by 07:00").
    """
    paused_reason: Literal["device_moved", "device_busy"] | None
    stop_mode: Literal["after_track", "now"] | None
    """
    Set once a stop is asked for, including the end of a window (`after_track`).
    """
    counters: Counters
    time_left: RunTimeLeft | None
    """
    This run's own time left, for the run header ("about 9 min left in this run"). Null while the run starts (its queue isn't built yet), and in the last `run.state`, once it has ended.
    """


class Status(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    state: Literal["idle", "starting", "running", "paused", "stopping", "finishing"]
    """
    `starting`: the pre-run check and catalog refresh. `finishing`: the ~25–30 s after an item, while the recorder saves the last track. `stopping`: a stop was asked for and is being carried out.
    """
    run: RunSummary | None
    item: QueueItem | None
    track: NowPlaying | None
    session_state: Literal["idle", "waiting", "recording", "ad", "paused", "stopping"] | None
    view_only: bool
    """
    The Player locks input (any state but `idle`).
    """


class CurrentRun(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    run: RunSummary | None
    queue: list[QueueItem]
    """
    Every item of the run in display order. Finished items first, then the current one, then Up next and interrupted ones.
    """
    current_tracks: list[RunTrack]


class Hours(BaseModel):
    """
    Each list holds the active hours of that day (0–23), local time in `TZ`. All lists empty means Manual only. Contiguous hours form one window, across midnight and from Sunday to Monday.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    mon: Annotated[list[DayHoursDayHour], Field(max_length=24)]
    tue: Annotated[list[DayHoursDayHour], Field(max_length=24)]
    wed: Annotated[list[DayHoursDayHour], Field(max_length=24)]
    thu: Annotated[list[DayHoursDayHour], Field(max_length=24)]
    fri: Annotated[list[DayHoursDayHour], Field(max_length=24)]
    sat: Annotated[list[DayHoursDayHour], Field(max_length=24)]
    sun: Annotated[list[DayHoursDayHour], Field(max_length=24)]


class Schedule(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    hours: Hours
    tz: str
    """
    Read-only. Set by `TZ`.
    """
    run_order: Annotated[
        list[Literal["carried_over", "liked", "playlists", "albums"]],
        Field(max_length=4, min_length=4),
    ]
    windows_per_week: Annotated[int, Field(ge=0)]
    hours_per_week: Annotated[int, Field(ge=0, le=168)]


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    hours: Hours
    tz: str | None = None
    """
    Ignored.
    """
    run_order: Annotated[
        list[Literal["carried_over", "liked", "playlists", "albums"]] | None,
        Field(max_length=4, min_length=4),
    ] = None
    """
    Left out keeps the stored order. The drag UI is deferred, so M1 keeps the default.
    """


class ListLibraryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    items: list[LibraryItem]


class ListAlbumsResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    items: list[Album]
    summary: AlbumsSummary


class AddAlbumsResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    added: list[Album]
    skipped: list[AddAlbumsResponseSkippedItem]
