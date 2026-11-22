"""Spytify 2.0.2's protocol, as the controller speaks it: spytifyd's JSON-RPC methods, its
notifications and their payloads, its error codes and its exit codes.

Source: Spytify's `pkg/proto` (proto.go, jsonrpc.go, contract.go) and `cmd/spytifyd/main.go` at
tag 2.0.2 (commit fef3f4e, the one the Dockerfile builds).
`tests/spytify/proto-2.0.2.schema.json` is that tag's `pkg/proto/schema.json` (MIT licence),
and `tests/test_spytify_protocol.py` checks these types against it.

**Frozen (S6 foundation).** The fake recorder builds its payloads with these types, the real
recorder (recorder/rpc.py) hands them on as `RecorderNotification`s, and the item engine reads
them with `parse_notification`. A change here is a change to all three: ask the orchestrator.

Wire rules:
- **Framing:** newline-delimited JSON-RPC 2.0 on the Unix socket `SPYTIFY_SOCKET`, one object per
  line, lines up to 1 MiB.
- **Requests** carry integer ids. A notification has a `method` and no `id`. A parse error is
  answered with id 0.
- **Go's `omitempty`:** an empty string, false, 0, an empty list or map, or null is left out of
  the payload. `to_params()` follows that, so the fake recorder sends what spytifyd sends.
  `from_params()` reads a missing key as that empty value.
- **Slow readers:** spytifyd queues 512 lines per client, then disconnects it. Read the socket
  all the time, even while waiting for nothing in particular.
- **Paths** (`track.finished.path`, `track.skipped.path`) are absolute, as Spytify wrote the file.
  The controller stores them relative to the music folder (contracts/schema.sql).
- **Artist** in `track.started` is MPRIS's artists joined by ", ". Spotify's MPRIS gives only the
  first one, so it's the first artist.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

PROTOCOL = 1  # proto.Protocol in 2.0.2

# --- Methods (client to spytifyd) ---------------------------------------------------------------

CORE_INFO = "core.info"
CORE_SHUTDOWN = "core.shutdown"
SESSION_START = "session.start"
SESSION_STOP = "session.stop"
SESSION_STATUS = "session.status"
SETTINGS_GET = "settings.get"
SETTINGS_SET = "settings.set"
SETTINGS_RESET = "settings.reset"
PLAYER_CONTROL = "player.control"
PLAYER_LAUNCH = "player.launch"
LOG_TAIL = "log.tail"
EVENTS_RECENT = "events.recent"
TRACK_KEEP = "track.keep"

METHODS = (
    CORE_INFO,
    CORE_SHUTDOWN,
    SESSION_START,
    SESSION_STOP,
    SESSION_STATUS,
    SETTINGS_GET,
    SETTINGS_SET,
    SETTINGS_RESET,
    PLAYER_CONTROL,
    PLAYER_LAUNCH,
    LOG_TAIL,
    EVENTS_RECENT,
    TRACK_KEEP,
)

# --- Notifications (spytifyd to every client) ---------------------------------------------------

SESSION_STATE = "session.state"
TRACK_STARTED = "track.started"
TRACK_FINISHED = "track.finished"
TRACK_SKIPPED = "track.skipped"
TRACK_KEEPABLE = "track.keepable"
LEVEL = "level"
SETTINGS_CHANGED = "settings.changed"
TARGET_STATE = "target.state"  # only the always-running daemon watches the target: not in --once
LOG = "log"
ERROR = "error"

EVENTS = (
    SESSION_STATE,
    TRACK_STARTED,
    TRACK_FINISHED,
    TRACK_SKIPPED,
    TRACK_KEEPABLE,
    LEVEL,
    SETTINGS_CHANGED,
    TARGET_STATE,
    LOG,
    ERROR,
)

# --- Enumerations -------------------------------------------------------------------------------

type SessionState = Literal["idle", "waiting", "recording", "ad", "paused", "stopping"]
type SkipReason = Literal[
    "duplicate", "too_short", "ad", "incomplete", "seeked", "low_quality", "silent"
]
type PlayerCmd = Literal["play", "pause", "next", "previous", "restart", "full_volume"]
type LogLevel = Literal["error", "info", "debug"]

# Spytify's `error` codes (proto.ErrorCode). The withdrawable ones are sent again with an empty
# `msg` once the problem is gone.
type ErrorCode = Literal[
    "output_dir",
    "disk_full",
    "temp_file",
    "write",
    "ring_overflow",
    "capture_stalled",
    "capture_silent",
    "capture_low_quality",
    "player_volume_low",
    "read",
    "encode",
    "rename",
    "counter_full",
]
WITHDRAWABLE: frozenset[str] = frozenset(
    {"capture_silent", "capture_low_quality", "player_volume_low"}
)

# JSON-RPC error codes (jsonrpc.go): the standard ones, then Spytify's application range.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TARGET_NOT_RUNNING = -32001
FFMPEG_MISSING = -32002
SESSION_ACTIVE = -32003
NO_SESSION = -32004
UNSUPPORTED = -32005  # e.g. "the player does not accept \"pause\"" on a stopped player
NOT_AVAILABLE = -32006
OUTPUT_DIR = -32007

MAX_LINE_BYTES = 1 << 20  # spytifyd refuses a longer line
CLIENT_BACKLOG = 512  # lines spytifyd queues for one client before disconnecting it


# --- Payload types ------------------------------------------------------------------------------
#
# Each mirrors one Go struct of proto.go, field for field. `to_params()` drops what Go's
# `omitempty` drops; `from_params()` reads a missing key as its empty value.


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    """Sets `key` unless Go's omitempty would drop `value`."""
    if value is None or value is False or value == "" or value == 0:
        return
    if isinstance(value, list | tuple | dict) and not value:
        return
    out[key] = value


def _str(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    return value if isinstance(value, str) else ""


def _int(params: Mapping[str, Any], key: str) -> int:
    value = params.get(key)
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def _float(params: Mapping[str, Any], key: str) -> float:
    value = params.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _bool(params: Mapping[str, Any], key: str) -> bool:
    return params.get(key) is True


def _obj(params: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = params.get(key)
    return value if isinstance(value, Mapping) else None


def _facts(params: Mapping[str, Any]) -> dict[str, str]:
    value = params.get("facts")
    if not isinstance(value, Mapping):
        return {}
    return {str(k): str(v) for k, v in value.items()}


@dataclass(frozen=True, slots=True)
class AudioSource:
    """The captured stream's format."""

    sample_rate: int
    channels: int

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "AudioSource":
        return cls(sample_rate=_int(params, "sample_rate"), channels=_int(params, "channels"))

    def to_params(self) -> dict[str, Any]:
        return {"sample_rate": self.sample_rate, "channels": self.channels}


@dataclass(frozen=True, slots=True)
class TrackCut:
    """How the recorder placed a take's start: `kind` first, boundary or interrupt; `by` silence,
    dip, edge, length or notice (first_sound or notice for a first track)."""

    kind: str
    by: str
    offset_ms: int

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "TrackCut":
        return cls(
            kind=_str(params, "kind"), by=_str(params, "by"), offset_ms=_int(params, "offset_ms")
        )

    def to_params(self) -> dict[str, Any]:
        return {"kind": self.kind, "by": self.by, "offset_ms": self.offset_ms}


@dataclass(frozen=True, slots=True)
class Track:
    """A track as the session sees it (`session.status`). `id` is the take id."""

    id: str
    artist: str
    title: str
    length_ms: int
    album: str = ""
    cover_url: str = ""

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "Track":
        return cls(
            id=_str(params, "id"),
            artist=_str(params, "artist"),
            title=_str(params, "title"),
            length_ms=_int(params, "length_ms"),
            album=_str(params, "album"),
            cover_url=_str(params, "cover_url"),
        )

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "artist": self.artist,
            "title": self.title,
            "length_ms": self.length_ms,
        }
        _put(out, "album", self.album)
        _put(out, "cover_url", self.cover_url)
        return out


@dataclass(frozen=True, slots=True)
class TrackStarted:
    """`track.started`: a take began (the boundary is committed). `id` is the take id,
    `<session id>-<nnn>` (for example `20261113-060012-002`)."""

    id: str
    artist: str
    title: str
    length_ms: int
    album: str = ""
    cover_url: str = ""
    source: AudioSource | None = None
    cut: TrackCut | None = None

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "TrackStarted":
        source = _obj(params, "source")
        cut = _obj(params, "cut")
        return cls(
            id=_str(params, "id"),
            artist=_str(params, "artist"),
            title=_str(params, "title"),
            length_ms=_int(params, "length_ms"),
            album=_str(params, "album"),
            cover_url=_str(params, "cover_url"),
            source=AudioSource.from_params(source) if source is not None else None,
            cut=TrackCut.from_params(cut) if cut is not None else None,
        )

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "artist": self.artist,
            "title": self.title,
            "length_ms": self.length_ms,
        }
        _put(out, "album", self.album)
        _put(out, "cover_url", self.cover_url)
        if self.source is not None:
            out["source"] = self.source.to_params()
        if self.cut is not None:
            out["cut"] = self.cut.to_params()
        return out


@dataclass(frozen=True, slots=True)
class FinishTimings:
    """How long saving a file took, step by step."""

    format: str
    trim_ms: int
    cover_ms: int
    encode_ms: int
    tag_ms: int
    total_ms: int

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "FinishTimings":
        return cls(
            format=_str(params, "format"),
            trim_ms=_int(params, "trim_ms"),
            cover_ms=_int(params, "cover_ms"),
            encode_ms=_int(params, "encode_ms"),
            tag_ms=_int(params, "tag_ms"),
            total_ms=_int(params, "total_ms"),
        )

    def to_params(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "trim_ms": self.trim_ms,
            "cover_ms": self.cover_ms,
            "encode_ms": self.encode_ms,
            "tag_ms": self.tag_ms,
            "total_ms": self.total_ms,
        }


@dataclass(frozen=True, slots=True)
class TrackFinished:
    """`track.finished`: a file was closed and tagged. It has no title: match it to its
    `track.started` by `id` (the take id). `path` is absolute.

    `partial` (saved with track.keep), `pause_fade` (" (pause fade)" in its name) and `low_volume`
    (" (low volume)") are takes that don't count as recorded: the track stays missing, and their
    key isn't added to Spytify's index.
    """

    id: str
    path: str
    duration_ms: int
    bytes: int
    tagged: bool
    counter: int = 0  # the number output.prefix=counter gave this file
    tagged_by: str = ""
    timings: FinishTimings | None = None
    partial: bool = False
    pause_fade: bool = False
    low_volume: bool = False

    @property
    def counted(self) -> bool:
        """The take counts as recorded (events.md `track.finished.counted`)."""
        return not (self.partial or self.pause_fade or self.low_volume)

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "TrackFinished":
        timings = _obj(params, "timings")
        return cls(
            id=_str(params, "id"),
            path=_str(params, "path"),
            duration_ms=_int(params, "duration_ms"),
            bytes=_int(params, "bytes"),
            tagged=_bool(params, "tagged"),
            counter=_int(params, "counter"),
            tagged_by=_str(params, "tagged_by"),
            timings=FinishTimings.from_params(timings) if timings is not None else None,
            partial=_bool(params, "partial"),
            pause_fade=_bool(params, "pause_fade"),
            low_volume=_bool(params, "low_volume"),
        )

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "path": self.path,
            "duration_ms": self.duration_ms,
            "bytes": self.bytes,
            "tagged": self.tagged,
        }
        _put(out, "counter", self.counter)
        _put(out, "tagged_by", self.tagged_by)
        if self.timings is not None:
            out["timings"] = self.timings.to_params()
        _put(out, "partial", self.partial)
        _put(out, "pause_fade", self.pause_fade)
        _put(out, "low_volume", self.low_volume)
        return out


@dataclass(frozen=True, slots=True)
class TrackSkipped:
    """`track.skipped`: a take that wasn't saved, and why. For a duplicate, `path` is the file the
    track already has (absolute), or `of` is the take of this session still saving it."""

    id: str
    reason: SkipReason
    path: str = ""
    of: str = ""

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "TrackSkipped":
        return cls(
            id=_str(params, "id"),
            reason=_str(params, "reason"),  # type: ignore[arg-type]
            path=_str(params, "path"),
            of=_str(params, "of"),
        )

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "reason": self.reason}
        _put(out, "path", self.path)
        _put(out, "of", self.of)
        return out


@dataclass(frozen=True, slots=True)
class TrackKeepable:
    """`track.keepable`: whether a skipped take can still be saved with `track.keep`. The held
    take's WAV stays in `<output>/.spytify/` until another track is saved (Spytify bug 4)."""

    id: str
    keepable: bool

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "TrackKeepable":
        return cls(id=_str(params, "id"), keepable=_bool(params, "keepable"))

    def to_params(self) -> dict[str, Any]:
        return {"id": self.id, "keepable": self.keepable}  # keepable has no omitempty


@dataclass(frozen=True, slots=True)
class SessionStateChanged:
    """`session.state`, on every transition. `playlist` is the .m3u8 Spytify wrote, only with
    output.playlist on, which the controller turns off."""

    state: SessionState
    playlist: str = ""

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "SessionStateChanged":
        return cls(state=_str(params, "state"), playlist=_str(params, "playlist"))  # type: ignore[arg-type]

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {"state": self.state}
        _put(out, "playlist", self.playlist)
        return out


@dataclass(frozen=True, slots=True)
class ChannelLevel:
    peak_dbfs: float
    rms_dbfs: float

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "ChannelLevel":
        return cls(peak_dbfs=_float(params, "peak_dbfs"), rms_dbfs=_float(params, "rms_dbfs"))

    def to_params(self) -> dict[str, Any]:
        return {"peak_dbfs": self.peak_dbfs, "rms_dbfs": self.rms_dbfs}


@dataclass(frozen=True, slots=True)
class Level:
    """`level`: at most 10 a second, only while recording. Channels left then right."""

    peak_dbfs: float
    rms_dbfs: float
    channels: tuple[ChannelLevel, ...] = ()

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "Level":
        raw = params.get("channels")
        channels = (
            tuple(ChannelLevel.from_params(c) for c in raw if isinstance(c, Mapping))
            if isinstance(raw, list)
            else ()
        )
        return cls(
            peak_dbfs=_float(params, "peak_dbfs"),
            rms_dbfs=_float(params, "rms_dbfs"),
            channels=channels,
        )

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {"peak_dbfs": self.peak_dbfs, "rms_dbfs": self.rms_dbfs}
        _put(out, "channels", [c.to_params() for c in self.channels])
        return out


@dataclass(frozen=True, slots=True)
class LogLine:
    """`log` (and `log.tail`'s lines): every log line, every level. `ts` is RFC 3339 with
    nanoseconds, in spytifyd's local time."""

    level: LogLevel
    msg: str
    ts: str

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "LogLine":
        return cls(level=_str(params, "level"), msg=_str(params, "msg"), ts=_str(params, "ts"))  # type: ignore[arg-type]

    def to_params(self) -> dict[str, Any]:
        return {"level": self.level, "msg": self.msg, "ts": self.ts}  # no omitempty

    def text(self) -> str:
        """The line as the --log-file and stderr have it: `<ts> <level, 5 wide> <msg>`."""
        return f"{self.ts} {self.level:<5} {self.msg}"


@dataclass(frozen=True, slots=True)
class SpytifyError:
    """`error`: a failure or a warning, by its code. An empty `msg` on a withdrawable code
    withdraws the warning (events.md `error.withdrawn`). `facts` hold no names or paths."""

    code: str
    msg: str
    fatal: bool = False
    source: AudioSource | None = None  # capture_low_quality
    free_mb: int | None = None  # disk_full
    volume: int | None = None  # player_volume_low, in percent
    facts: Mapping[str, str] = field(default_factory=dict)

    @property
    def withdrawn(self) -> bool:
        return self.code in WITHDRAWABLE and self.msg == ""

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "SpytifyError":
        source = _obj(params, "source")
        free_mb = params.get("free_mb")
        volume = params.get("volume")
        return cls(
            code=_str(params, "code"),
            msg=_str(params, "msg"),
            fatal=_bool(params, "fatal"),
            source=AudioSource.from_params(source) if source is not None else None,
            free_mb=free_mb if isinstance(free_mb, int) and not isinstance(free_mb, bool) else None,
            volume=volume if isinstance(volume, int) and not isinstance(volume, bool) else None,
            facts=_facts(params),
        )

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "msg": self.msg, "fatal": self.fatal}
        if self.source is not None:
            out["source"] = self.source.to_params()
        if self.free_mb is not None:  # a pointer in Go: 0 is still sent
            out["free_mb"] = self.free_mb
        if self.volume is not None:
            out["volume"] = self.volume
        _put(out, "facts", dict(self.facts))
        return out


@dataclass(frozen=True, slots=True)
class SettingsChanged:
    """`settings.changed`: after a settings.set or settings.reset, the keys that changed with
    their new values. --set overrides don't send it; output.prefix=counter does, as the counter
    moves on after each file (`output.counter_next`)."""

    values: Mapping[str, Any]

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "SettingsChanged":
        values = _obj(params, "values")
        return cls(values=dict(values) if values is not None else {})

    def to_params(self) -> dict[str, Any]:
        return {"values": dict(self.values)}


@dataclass(frozen=True, slots=True)
class TargetState:
    """`target.state`: the player process appeared or exited. The always-running daemon sends
    it; a `--once` recorder doesn't watch the target, so the controller never sees it."""

    running: bool
    pid: int = 0

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "TargetState":
        return cls(running=_bool(params, "running"), pid=_int(params, "pid"))

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {"running": self.running}
        _put(out, "pid", self.pid)
        return out


type Notification = (
    TrackStarted
    | TrackFinished
    | TrackSkipped
    | TrackKeepable
    | SessionStateChanged
    | Level
    | LogLine
    | SpytifyError
    | SettingsChanged
    | TargetState
)

_PARSERS: dict[str, Any] = {
    TRACK_STARTED: TrackStarted.from_params,
    TRACK_FINISHED: TrackFinished.from_params,
    TRACK_SKIPPED: TrackSkipped.from_params,
    TRACK_KEEPABLE: TrackKeepable.from_params,
    SESSION_STATE: SessionStateChanged.from_params,
    LEVEL: Level.from_params,
    LOG: LogLine.from_params,
    ERROR: SpytifyError.from_params,
    SETTINGS_CHANGED: SettingsChanged.from_params,
    TARGET_STATE: TargetState.from_params,
}


def parse_notification(method: str, params: Mapping[str, Any]) -> Notification | None:
    """A notification's payload as its type, or None for a method this protocol doesn't know
    (a newer spytifyd may add some: log it and go on)."""
    parser = _PARSERS.get(method)
    return parser(params) if parser is not None else None


# --- Results ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Check:
    """One line of core.info's capability probe. `ok` false on a check that isn't `advice`
    means recording can't work (on Linux: target, player_running, ffmpeg, encoder, capture,
    session_bus, player_heard, output_writable)."""

    name: str
    ok: bool
    id: str = ""
    detail: str = ""
    args: tuple[str, ...] = ()
    advice: bool = False
    facts: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "Check":
        args = params.get("args")
        return cls(
            name=_str(params, "name"),
            ok=_bool(params, "ok"),
            id=_str(params, "id"),
            detail=_str(params, "detail"),
            args=tuple(str(a) for a in args) if isinstance(args, list) else (),
            advice=_bool(params, "advice"),
            facts=_facts(params),
        )

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        _put(out, "id", self.id)
        out["name"] = self.name
        out["ok"] = self.ok
        _put(out, "detail", self.detail)
        _put(out, "args", list(self.args))
        _put(out, "advice", self.advice)
        _put(out, "facts", dict(self.facts))
        return out


@dataclass(frozen=True, slots=True)
class TargetInfo:
    """The resolved SPYTIFY_TARGET_* configuration. `process` and `mpris` are comma-joined."""

    process: str
    mpris: str = ""
    bundle_id: str = ""
    launch: str = ""

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "TargetInfo":
        return cls(
            process=_str(params, "process"),
            mpris=_str(params, "mpris"),
            bundle_id=_str(params, "bundle_id"),
            launch=_str(params, "launch"),
        )

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {"process": self.process}
        _put(out, "mpris", self.mpris)
        _put(out, "bundle_id", self.bundle_id)
        _put(out, "launch", self.launch)
        return out


@dataclass(frozen=True, slots=True)
class CoreInfo:
    """`core.info`'s result. `version` is proto.Version, "v2.0.2" for the image's build."""

    version: str
    protocol: int
    target: TargetInfo
    platform: str
    checks: tuple[Check, ...]
    warnings: tuple[str, ...] = ()

    def failed_checks(self) -> list[Check]:
        """The checks that fail and aren't advice: recording can't work while any does."""
        return [check for check in self.checks if not check.ok and not check.advice]

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "CoreInfo":
        target = _obj(params, "target") or {}
        checks = params.get("checks")
        warnings = params.get("warnings")
        return cls(
            version=_str(params, "version"),
            protocol=_int(params, "protocol"),
            target=TargetInfo.from_params(target),
            platform=_str(params, "platform"),
            checks=tuple(Check.from_params(c) for c in checks if isinstance(c, Mapping))
            if isinstance(checks, list)
            else (),
            warnings=tuple(str(w) for w in warnings) if isinstance(warnings, list) else (),
        )

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "version": self.version,
            "protocol": self.protocol,
            "target": self.target.to_params(),
            "platform": self.platform,
            "checks": [c.to_params() for c in self.checks],
        }
        _put(out, "warnings", list(self.warnings))
        return out


@dataclass(frozen=True, slots=True)
class Counters:
    """A session's counters (`session.status`). `skipped` counts every skip, ads included."""

    recorded: int = 0
    skipped: int = 0
    ads: int = 0
    bytes: int = 0
    overruns: int = 0

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "Counters":
        return cls(
            recorded=_int(params, "recorded"),
            skipped=_int(params, "skipped"),
            ads=_int(params, "ads"),
            bytes=_int(params, "bytes"),
            overruns=_int(params, "overruns"),
        )

    def to_params(self) -> dict[str, Any]:
        return {
            "recorded": self.recorded,
            "skipped": self.skipped,
            "ads": self.ads,
            "bytes": self.bytes,
            "overruns": self.overruns,
        }


@dataclass(frozen=True, slots=True)
class SessionStatus:
    """`session.status`'s result. Before the --once session starts (and after it ends), `state`
    is idle and `session_id` empty; `track` is the take being recorded, if any."""

    state: SessionState
    counters: Counters
    session_id: str = ""
    track: Track | None = None

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "SessionStatus":
        track = _obj(params, "track")
        return cls(
            state=_str(params, "state"),  # type: ignore[arg-type]
            counters=Counters.from_params(_obj(params, "counters") or {}),
            session_id=_str(params, "session_id"),
            track=Track.from_params(track) if track is not None else None,
        )

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {"state": self.state}
        _put(out, "session_id", self.session_id)
        if self.track is not None:
            out["track"] = self.track.to_params()
        out["counters"] = self.counters.to_params()
        return out


@dataclass(frozen=True, slots=True)
class SessionStopResult:
    """`session.stop`'s result. `stopping` is true for a graceful stop (the take finishes)."""

    recorded: int
    skipped: int
    stopping: bool = False

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "SessionStopResult":
        return cls(
            recorded=_int(params, "recorded"),
            skipped=_int(params, "skipped"),
            stopping=_bool(params, "stopping"),
        )

    def to_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {"recorded": self.recorded, "skipped": self.skipped}
        _put(out, "stopping", self.stopping)
        return out


@dataclass(frozen=True, slots=True)
class SettingsSetResult:
    """`settings.set`'s result: unknown keys and bad values are rejected one by one (`rejected`:
    key → why); the rest are applied and saved to $SPYTIFY_CONFIG."""

    applied: tuple[str, ...]
    rejected: Mapping[str, str]

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "SettingsSetResult":
        applied = params.get("applied")
        rejected = _obj(params, "rejected") or {}
        return cls(
            applied=tuple(str(k) for k in applied) if isinstance(applied, list) else (),
            rejected={str(k): str(v) for k, v in rejected.items()},
        )

    def to_params(self) -> dict[str, Any]:
        return {"applied": list(self.applied), "rejected": dict(self.rejected)}


# --- Exit codes (cmd/spytifyd/main.go) ----------------------------------------------------------

EXIT_OK = (
    0  # the --once session ended: idle exit, a stop (SIGTERM or session.stop), the player gone
)
EXIT_RUNTIME = 1  # see classify_exit
EXIT_USAGE = 2  # a bad --set, a bad environment (env.Validate), or a bad --fake timeline

type ExitCause = Literal[
    "ok",  # 0
    "bad_setting",  # 2
    "socket_in_use",  # 1: "socket <path>: another spytifyd is listening on <path>"
    "output_dir",  # 1: session.start -32007, the output folder can't be written to
    "ffmpeg",  # 1: session.start -32002, ffmpeg missing
    "no_player",  # 1: session.start -32001, the player wasn't there within --wait-target
    "files",  # 1: the --log-file, --events file or $SPYTIFY_CONFIG couldn't be opened
    "killed",  # a signal ended it (a negative return code): SIGKILL from the controller
    "other",  # 1 for any other reason
]

# What the controller does (plan § Starting Spytify for an item, Exit codes).
type ExitAction = Literal["none", "fail_run", "retry_once", "fail_item"]

EXIT_ACTIONS: dict[str, ExitAction] = {
    "ok": "none",
    "bad_setting": "fail_run",
    "output_dir": "fail_run",
    "ffmpeg": "fail_run",
    "files": "fail_run",
    "socket_in_use": "retry_once",  # kill_orphans, remove the socket, start again once
    "no_player": "fail_item",
    "killed": "fail_item",
    "other": "fail_item",
}


@dataclass(frozen=True, slots=True)
class ExitVerdict:
    cause: ExitCause
    action: ExitAction


def classify_exit(code: int | None, log_tail: Sequence[str]) -> ExitVerdict:
    """What an exit code means, from the code and spytifyd's last log lines (stderr or the
    --log-file). Error lines look like `<ts> error session.start: <message> (code -32007)` or
    `<ts> error socket <path>: another spytifyd is listening on <path>`."""
    if code is None or code < 0:
        cause: ExitCause = "killed"
    elif code == EXIT_OK:
        cause = "ok"
    elif code == EXIT_USAGE:
        cause = "bad_setting"
    else:
        text = "\n".join(log_tail)
        if "another spytifyd is listening" in text:
            cause = "socket_in_use"
        elif f"(code {OUTPUT_DIR})" in text:
            cause = "output_dir"
        elif f"(code {FFMPEG_MISSING})" in text:
            cause = "ffmpeg"
        elif f"(code {TARGET_NOT_RUNNING})" in text:
            cause = "no_player"
        elif "--events:" in text or "log file:" in text or "config.toml" in text:
            cause = "files"
        else:
            cause = "other"
    return ExitVerdict(cause=cause, action=EXIT_ACTIONS[cause])
