"""The simulated spytifyd (`ports.Recorder`): one `--once --serve --idle-exit` process per item.

**The protocol is Spytify 2.0.2's, exactly.** Every notification and every RPC result is built
with recorder/protocol.py's types, which follow pkg/proto/schema.json field for field (Go's
`omitempty` included), and tests/test_spytify_protocol.py validates them against that schema.
Methods, error codes and exit codes are spytifyd's (cmd/spytifyd/main.go, internal/core).

A SimRecorderSession watches the SimPlayer as Spytify watches the real client, and behaves as
prototype/FINDINGS.md and docs/upstream/spytify-bugs.md describe:

- **Takes:** a track that starts playing gets a take: `track.started` (`id` is the take id,
  `<session id>-<nnn>`; the artist is MPRIS's first one; the cover is `mpris:artUrl`). A track
  already in the duplicate index is `track.skipped duplicate` at once (with the file's path);
  with `recorder.skip_duplicates_forward=true` Spytify then presses Next. A take that played to
  its end is encoded, then `track.finished` comes with no title: match it by take id. A take cut
  short is `track.skipped incomplete`, then `track.keepable` (held for `track.keep`).
- **Already playing:** a track the player is on more than 300 ms in when the session starts isn't
  recorded. Played again from the start, it is, unless the restart lands within 2 s of where it
  was paused (bug 2: Spotify sends only `Seeked`, and Spytify takes it for the player restating
  its position). Paused at its start (≤ 300 ms), it waits for Play and is recorded.
- **The end of an album:** Spotify loads track 1 paused. Spytify keeps that change pending, so
  the last take stays open. At the idle exit (`idle_exit_s` after the player stops playing, once
  it has played) the pending change is forced: a phantom `track.started` for track 1 and
  `track.skipped duplicate` (or `incomplete`), with Next pressed when skip-forward is on (bug 1,
  racing the exit), then the last take's `track.finished` about 5 s later, then the exit (code 0)
  about 3 s after that: 28 s after the pause, as in FINDINGS' excerpt. `album_end_race = True`
  gives the other outcome of that race: the change resolves live, and with skip-forward on the
  album plays again, every track a duplicate.
- **A pause mid-item** (a takeover, a stall) ends the session at the idle exit too; the take it
  cut is incomplete. A take paused and resumed is saved with `pause_fade` and doesn't count.
- **Stopping** (Spytify's `handleStop`): the first SIGTERM (or `session.stop`) lets the current
  take finish: the session ends at the next change, or at the idle exit while paused (a pending
  change then closes the take and starts no new one: no phantom); with no take, at once. The
  second (or `session.stop {now}`) stops at once: the current take is `skipped incomplete` and
  held (`track.keepable`), even one that played to its end and only waited for the album-end
  change, and its WAV stays in `.spytify/` once the process exits (bug 4). SIGKILL ends it at
  once, leaving a `.part` file for a take being encoded (bug 5). The player quitting ends the
  session as well. `core.shutdown` stops at once.
- **Capture problems:** `set_capture("silent")` reports `capture_silent` after 10 s of a take
  (D12) and withdraws it when sound returns; the take is `skipped silent`. `"stalled"` reports
  `capture_stalled` after 10 s; as in 2.0.2 the session carries on (the controller ends the
  item), and the take it spoiled is `skipped incomplete`. A take recorded below full volume is
  saved " (low volume)" and doesn't count; `player.control full_volume` fixes that and withdraws
  `player_volume_low`.
- **Starting:** `start()` returns once the --once session has started, as the real port does: a
  bad `--set` exits 2; an output folder that's missing or not writable, or a socket another
  recorder holds, exits 1 (RecorderStartError, with spytifyd's log lines). With no player on the
  bus it waits `wait_target_s` for one, then exits 1.

Files: a finished take is written where Spytify's naming settings put it (`output.group_by`,
`output.template`, `output.prefix`, `output.underscores`, `output.ascii_filenames`), as a sparse
file of the reported size, and its key is appended to `<output.dir>/.spytify/recorded.jsonl`
({"Key", "Path"}), so the controller's file and index checks work. These small writes are done
in place, not in a thread, to keep simulated time exact; real code never does this. The
`--events` file (`{"method", "params"}` per line, as spytifyd's) and the `--log-file` are written
when the process ends. The events file leaves out `level` records, as the real port's reader
does (recorder/events_file.py): a long item sends hundreds of thousands, and writing them in
place at the exit blocked the event loop for half a second in fake mode.

Owner: the S6 foundation (frozen while S6's builders work: ask the orchestrator for a change).
"""

import asyncio
import contextlib
import itertools
import json
import random
import unicodedata
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from spotivault.fake.clock import Timer, schedule
from spotivault.fake.player import PlayerEvent, SimPlayer
from spotivault.fake.system import FakeStorageProbe
from spotivault.matching import read_recorded_index, track_key
from spotivault.ports import (
    Clock,
    RecorderGone,
    RecorderNotification,
    RecorderRpcError,
    RecorderSpec,
    RecorderStartError,
    TrackMetadata,
)
from spotivault.recorder import protocol as sp

SPYTIFY_VERSION = "2.0.2"  # what `spytifyd --version` gives, parsed (Recorder.version)
CORE_VERSION = "v2.0.2"  # proto.Version, as core.info reports it (the image builds it so)

FRESH_START_MS = 300  # paused at most this far in: the track waits for Play (freshStartMs)
SEEK_SLACK_MS = 2000  # a Seeked within this of the paused position is ignored (seekSlackMs)
RESTART_TO_MS = 1500  # a Seeked to before this counts as a restart
TRIM_MS = 1100  # Spytify trims about this much silence from a take (87.3 s of 88.4 s)
SKIP_FORWARD_DELAY_S = 0.5  # from a duplicate to Spotify playing the next track after Next
WATCHDOG_S = 10.0  # silent or stalled capture is reported after this (D12, Spytify #811)
SOURCE = sp.AudioSource(sample_rate=44_100, channels=2)  # what PulseAudio's null sink gives

type Capture = Literal["ok", "silent", "stalled"]

_FORMATS = {"aac": ".m4a", "mp3": ".mp3", "flac": ".flac", "wav": ".wav"}
_TEMPLATE_FIELDS = ("album_artist", "artist", "artists", "title", "album", "track", "year")


# --- Spytify's settings table (internal/settings/table.go at 2.0.2) ----------------------------

type _Kind = Literal[
    "string", "path", "bool", "int", "float", "enum", "int_enum", "duration", "template"
]


@dataclass(frozen=True, slots=True)
class _Setting:
    kind: _Kind
    default: Any
    choices: tuple[Any, ...] = ()
    low: float | None = None
    high: float | None = None


SETTINGS: dict[str, _Setting] = {
    "app.theme": _Setting("enum", "system", ("system", "light", "dark")),
    "app.notifications": _Setting("enum", "problems", ("problems", "tracks", "off")),
    "app.minimize_to_tray": _Setting("bool", False),
    "app.autostart_recording": _Setting("bool", False),
    "app.check_updates": _Setting("bool", True),
    "output.dir": _Setting("path", "~/Spytify"),
    "output.group_by": _Setting(
        "enum", "artist/album", ("none", "artist", "artist/album", "artists", "artists/album")
    ),
    "output.playlist": _Setting("bool", False),
    "output.template": _Setting("template", "{album_artist} - {title}"),
    "output.underscores": _Setting("bool", False),
    "output.ascii_filenames": _Setting("bool", False),
    "output.prefix": _Setting("enum", "none", ("none", "counter", "album_track")),
    "output.counter_next": _Setting("int", 1, (), 0, 999_999_999),
    "output.counter_width": _Setting("int", 3, (), 1, 9),
    "encode.format": _Setting("enum", "mp3", ("mp3", "aac", "flac", "wav")),
    "encode.bitrate_kbps": _Setting("int_enum", 160, (128, 160, 256, 320)),
    "tags.cover": _Setting("bool", True),
    "tags.cover_size": _Setting("enum", "medium", ("small", "medium", "large")),
    "tags.extra_to_subtitle": _Setting("bool", False),
    "tags.artist_separator": _Setting("string", ", "),
    "recorder.duplicates": _Setting("enum", "skip", ("skip", "suffix", "overwrite")),
    "recorder.skip_duplicates_forward": _Setting("bool", False),
    "recorder.single_track": _Setting("bool", False),
    "recorder.stop_with_player": _Setting("bool", False),
    "recorder.normalize": _Setting("bool", False),
    "recorder.trim_silence": _Setting("bool", True),
    "recorder.silence_db": _Setting("float", -50.0, (), -90, -20),
    "recorder.boundary_window_ms": _Setting("int", 300, (), 20, 2000),
    "recorder.pause_fade_db": _Setting("float", 20.0, (), 0, 60),
    "recorder.session_timer": _Setting("duration", "0s"),
    "recorder.target_lufs": _Setting("float", -14.0, (), -30, -5),
    "recorder.pause_on_disk_full": _Setting("bool", True),
    "player.mute_output": _Setting("bool", False),
    "recorder.mute_ads": _Setting("bool", False),
    "recorder.skip_short_untitled": _Setting("int", 60, (), 0, 600),
    "privacy.bug_tracker": _Setting("bool", True),
}


def coerce_setting(key: str, value: Any) -> tuple[Any, str | None]:
    """A value as Spytify's `Def.Coerce` takes it (a --set string, or a JSON value from
    settings.set): (the typed value, None), or (None, why it's rejected)."""
    setting = SETTINGS.get(key)
    if setting is None:
        return None, "unknown setting"
    kind = setting.kind
    if kind == "bool":
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str):
            text = value.strip()
            if text in ("1", "t", "T", "TRUE", "true", "True"):
                return True, None
            if text in ("0", "f", "F", "FALSE", "false", "False"):
                return False, None
        return None, "expected true or false"
    if kind in ("int", "int_enum"):
        number = _whole_number(value)
        if number is None:
            return None, "expected a whole number"
        if kind == "int_enum" and number not in setting.choices:
            return None, f"expected one of [{' '.join(str(c) for c in setting.choices)}]"
        if not _in_range(number, setting):
            return None, f"expected {setting.low:g} to {setting.high:g}"
        return number, None
    if kind == "float":
        real = _real_number(value)
        if real is None:
            return None, "expected a number"
        if not _in_range(real, setting):
            return None, f"expected {setting.low:g} to {setting.high:g}"
        return real, None
    if kind == "duration":
        if isinstance(value, str) and value.strip().endswith(("s", "m", "h")):
            return value.strip(), None
        return None, "expected a duration such as 90m or 2h"
    if not isinstance(value, str):
        return None, "expected a string"
    if kind == "enum":
        if value in setting.choices:
            return value, None
        return None, f"expected one of {', '.join(setting.choices)}"
    if kind == "path":
        text = value.strip()
        if not text or "\x00" in text:
            return None, "expected a folder path"
        if not (text.startswith("/") or text == "~" or text.startswith("~/")):
            return None, "expected an absolute path or one starting with ~/"
        return text, None
    if kind == "template":
        return _valid_template(value)
    if "\x00" in value:
        return None, "contains a NUL byte"
    return value, None


def _whole_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _real_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _in_range(number: float, setting: _Setting) -> bool:
    if setting.low is None or setting.high is None:
        return True
    return setting.low <= number <= setting.high


def _valid_template(template: str) -> tuple[str | None, str | None]:
    """Spytify's validTemplate: no / or \\, unknown {names} left out, and at least one
    placeholder left. {year} counts for Spytify; the controller's layout check refuses a name
    with only {year}, since the Linux client never gives one."""
    if not template.strip():
        return None, "template is empty"
    if "/" in template or "\\" in template:
        return None, "folders come from output.group_by; the template cannot contain / or \\"
    kept = template
    for start in [i for i, c in enumerate(template) if c == "{"]:
        end = template.find("}", start)
        if end == -1:
            continue
        name = template[start + 1 : end]
        if "{" not in name and name not in _TEMPLATE_FIELDS:
            kept = kept.replace("{" + name + "}", "")
    if not any("{" + name + "}" in kept for name in _TEMPLATE_FIELDS):
        return None, (
            "template needs at least one of {album_artist}, {artists}, {title}, {album}, {track}"
        )
    return kept, None


# --- The recorder -------------------------------------------------------------------------------


class SimRecorder:
    """`ports.Recorder` over the simulated player. The attributes below are the knobs."""

    def __init__(
        self,
        clock: Clock,
        player: SimPlayer,
        *,
        music_dir: Path,
        storage: FakeStorageProbe,
        mpris_name: str = "org.mpris.MediaPlayer2.spotify",
        process_name: str = "spotify",
    ) -> None:
        self.clock = clock
        self.player = player
        self.music_dir = music_dir  # where output.dir points when no --set gives it
        self.storage = storage
        self.mpris_name = mpris_name
        self.process_name = process_name
        self.sessions: list[SimRecorderSession] = []  # every session started, oldest first
        self.started: list[RecorderSpec] = []  # every spec start() was given
        # settings.set and the counter, saved to $SPYTIFY_CONFIG: they outlive a session.
        self.persisted_settings: dict[str, Any] = {}
        # Knobs for tests:
        self.start_failure: RecorderStartError | None = None  # the next start() raises it
        self.capture: Capture = "ok"
        self.ignore_sigterm = False  # SIGTERM does nothing; only SIGKILL ends it
        self.album_end_race = False  # the album-end change resolves live (bug 1, live path)
        self.lose_final_notifications = False  # the socket closes before the last ones
        self.level_interval_s: float | None = 0.1  # None: no level notifications
        self.encode_s = 2.0  # from a take's end to its track.finished
        self.final_encode_s = 5.0  # the same at the end of a session
        self.exit_delay_s = 3.0  # from the last track.finished to the exit
        self.hang_methods: set[str] = set()  # RPC methods that never answer
        self.orphans = 0  # recorders a crash left running: kill_orphans() finds them
        self.world: object | None = None  # the FakeWorld it belongs to
        self._pids = itertools.count(4100)

    @property
    def counter_next(self) -> int:
        """output.counter_next: the counter prefix goes on across sessions."""
        return int(self.persisted_settings.get("output.counter_next", 1))

    def live(self) -> "SimRecorderSession | None":
        """The session whose process is still running, if any."""
        for session in self.sessions:
            if session.returncode is None:
                return session
        return None

    def set_capture(self, capture: Capture) -> None:
        """Changes what the capture delivers, for the running session too."""
        self.capture = capture
        session = self.live()
        if session is not None:
            session.capture_changed()

    # --- ports.Recorder ------------------------------------------------------------------------

    async def start(self, spec: RecorderSpec) -> "SimRecorderSession":
        self.started.append(spec)
        if self.start_failure is not None:
            failure, self.start_failure = self.start_failure, None
            raise failure
        settings = {key: setting.default for key, setting in SETTINGS.items()}
        settings.update(self.persisted_settings)
        for key, raw in spec.settings:
            value, why = coerce_setting(key, raw)
            if why is not None:
                raise _start_error(self.clock, 2, f"--set {key}: {why}")
            settings[key] = value
        for other in self.sessions:
            if other.returncode is None and other.spec.socket_path == spec.socket_path:
                where = spec.socket_path
                raise _start_error(
                    self.clock, 1, f"socket {where}: another spytifyd is listening on {where}"
                )
        overridden = any(key == "output.dir" for key, _ in spec.settings)
        out_dir = Path(settings["output.dir"]) if overridden else self.music_dir
        if out_dir == self.music_dir:  # the music volume is always there in the container
            await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
        volume = self.storage.volumes.get(out_dir)
        writable = volume.writable if volume is not None else True
        if not writable or not await asyncio.to_thread(out_dir.is_dir):
            raise _start_error(
                self.clock,
                1,
                "session.start: the output folder cannot be written to: "
                f"open {out_dir}: permission denied (code {sp.OUTPUT_DIR})",
            )
        index = await asyncio.to_thread(
            read_recorded_index, out_dir / ".spytify" / "recorded.jsonl"
        )
        session = SimRecorderSession(self, spec, settings, next(self._pids), out_dir, index)
        self.sessions.append(session)
        session.begin()
        try:
            # --once: the session starts at once, or once the player shows up (--wait-target).
            await asyncio.shield(session.started)
        except RecorderStartError:
            await session.wait()
            raise
        return session

    async def version(self) -> str | None:
        return SPYTIFY_VERSION

    async def kill_orphans(self) -> int:
        found, self.orphans = self.orphans, 0
        return found


def _start_error(clock: Clock, code: int, message: str) -> RecorderStartError:
    """spytifyd exiting before its session started, with the log line it printed."""
    line = sp.LogLine(level="error", msg=message, ts=_rfc3339_nano(clock)).text()
    return RecorderStartError(
        f"spytifyd exited with code {code}: {message}", exit_code=code, log_tail=[line]
    )


@dataclass(slots=True)
class _Take:
    """One take Spytify is recording."""

    take_id: str
    meta: TrackMetadata
    artist: str  # MPRIS's first artist
    album_artist: str
    track_number: int | None
    key: str
    complete: bool = False  # the track played to its end
    paused: bool = False  # paused partway and resumed: pause_fade
    seeked: bool = False
    low_volume: bool = False
    silent: bool = False
    stalled: bool = False  # the capture stalled during it: incomplete


@dataclass(slots=True)
class _Encoding:
    timer: Timer
    path: Path


class SimRecorderSession:
    """`ports.RecorderSession`: one simulated spytifyd process. Built by SimRecorder.start()."""

    def __init__(
        self,
        recorder: SimRecorder,
        spec: RecorderSpec,
        settings: dict[str, Any],
        pid: int,
        out_dir: Path,
        index: dict[str, str],
    ) -> None:
        self.recorder = recorder
        self.spec = spec
        self.settings = settings  # typed, as Spytify's store holds them
        self.out_dir = out_dir
        self.clock = recorder.clock
        self.player = recorder.player
        self.session_id = self.clock.now().strftime("%Y%m%d-%H%M%S")
        self.state: sp.SessionState = "idle"  # Spytify's SessionState
        self.records: list[RecorderNotification] = []  # the --events file: all but `level`
        self.levels_sent = 0  # `level` notifications sent (not kept: see _notify)
        self.log_lines: list[str] = []  # what the --log-file holds
        self.calls: list[str] = []  # RPC methods called
        self.sigterms = 0
        self.recorded = 0
        self.skipped = 0
        self.bytes = 0
        self.started: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._pid = pid
        self._returncode: int | None = None
        self._index = index  # track key → path, for duplicates
        self._queue: asyncio.Queue[RecorderNotification | None] = asyncio.Queue()
        self._exit: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        self._take: _Take | None = None
        self._track_id: str | None = None  # what Spytify thinks is loaded, take or not
        self._ghost = False  # that track was already playing when the session started
        self._pending: TrackMetadata | None = None  # a change waiting for Play
        self._pending_album_end = False
        self._has_played = False
        self._stopping = False  # SIGTERM 1: end once the current take is done
        self._ended = False  # the session is over; the process is finishing
        self._take_count = 0
        self._last_cut: Literal["first", "boundary", "interrupt"] = "first"
        self._encoding: dict[str, _Encoding] = {}
        self._held: _Take | None = None  # skipped incomplete: waits for track.keep
        self._idle_timer: Timer | None = None
        self._level_timer: Timer | None = None
        self._watchdog: Timer | None = None
        self._wait_timer: Timer | None = None
        self._exit_timer: Timer | None = None
        self._reported: set[str] = set()  # warnings raised and not withdrawn
        self._stall_reported = False
        self._levels = random.Random(pid)

    # --- ports.RecorderSession -----------------------------------------------------------------

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def returncode(self) -> int | None:
        return self._returncode

    async def call(
        self, method: str, params: Mapping[str, Any] | None = None, *, timeout_s: float = 15.0
    ) -> Any:
        self.calls.append(method)
        if self._returncode is not None:
            raise RecorderGone("the recorder's socket is closed")
        if method in self.recorder.hang_methods:
            await self.clock.sleep(timeout_s)
            raise TimeoutError(f"{method}: no answer in {timeout_s} s")
        return self._answer(method, dict(params or {}))

    async def notifications(self) -> AsyncIterator[RecorderNotification]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    async def wait(self) -> int:
        return await asyncio.shield(self._exit)

    async def terminate(self, *, first_grace_s: float = 45.0, second_grace_s: float = 15.0) -> int:
        if self._returncode is not None:
            return self._returncode
        self.sigterm()
        if await self._exited_within(first_grace_s):
            return await self.wait()
        self.sigterm()
        if await self._exited_within(second_grace_s):
            return await self.wait()
        return await self.kill()

    async def kill(self) -> int:
        if self._returncode is None:
            self._log("error", "killed (SIGKILL)", notify=False)
            self._exit_now(-9)
        return await self.wait()

    async def events_file(self) -> list[RecorderNotification]:
        return list(self.records)

    # --- Signals -------------------------------------------------------------------------------

    def sigterm(self) -> None:
        """SIGTERM: the first finishes the current take, the second stops at once."""
        if self._returncode is not None:
            return
        self.sigterms += 1
        if self.recorder.ignore_sigterm:
            return
        if self.sigterms == 1:
            self._log(
                "info", "terminated received, finishing the current track (again to stop now)"
            )
            self._stop_after_take()
        else:
            self._log("info", "terminated received, stopping now")
            self._stop_now()

    # --- Player events -------------------------------------------------------------------------

    def begin(self) -> None:
        """The process is up and its socket answers: the session starts by itself (--once), at
        once or once the player shows up within --wait-target."""
        self._log("info", f"listening on unix {self.spec.socket_path}")
        self.player.listeners.append(self._on_player)
        if not self.player.on_bus:
            self._wait_timer = schedule(self.clock, self.spec.wait_target_s, self._no_target)
            return
        self._session_starts()

    def _session_starts(self) -> None:
        self._cancel("_wait_timer")
        if not self.started.done():
            self.started.set_result(None)
        self._set_state("waiting")
        self._look_at_player()

    def capture_changed(self) -> None:
        if self._ended:
            return
        capture = self.recorder.capture
        if capture == "ok":
            self._cancel("_watchdog")
            self._stall_reported = False
            if "capture_silent" in self._reported:
                self._reported.discard("capture_silent")
                self._error(sp.SpytifyError(code="capture_silent", msg=""))
        elif self._take is not None and self.state == "recording":
            self._arm_watchdog()

    def _look_at_player(self) -> None:
        meta = self.player.metadata()
        if meta is None:
            return
        position = self.player.position_ms()
        self._track_id = meta.track_id
        if position > FRESH_START_MS:
            self._ghost = True
            self._log(
                "info", f'"{meta.title}" is already playing; recording starts with the next track'
            )
        elif self.player.status == "Playing":
            self._has_played = True
            self._start_take(meta)
        else:
            self._pending = meta  # paused at its start: it waits for Play

    def _on_player(self, event: PlayerEvent) -> None:
        if self._ended or self._returncode is not None:
            return
        if event.kind == "bus":
            if not event.on_bus:
                self._log("info", "player interface gone")
                self._end()
            elif self._wait_timer is not None:
                self._session_starts()
        elif not self.started.done():
            return  # no session yet: nothing is watched
        elif event.kind == "track":
            self._on_track(event)
        elif event.kind == "status":
            self._on_status(event)
        elif event.kind == "seeked":
            self._on_seeked(event)

    def _on_track(self, event: PlayerEvent) -> None:
        meta = event.metadata
        if meta is None:
            self._log("info", "the player's metadata went empty")
            self._end()
            return
        if event.album_end and not self.recorder.album_end_race:
            # Track 1 loaded, paused at 0: the change waits for Play, the last take stays open.
            if self._take is not None:
                self._take.complete = event.previous_ended
            self._pending = meta
            self._pending_album_end = True
            return
        self._change_to(
            meta, playing=event.status == "Playing", previous_ended=event.previous_ended
        )

    def _on_status(self, event: PlayerEvent) -> None:
        if event.status == "Playing":
            self._has_played = True
            self._cancel("_idle_timer")
            meta = self.player.metadata()
            if self._pending is not None:
                pending, album_end = self._pending, self._pending_album_end
                self._change_to(pending, playing=True, previous_ended=album_end)
            elif self._take is not None and self._take.complete and meta is not None:
                # A one-track context played to its end and now plays again: a new take.
                self._change_to(meta, playing=True, previous_ended=True)
            elif self._take is not None:
                self._recording()
            else:
                self._set_state("waiting")
            return
        # Paused (Spotify never reports Stopped once something played).
        if self._take is not None and not self._take.complete and self._pending is None:
            self._take.paused = True
        self._cancel("_level_timer")
        self._cancel("_watchdog")
        self._set_state("paused")
        if self._has_played:
            self._cancel("_idle_timer")
            self._idle_timer = schedule(self.clock, self.spec.idle_exit_s, self._idle_exit)

    def _on_seeked(self, event: PlayerEvent) -> None:
        meta = event.metadata
        if meta is None:
            return
        if event.album_end:
            # A one-track context ended: back to 0 and paused on the same track. Spytify sees
            # no change, so the take stays open until the idle exit saves it (Panspermia).
            if self._take is not None:
                self._take.complete = event.previous_ended
            return
        before = event.seeked_from_ms or 0
        after = event.position_ms
        restarted = after < RESTART_TO_MS and abs(before - after) > SEEK_SLACK_MS
        if self._ghost and meta.track_id == self._track_id:
            if restarted:
                self._log("debug", f'"{meta.title}" started over: the player is at {after} ms')
                self._ghost = False
                if event.status == "Playing":
                    self._start_take(meta)
                else:
                    self._pending = meta
            return
        if self._take is not None:
            if restarted:
                self._close_take(reason="seeked")
                if event.status == "Playing":
                    self._start_take(meta)
                else:
                    self._pending = meta
            elif abs(before - after) > SEEK_SLACK_MS:
                self._take.seeked = True

    # --- Takes ---------------------------------------------------------------------------------

    def _change_to(self, meta: TrackMetadata, *, playing: bool, previous_ended: bool) -> None:
        """Another track is loaded: close the take before it, and start one for this track if
        it plays (else it waits for Play)."""
        self._pending = None
        self._pending_album_end = False
        if self._take is not None and previous_ended:
            self._take.complete = True
        self._last_cut = "boundary" if previous_ended else "interrupt"
        self._close_take()
        self._ghost = False
        self._track_id = meta.track_id
        if self._stopping:
            self._log("info", "stopping: the current take is done")
            self._end()
            return
        if playing:
            self._start_take(meta)
        else:
            self._pending = meta

    def _start_take(self, meta: TrackMetadata, *, phantom: bool = False) -> None:
        self._take_count += 1
        take_id = f"{self.session_id}-{self._take_count:03d}"
        artist = meta.artists[0] if meta.artists else ""
        entry = self.player.entry
        same = entry is not None and entry.track is not None and entry.track.id == meta.track_id
        album_artist = (entry.album_artist if same and entry else None) or artist
        track_number = entry.track.track_number if same and entry and entry.track else None
        self._track_id = meta.track_id
        cut_kind = "first" if self._take_count == 1 else self._last_cut
        cut = sp.TrackCut(
            kind=cut_kind,
            by={"first": "first_sound", "boundary": "silence", "interrupt": "edge"}[cut_kind],
            offset_ms=0,
        )
        self._notify(
            sp.TRACK_STARTED,
            sp.TrackStarted(
                id=take_id,
                artist=artist,
                title=meta.title or "",
                length_ms=meta.length_ms or 0,
                album=meta.album or "",
                cover_url=meta.art_url or "",
                source=SOURCE,
                cut=cut,
            ),
        )
        key = track_key(artist, meta.title or "")
        existing = self._index.get(key)
        if existing is not None and self.settings["recorder.duplicates"] == "skip":
            self.skipped += 1
            self._notify(
                sp.TRACK_SKIPPED, sp.TrackSkipped(id=take_id, reason="duplicate", path=existing)
            )
            if not phantom:
                self._set_state("waiting")
            if self.settings["recorder.skip_duplicates_forward"]:
                track_id = meta.track_id
                schedule(self.clock, SKIP_FORWARD_DELAY_S, lambda: self._skip_forward(track_id))
            return
        if phantom:
            self.skipped += 1
            self._notify(sp.TRACK_SKIPPED, sp.TrackSkipped(id=take_id, reason="incomplete"))
            return
        take = _Take(
            take_id=take_id,
            meta=meta,
            artist=artist,
            album_artist=album_artist,
            track_number=track_number,
            key=key,
            low_volume=self.player.volume < 100,
        )
        self._take = take
        if take.low_volume and "player_volume_low" not in self._reported:
            self._reported.add("player_volume_low")
            volume = self.player.volume
            self._error(
                sp.SpytifyError(
                    code="player_volume_low",
                    msg=f"the player's own volume is {volume}%: the recording is quieter",
                    volume=volume,
                )
            )
        if self.player.status == "Playing":
            self._recording()

    def _recording(self) -> None:
        """The take is being recorded: the meter runs, and the capture is watched."""
        self._set_state("recording")
        self._arm_level()
        if self.recorder.capture != "ok":
            self._arm_watchdog()

    def _skip_forward(self, track_id: str | None) -> None:
        """Spytify's Next after a duplicate (bug 1). It can land after the session ended."""
        if self._returncode is not None or not self.player.on_bus:
            return
        meta = self.player.metadata()
        if meta is not None and meta.track_id == track_id:
            self.player.mpris_next()

    def _close_take(
        self, *, reason: sp.SkipReason = "incomplete", delay_s: float | None = None
    ) -> None:
        take, self._take = self._take, None
        self._cancel("_level_timer")
        self._cancel("_watchdog")
        if take is None:
            return
        if take.silent:
            reason = "silent"
        elif take.seeked:
            reason = "seeked"  # a jump inside the take: it can't be a clean recording
        elif take.stalled:
            reason = "incomplete"
        if not take.complete or take.silent or take.seeked or take.stalled:
            self.skipped += 1
            self._notify(sp.TRACK_SKIPPED, sp.TrackSkipped(id=take.take_id, reason=reason))
            if reason != "silent":
                self._hold(take)  # cut short or moved: kept for track.keep
            return
        self._encode(take, delay_s=self.recorder.encode_s if delay_s is None else delay_s)

    def _hold(self, take: _Take) -> None:
        """Spytify's keeper: the last take cut short is held until another track is saved."""
        previous, self._held = self._held, take
        if previous is not None:
            self._notify(sp.TRACK_KEEPABLE, sp.TrackKeepable(id=previous.take_id, keepable=False))
        self._notify(sp.TRACK_KEEPABLE, sp.TrackKeepable(id=take.take_id, keepable=True))

    def _encode(self, take: _Take, *, delay_s: float, partial: bool = False) -> None:
        """The take is encoded; its track.finished comes `delay_s` later, with the file."""
        suffix = " (partial)" if partial else (" (low volume)" if take.low_volume else "")
        path = self._path_for(take, suffix)
        timer = schedule(self.clock, delay_s, lambda: self._finished(take, path, partial))
        self._encoding[take.take_id] = _Encoding(timer, path)

    def _finished(self, take: _Take, path: Path, partial: bool) -> None:
        self._encoding.pop(take.take_id, None)
        length = take.meta.length_ms or 0
        duration_ms = max(0, length - TRIM_MS)
        bitrate = int(self.settings["encode.bitrate_kbps"])
        size = duration_ms * bitrate // 8
        counted = not (take.low_volume or take.paused or partial)
        _write_take(path, size, self.spec.umask)
        counter = 0
        if self.settings["output.prefix"] == "counter":
            counter = self.recorder.counter_next
            self._advance_counter(counter + 1)
        if counted:
            self._index[take.key] = str(path)
            _append_index(self.out_dir, take.key, path, self.spec.umask)
            self.recorded += 1
            self.bytes += size
        self._notify(
            sp.TRACK_FINISHED,
            sp.TrackFinished(
                id=take.take_id,
                path=str(path),
                duration_ms=duration_ms,
                bytes=size,
                tagged=True,
                counter=counter,
                timings=sp.FinishTimings(
                    format=str(self.settings["encode.format"]),
                    trim_ms=40,
                    cover_ms=60,
                    encode_ms=1500,
                    tag_ms=30,
                    total_ms=1650,
                ),
                partial=partial,
                pause_fade=take.paused,
                low_volume=take.low_volume,
            ),
        )
        if not partial and self._held is not None:
            # The take held for track.keep goes once the next track is saved.
            held, self._held = self._held, None
            self._notify(sp.TRACK_KEEPABLE, sp.TrackKeepable(id=held.take_id, keepable=False))
        if self._ended and not self._encoding:
            self._exit_later(self.recorder.exit_delay_s, 0)

    def _advance_counter(self, next_value: int) -> None:
        """output.prefix=counter: Spytify saves output.counter_next after each file, which also
        sends settings.changed."""
        self.recorder.persisted_settings["output.counter_next"] = next_value
        self.settings["output.counter_next"] = next_value
        self._notify(
            sp.SETTINGS_CHANGED, sp.SettingsChanged(values={"output.counter_next": next_value})
        )

    # --- Ending --------------------------------------------------------------------------------

    def _idle_exit(self) -> None:
        self._idle_timer = None
        self._log("info", f"player idle for {self.spec.idle_exit_s}s, ending the session")
        self._end()

    def _end(self, *, exit_code: int = 0) -> None:
        """endOfPlayback: force a pending change (the phantom take), save the last take, exit."""
        if self._ended:
            return
        self._ended = True
        for name in ("_idle_timer", "_level_timer", "_watchdog", "_wait_timer"):
            self._cancel(name)
        if self._pending is not None:
            pending, self._pending = self._pending, None
            if not self._stopping:  # a graceful stop ends at the cut: no take for the change
                last, self._take = self._take, None
                self._start_take(pending, phantom=True)
                self._take = last
        self._close_take(delay_s=self.recorder.final_encode_s)
        self._set_state("idle")
        self._log(
            "info",
            f"session {self.session_id} ended: {self.recorded + len(self._encoding)} recorded, "
            f"{self.skipped} skipped",
        )
        if exit_code != 0:
            self._exit_later(0.5, exit_code)
        elif not self._encoding:
            self._exit_later(0.5, 0)

    def _stop_after_take(self) -> None:
        """A graceful stop: the take finishes at the next change, or at the idle exit while
        paused (the idle timer is armed: a take only starts once the player played)."""
        self._stopping = True
        self._set_state("stopping")
        if self._take is None:
            self._end()

    def _stop_now(self) -> None:
        """The current take ends where it is: skipped incomplete and held for track.keep, even
        one that played to its end (Spytify's handleStop rejects the current segment, whatever
        it is); takes already encoding still finish."""
        self._last_cut = "interrupt"
        if self._take is not None:
            self._take.complete = False
        self._close_take()
        self._pending = None
        self._end()
        if not self._encoding:
            self._exit_later(0.2, 0)

    def _no_target(self) -> None:
        self._wait_timer = None
        name = self.recorder.process_name
        self._log("error", f"session.start: {name} is not running (code {sp.TARGET_NOT_RUNNING})")
        self._ended = True
        if not self.started.done():
            tail = self.log_lines[-5:]
            self.started.set_exception(
                RecorderStartError(
                    f"spytifyd exited with code 1: {name} is not running",
                    exit_code=1,
                    log_tail=tail,
                )
            )
        self._exit_later(0.0, 1)

    def _exit_later(self, delay_s: float, code: int) -> None:
        self._cancel("_exit_timer")
        self._exit_timer = schedule(self.clock, delay_s, lambda: self._exit_now(code))

    def _exit_now(self, code: int) -> None:
        if self._returncode is not None:
            return
        for name in (
            "_idle_timer",
            "_level_timer",
            "_watchdog",
            "_wait_timer",
            "_exit_timer",
        ):
            self._cancel(name)
        for encoding in self._encoding.values():
            encoding.timer.cancel()
            _leave_part(encoding.path)  # bug 5: killed while encoding
        self._encoding.clear()
        if self._held is not None:
            _leave_wav(self.out_dir, self._held.take_id)  # bug 4: --once exits holding it
        self._ended = True
        self._returncode = code
        if self._on_player in self.player.listeners:
            self.player.listeners.remove(self._on_player)
        self._write_files()
        self._queue.put_nowait(None)
        if not self.started.done():
            self.started.set_exception(
                RecorderStartError(f"spytifyd exited with code {code}", exit_code=code)
            )
            self.started.exception()  # retrieved: nobody may be waiting for it any more
        if not self._exit.done():
            self._exit.set_result(code)

    async def _exited_within(self, seconds: float) -> bool:
        sleeper = asyncio.ensure_future(self.clock.sleep(seconds))
        try:
            await asyncio.wait({sleeper, self._exit}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sleeper
        return self._exit.done()

    # --- RPC -----------------------------------------------------------------------------------

    def _answer(self, method: str, params: dict[str, Any]) -> Any:
        if method == sp.CORE_INFO:
            return self._core_info().to_params()
        if method == sp.SESSION_STATUS:
            return self._status().to_params()
        if method == sp.SESSION_START:
            raise RecorderRpcError(method, sp.SESSION_ACTIVE, "a session is already running")
        if method == sp.SESSION_STOP:
            return self._session_stop(bool(params.get("now"))).to_params()
        if method == sp.PLAYER_CONTROL:
            self._player_control(str(params.get("cmd", "")))
            return {}
        if method == sp.PLAYER_LAUNCH:
            if not self.player.on_bus:
                name = self.recorder.process_name
                raise RecorderRpcError(method, sp.TARGET_NOT_RUNNING, f"{name} is not running")
            return {}
        if method == sp.SETTINGS_GET:
            return self._settings_get(params.get("keys") or [])
        if method == sp.SETTINGS_SET:
            return self._settings_set(params.get("values") or {}).to_params()
        if method == sp.SETTINGS_RESET:
            return self._settings_reset(str(params.get("prefix") or ""))
        if method == sp.LOG_TAIL:
            lines = int(params.get("lines") or 0) or 100
            tail = [n.params for n in self.records if n.method == sp.LOG][-lines:]
            return {"lines": [dict(line) for line in tail]}
        if method == sp.EVENTS_RECENT:
            recent = self.records[-200:]  # `level` isn't kept (_notify)
            return {"events": [{"method": n.method, "params": dict(n.params)} for n in recent]}
        if method == sp.TRACK_KEEP:
            self._keep(str(params.get("id") or ""))
            return {}
        if method == sp.CORE_SHUTDOWN:
            schedule(self.clock, 0.0, self._stop_now)
            return {}
        raise RecorderRpcError(method, sp.METHOD_NOT_FOUND, f'unknown method "{method}"')

    def _core_info(self) -> sp.CoreInfo:
        volume = self.recorder.storage.volumes.get(self.out_dir)
        writable = volume.writable if volume is not None else True
        running = self.player.on_bus
        encoder = {"aac": "aac", "mp3": "libmp3lame", "flac": "", "wav": "pcm_s16le"}[
            str(self.settings["encode.format"])
        ]
        process = self.recorder.process_name
        checks = [
            sp.Check(
                id="target",
                name="target configured",
                ok=True,
                detail=f"SPYTIFY_TARGET_PROCESS={process}",
                args=(process,),
            ),
            sp.Check(
                id="player_running",
                name="player running",
                ok=running,
                detail="pid 4000" if running else "not running",
                args=("4000",) if running else (),
            ),
            sp.Check(id="ffmpeg", name="ffmpeg found", ok=True, detail="7.1 (spotivault minimal)"),
        ]
        if encoder:
            fmt = str(self.settings["encode.format"])
            checks.append(
                sp.Check(
                    id="encoder",
                    name=f"encoder {encoder}",
                    ok=True,
                    detail=f"for encode.format={fmt}",
                    args=(encoder, fmt),
                )
            )
        checks += [
            sp.Check(
                id="capture",
                name="capture",
                ok=self.recorder.capture != "stalled",
                detail="pulseaudio",
                args=("pulseaudio",),
            ),
            sp.Check(id="session_bus", name="session bus", ok=True, detail="connected"),
            sp.Check(
                id="player_heard",
                name="player heard",
                ok=self.recorder.capture != "silent",
                detail="no silence heard"
                if self.recorder.capture != "silent"
                else "only silence from the capture while the player played",
            ),
            sp.Check(
                id="output_writable",
                name="output folder writable",
                ok=writable,
                detail=str(self.out_dir) if writable else "permission denied",
                facts={"output.default": "no"},
            ),
        ]
        return sp.CoreInfo(
            version=CORE_VERSION,
            protocol=sp.PROTOCOL,
            target=sp.TargetInfo(process=process, mpris=self.recorder.mpris_name),
            platform="linux/amd64",
            checks=tuple(checks),
            warnings=("turn crossfade and gapless playback off in the player",),
        )

    def _status(self) -> sp.SessionStatus:
        counters = sp.Counters(recorded=self.recorded, skipped=self.skipped, bytes=self.bytes)
        if not self.started.done() or self._ended:
            return sp.SessionStatus(state="idle", counters=counters)
        take = self._take
        track = None
        if take is not None:
            track = sp.Track(
                id=take.take_id,
                artist=take.artist,
                title=take.meta.title or "",
                length_ms=take.meta.length_ms or 0,
                album=take.meta.album or "",
                cover_url=take.meta.art_url or "",
            )
        return sp.SessionStatus(
            state=self.state, counters=counters, session_id=self.session_id, track=track
        )

    def _session_stop(self, now: bool) -> sp.SessionStopResult:
        if self._ended:
            raise RecorderRpcError(sp.SESSION_STOP, sp.NO_SESSION, "no session is running")
        result = sp.SessionStopResult(
            recorded=self.recorded, skipped=self.skipped, stopping=not now
        )
        if now:
            self._stop_now()
        else:
            self._stop_after_take()
        return result

    def _player_control(self, cmd: str) -> None:
        method = sp.PLAYER_CONTROL
        commands = ("play", "pause", "next", "previous", "restart", "full_volume")
        if cmd not in commands:
            raise RecorderRpcError(
                method,
                sp.INVALID_PARAMS,
                "cmd must be play, pause, next, previous, restart or full_volume",
            )
        if cmd == "full_volume":
            if self.player.volume < 100:
                self._log(
                    "info",
                    f"player volume raised from {self.player.volume}% to 100% for the session",
                )
                self.player.set_volume(100)
                if "player_volume_low" in self._reported:
                    self._reported.discard("player_volume_low")
                    self._error(sp.SpytifyError(code="player_volume_low", msg=""))
            return
        if self.player.entry is None or not self.player.on_bus:
            raise RecorderRpcError(method, sp.UNSUPPORTED, f'the player does not accept "{cmd}"')
        if cmd == "play":
            self.player.mpris_play()
        elif cmd == "pause":
            self.player.mpris_pause()
        elif cmd == "next":
            self.player.mpris_next()
        elif cmd == "previous":
            self.player.mpris_previous()
        else:  # restart: from 0:00
            self.player.seek_to(0)

    def _settings_get(self, keys: list[Any]) -> dict[str, Any]:
        wanted = [str(k) for k in keys] or list(SETTINGS)
        unknown = [k for k in wanted if k not in SETTINGS]
        if unknown:
            raise RecorderRpcError(
                sp.SETTINGS_GET, sp.INVALID_PARAMS, f"unknown settings: [{' '.join(unknown)}]"
            )
        return {"values": {key: self.settings[key] for key in wanted}}

    def _settings_set(self, values: Mapping[str, Any]) -> sp.SettingsSetResult:
        applied: list[str] = []
        rejected: dict[str, str] = {}
        changed: dict[str, Any] = {}
        for key in sorted(values):
            value, why = coerce_setting(key, values[key])
            if why is not None:
                rejected[key] = why
                continue
            self.settings[key] = value
            self.recorder.persisted_settings[key] = value
            applied.append(key)
            changed[key] = value
        if changed:
            self._notify(sp.SETTINGS_CHANGED, sp.SettingsChanged(values=changed))
        return sp.SettingsSetResult(applied=tuple(applied), rejected=rejected)

    def _settings_reset(self, prefix: str) -> dict[str, Any]:
        changed: dict[str, Any] = {}
        for key, setting in SETTINGS.items():
            if prefix and not (key == prefix or key.startswith(prefix + ".")):
                continue
            self.recorder.persisted_settings.pop(key, None)
            if self.settings[key] != setting.default:
                self.settings[key] = setting.default
                changed[key] = setting.default
        if changed:
            self._notify(sp.SETTINGS_CHANGED, sp.SettingsChanged(values=changed))
        return {}

    def _keep(self, take_id: str) -> None:
        held = self._held
        if held is None or (take_id and held.take_id != take_id):
            raise RecorderRpcError(
                sp.TRACK_KEEP,
                sp.NOT_AVAILABLE,
                "this take can no longer be saved: only the last one cut short or in low "
                "quality can, until the next track is saved",
            )
        self._held = None
        self._notify(sp.TRACK_KEEPABLE, sp.TrackKeepable(id=held.take_id, keepable=False))
        held.complete = True
        self._encode(held, delay_s=self.recorder.encode_s, partial=True)
        if self._exit_timer is not None:
            self._cancel("_exit_timer")

    # --- Notifications -------------------------------------------------------------------------

    def _notify(self, method: str, payload: Any) -> None:
        """Broadcasts one notification: its params are `payload.to_params()`, as Go marshals
        the struct."""
        if self._returncode is not None:
            return
        notification = RecorderNotification(
            method=method, params=payload.to_params(), received_at=self.clock.now()
        )
        if method == sp.LEVEL:
            # The meter goes to the socket only. Kept, a long item's (10 a second) would fill
            # memory, and writing them at the exit would block the event loop: _write_files runs
            # in place, and took 0.5 s for a 3-hour item. The real port's events_file() leaves
            # them out too.
            self.levels_sent += 1
        else:
            self.records.append(notification)
        if self._ended and self.recorder.lose_final_notifications:
            return
        self._queue.put_nowait(notification)

    def _set_state(self, state: sp.SessionState) -> None:
        if self._stopping and state != "idle":
            state = "stopping"  # Spytify's refreshState: a graceful stop shows over the rest
        if state != self.state:
            self.state = state
            self._notify(sp.SESSION_STATE, sp.SessionStateChanged(state=state))

    def _log(self, level: sp.LogLevel, message: str, *, notify: bool = True) -> None:
        line = sp.LogLine(level=level, msg=message, ts=_rfc3339_nano(self.clock))
        self.log_lines.append(line.text())
        if notify:
            self._notify(sp.LOG, line)

    def _error(self, error: sp.SpytifyError) -> None:
        """Spytify's `error`. A withdrawal is the same code sent again with an empty msg."""
        if error.msg:
            self._log("error", error.msg)
        self._notify(sp.ERROR, error)

    # --- Level meter and capture watchdog ------------------------------------------------------

    def _arm_level(self) -> None:
        self._cancel("_level_timer")
        interval = self.recorder.level_interval_s
        if interval is not None:
            self._level_timer = schedule(self.clock, interval, self._level)

    def _level(self) -> None:
        self._level_timer = None
        if self.state != "recording" or self._take is None:
            return
        if self.recorder.capture == "ok":
            peak = round(-1.0 - self._levels.random() * 4, 1)
            rms = round(peak - 12 - self._levels.random() * 4, 1)
        else:
            peak, rms = -90.0, -90.0
        channel = sp.ChannelLevel(peak_dbfs=peak, rms_dbfs=rms)
        self._notify(sp.LEVEL, sp.Level(peak_dbfs=peak, rms_dbfs=rms, channels=(channel, channel)))
        self._arm_level()

    def _arm_watchdog(self) -> None:
        self._cancel("_watchdog")
        self._watchdog = schedule(self.clock, WATCHDOG_S, self._watchdog_fired)

    def _watchdog_fired(self) -> None:
        self._watchdog = None
        capture = self.recorder.capture
        seconds = str(int(WATCHDOG_S))
        if capture == "silent":
            if self._take is not None:
                self._take.silent = True
            if "capture_silent" not in self._reported:
                self._reported.add("capture_silent")
                self._error(
                    sp.SpytifyError(
                        code="capture_silent",
                        msg=f"only silence from the capture for {seconds}s while the player plays",
                        facts={"silence.seconds": seconds, "silence.peak_dbfs": "-90.0"},
                    )
                )
        elif capture == "stalled":
            if self._take is not None:
                self._take.stalled = True
            if not self._stall_reported:
                self._stall_reported = True
                self._error(
                    sp.SpytifyError(
                        code="capture_stalled",
                        msg=f"no audio from the capture for {seconds}s while the player plays",
                        facts={
                            "stall.player_status": "Playing",
                            "stall.since_chunk_ms": str(int(WATCHDOG_S * 1000)),
                            "stall.any_chunk": "no",
                        },
                    )
                )

    # --- Files ---------------------------------------------------------------------------------

    def _path_for(self, take: _Take, suffix: str) -> Path:
        """Where Spytify's naming settings put a take (contracts/vectors/layouts.json rules)."""
        settings = self.settings
        title = take.meta.title or ""
        album = take.meta.album or ""
        number = take.track_number
        name = str(settings["output.template"])
        values = {
            "{album_artist}": take.album_artist,
            "{artist}": take.album_artist,
            "{artists}": take.artist,
            "{title}": title,
            "{album}": album,
            "{track}": f"{number:02d}" if number else "",
            "{year}": "",
        }
        for placeholder, value in values.items():
            name = name.replace(placeholder, value)
        name = name.replace("()", "").strip(" -_")
        prefix = settings["output.prefix"]
        if prefix == "counter":
            width = int(settings["output.counter_width"])
            name = f"{self.recorder.counter_next:0{width}d} {name}"
        elif prefix == "album_track" and number:
            name = f"{number:02d} {name}"
        group = settings["output.group_by"]
        folders = []
        if group in ("artist", "artist/album", "artists", "artists/album"):
            folders.append(take.album_artist)
        if group in ("artist/album", "artists/album"):
            folders.append(album)
        parts = [self._clean(part) for part in (*folders, name + suffix)]
        extension = _FORMATS[str(settings["encode.format"])]
        return self.out_dir.joinpath(*parts[:-1], parts[-1] + extension)

    def _clean(self, part: str) -> str:
        cleaned = "".join(c for c in part if c not in '/\\:*?"<>|' and ord(c) >= 32).strip()
        if self.settings["output.ascii_filenames"]:
            decomposed = unicodedata.normalize("NFKD", cleaned)
            cleaned = decomposed.encode("ascii", "ignore").decode("ascii")
        if self.settings["output.underscores"]:
            cleaned = cleaned.replace(" ", "_")
        return cleaned or "_"

    def _write_files(self) -> None:
        """The --events and --log-file files, written as the process ends. Each events line is
        Go's proto.Event: `{"method": …, "params": …}`; `level` isn't kept (_notify)."""
        lines = [
            json.dumps({"method": n.method, "params": n.params}, ensure_ascii=False)
            for n in self.records
        ]
        _write_text(self.spec.events_file, lines)
        _write_text(self.spec.log_file, self.log_lines)

    def _cancel(self, name: str) -> None:
        timer = getattr(self, name)
        if timer is not None:
            timer.cancel()
            setattr(self, name, None)


def _rfc3339_nano(clock: Clock) -> str:
    """A log line's `ts`, as Go's time.RFC3339Nano writes a UTC time (no trailing zeros)."""
    now = clock.now()
    fraction = f"{now.microsecond:06d}".rstrip("0")
    return now.strftime("%Y-%m-%dT%H:%M:%S") + (f".{fraction}" if fraction else "") + "Z"


def read_index(out_dir: Path) -> dict[str, str]:
    """`<out_dir>/.spytify/recorded.jsonl` as key → path (matching.read_recorded_index).
    Blocking: call it through asyncio.to_thread."""
    return read_recorded_index(out_dir / ".spytify" / "recorded.jsonl")


# --- Small file writes (see the module docstring) ------------------------------------------------


def _write_take(path: Path, size: int, umask: int) -> None:
    _make_dirs(path.parent, umask)
    with path.open("wb") as fh:
        fh.write(b"spotivault fake take\n")
        fh.truncate(max(size, 32))  # sparse: the reported size, almost no disk
    path.chmod(0o666 & ~umask)


def _append_index(out_dir: Path, key: str, path: Path, umask: int) -> None:
    folder = out_dir / ".spytify"
    _make_dirs(folder, umask)
    with (folder / "recorded.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"Key": key, "Path": str(path)}, ensure_ascii=False) + "\n")


def _leave_wav(out_dir: Path, take_id: str) -> None:
    folder = out_dir / ".spytify"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{take_id}.wav").write_bytes(b"RIFF fake held take")


def _leave_part(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_name(path.name + ".part").write_bytes(b"fake partial encode")


def _write_text(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def _make_dirs(folder: Path, umask: int) -> None:
    missing = []
    current = folder
    while not current.exists():
        missing.append(current)
        current = current.parent
    for created in reversed(missing):
        created.mkdir()
        created.chmod(0o777 & ~umask)
