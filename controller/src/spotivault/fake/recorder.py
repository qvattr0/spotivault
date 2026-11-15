"""The simulated spytifyd (`ports.Recorder`): one `--once --serve --idle-exit` process per item.

A SimRecorderSession watches the SimPlayer as Spytify 2.0.2 watches the real client, and behaves
as prototype/FINDINGS.md and docs/upstream/spytify-bugs.md describe:

- **Takes:** a track that starts playing gets a take: `track.started` (`id` is the take id, the
  artist is MPRIS's first one). A track already in the duplicate index is `track.skipped
  duplicate` at once; with `recorder.skip_duplicates_forward=true` Spytify then presses Next. A
  take that played to its end is encoded, then `track.finished` comes with no title: match it by
  take id. A take cut short is `track.skipped incomplete`.
- **Already playing:** a track the player is on more than 300 ms in when the session starts isn't
  recorded. Played again from the start, it is, unless the restart lands within 2 s of where it
  was paused (bug 2: Spotify sends only `Seeked`, and Spytify takes it for the player restating
  its position). Paused at its start (≤ 300 ms), it waits for Play and is recorded.
- **The end of an album:** Spotify loads track 1 paused. Spytify keeps that change pending, so
  the last take stays open. At the idle exit (`idle_exit_s` after the player stops playing, once
  it has played) the pending change is forced: a phantom `track.started` for track 1 and
  `track.skipped duplicate` (or `incomplete`), with Next pressed when skip-forward is on (bug 1,
  racing the exit), then the last take's `track.finished` about 5 s later, then the exit (code 0)
  about 3 s after that. `album_end_race = True` gives the other outcome of that race: the change
  resolves live, and with skip-forward on the album plays again, every track a duplicate.
- **A pause mid-item** (a takeover, a stall) ends the session at the idle exit too; the take it
  cut is incomplete. A take paused and resumed is saved with `pause_fade` and doesn't count.
- **Stopping:** the first SIGTERM (or `session.stop`) finishes the current take, then ends; the
  second stops at once and holds the take for `track.keep` (`track.keepable`), leaving its WAV in
  `.spytify/` (bug 4); SIGKILL ends it at once, leaving a `.part` file for a take being encoded
  (bug 5). The player quitting ends the session as well.
- **Capture problems:** `set_capture("silent")` reports `capture_silent` after 10 s and withdraws
  it when sound returns; `"stalled"` reports `capture_stalled` after 10 s (D12) and ends the
  session (exit 1). A take recorded below full volume is saved "(low volume)" and doesn't count;
  `player.control full_volume` fixes that.
- **Starting:** a bad `--set` exits 2; an output folder that's missing or not writable, or a
  socket another recorder holds, exits 1 (RecorderStartError). With no player on the bus it waits
  `wait_target_s`, then exits 1.

Files: a finished take is written where Spytify's naming settings put it (`output.group_by`,
`output.template`, `output.prefix`, `output.underscores`, `output.ascii_filenames`), as a sparse
file of the reported size, and its key is appended to `<output.dir>/.spytify/recorded.jsonl`
({"Key", "Path"}), so the controller's file and index checks work. These small writes are done
in place, not in a thread, to keep simulated time exact; real code never does this. The
`--events` and `--log-file` files are written when the process ends.

The notification payloads carry only fields seen in the S0 runs and contracts/events.md; Spytify
may send more. Owner: the fake agent.
"""

import asyncio
import contextlib
import itertools
import json
import os
import random
import unicodedata
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from spotivault.clock import iso_ms
from spotivault.fake.clock import Timer, schedule
from spotivault.fake.player import PlayerEvent, SimPlayer
from spotivault.fake.system import FakeStorageProbe
from spotivault.ports import (
    Clock,
    RecorderGone,
    RecorderNotification,
    RecorderRpcError,
    RecorderSpec,
    RecorderStartError,
    TrackMetadata,
)

SPYTIFY_VERSION = "2.0.2"

FRESH_START_MS = 300  # paused at most this far in: the track waits for Play (freshStartMs)
SEEK_SLACK_MS = 2000  # a Seeked within this of the paused position is ignored (seekSlackMs)
RESTART_TO_MS = 1500  # a Seeked to before this counts as a restart
TRIM_MS = 1100  # Spytify trims about this much silence from a take (87.3 s of 88.4 s)
SKIP_FORWARD_DELAY_S = 0.5  # from a duplicate to Spotify playing the next track after Next
WATCHDOG_S = 10.0  # silent or stalled capture is reported after this (D12, Spytify #811)

type Capture = Literal["ok", "silent", "stalled"]

_BOOL = ("true", "false")
_FORMATS = {"aac": ".m4a", "mp3": ".mp3", "flac": ".flac", "wav": ".wav"}
_PLACEHOLDERS = ("{album_artist}", "{artists}", "{title}", "{album}", "{track}", "{year}")

# Every --set key the controller passes (plan § Starting Spytify for an item), with its check.
SETTINGS: dict[str, Callable[[str], bool]] = {
    "output.dir": lambda v: v.startswith("/"),
    "output.group_by": lambda v: v in ("none", "artist", "artist/album"),
    "output.template": lambda v: _template_ok(v),
    "output.prefix": lambda v: v in ("none", "counter", "album_track"),
    "output.underscores": lambda v: v in _BOOL,
    "output.ascii_filenames": lambda v: v in _BOOL,
    "encode.format": lambda v: v in _FORMATS,
    "encode.bitrate_kbps": lambda v: v.isdigit() and 32 <= int(v) <= 320,
    "recorder.duplicates": lambda v: v in ("skip", "keep"),
    "recorder.skip_duplicates_forward": lambda v: v in _BOOL,
    "recorder.stop_with_player": lambda v: v in _BOOL,
    "recorder.silence_db": lambda v: _is_number(v),
    "tags.cover_size": lambda v: v in ("small", "medium", "large"),
    "privacy.bug_tracker": lambda v: v in _BOOL,
    "app.check_updates": lambda v: v in _BOOL,
}

# Spytify's own defaults for what the controller doesn't set (its default format is mp3 160).
DEFAULTS = {
    "output.group_by": "artist/album",
    "output.template": "{track} - {title}",
    "output.prefix": "none",
    "output.underscores": "false",
    "output.ascii_filenames": "false",
    "encode.format": "mp3",
    "encode.bitrate_kbps": "160",
    "recorder.duplicates": "skip",
    "recorder.skip_duplicates_forward": "true",
}


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
    ) -> None:
        self.clock = clock
        self.player = player
        self.music_dir = music_dir  # where output.dir points when it isn't set
        self.storage = storage
        self.mpris_name = mpris_name
        self.sessions: list[SimRecorderSession] = []  # every session started, oldest first
        self.started: list[RecorderSpec] = []  # every spec start() was given
        self.persisted_settings: dict[str, str] = {}  # settings.set, saved to $SPYTIFY_CONFIG
        self.counter_next = 1  # output.counter_next: the counter prefix goes on across items
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
        settings = dict(DEFAULTS)
        for key, value in spec.settings:
            check = SETTINGS.get(key)
            if check is None:
                raise _start_error(2, f"bad setting {key}={value!r}: unknown setting")
            if not check(value):
                raise _start_error(2, f"bad setting {key}={value!r}: invalid value")
            settings[key] = value
        for other in self.sessions:
            if other.returncode is None and other.spec.socket_path == spec.socket_path:
                raise _start_error(1, f"{spec.socket_path}: socket in use by another spytifyd")
        out_dir = Path(settings.get("output.dir") or self.music_dir)
        if out_dir == self.music_dir:  # the music volume is always there in the container
            await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
        volume = self.storage.volumes.get(out_dir)
        writable = volume.writable if volume is not None else True
        if not writable or not await asyncio.to_thread(out_dir.is_dir):
            raise _start_error(1, f"output folder {out_dir} isn't writable")
        index = await asyncio.to_thread(read_index, out_dir)
        session = SimRecorderSession(self, spec, settings, next(self._pids), out_dir, index)
        self.sessions.append(session)
        session.begin()
        return session

    async def version(self) -> str | None:
        return SPYTIFY_VERSION

    async def kill_orphans(self) -> int:
        found, self.orphans = self.orphans, 0
        return found


def _start_error(code: int, message: str) -> RecorderStartError:
    line = f"error {message}"
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
        settings: dict[str, str],
        pid: int,
        out_dir: Path,
        index: dict[str, str],
    ) -> None:
        self.recorder = recorder
        self.spec = spec
        self.settings = settings
        self.out_dir = out_dir
        self.clock = recorder.clock
        self.player = recorder.player
        self.session_id = self.clock.now().strftime("%Y%m%d-%H%M%S")
        self.state = "idle"  # Spytify's SessionState
        self.records: list[RecorderNotification] = []  # what the --events file holds
        self.log_lines: list[str] = []  # what the --log-file holds
        self.calls: list[str] = []  # RPC methods called
        self.sigterms = 0
        self.recorded = 0
        self.skipped = 0
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
        self._encoding: dict[str, _Encoding] = {}
        self._held: _Take | None = None  # stopped "now": waits for track.keep
        self._idle_timer: Timer | None = None
        self._level_timer: Timer | None = None
        self._watchdog: Timer | None = None
        self._wait_timer: Timer | None = None
        self._exit_timer: Timer | None = None
        self._reported: set[str] = set()  # warnings raised and not withdrawn
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
            self._log("warn", "SIGTERM ignored")
            return
        if self.sigterms == 1:
            self._stop_after_take()
        else:
            self._stop_now()

    # --- Player events -------------------------------------------------------------------------

    def begin(self) -> None:
        """The process is up and its socket answers: the session starts by itself (--once)."""
        self._log("info", f"spytifyd {SPYTIFY_VERSION}: session {self.session_id} started (--once)")
        self.player.listeners.append(self._on_player)
        self._set_state("waiting")
        if not self.player.on_bus:
            wait_s = self.spec.wait_target_s
            self._wait_timer = schedule(self.clock, wait_s, self._no_target)
            return
        self._look_at_player()

    def capture_changed(self) -> None:
        if self._ended:
            return
        capture = self.recorder.capture
        if capture == "ok":
            self._cancel("_watchdog")
            for code in ("capture_silent",):
                if code in self._reported:
                    self._reported.discard(code)
                    self._error(code, "", fatal=False, facts=None, withdrawn=True)
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
                self._cancel("_wait_timer")
                self._look_at_player()
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
        self._notify(
            "track.started",
            {
                "id": take_id,
                "artist": artist,
                "title": meta.title or "",
                "album": meta.album or "",
                "length_ms": meta.length_ms or 0,
            },
        )
        key = track_key(artist, meta.title or "")
        existing = self._index.get(key)
        if existing is not None and self.settings["recorder.duplicates"] == "skip":
            self.skipped += 1
            self._notify("track.skipped", {"id": take_id, "reason": "duplicate", "path": existing})
            if not phantom:
                self._set_state("waiting")
            if self.settings["recorder.skip_duplicates_forward"] == "true":
                track_id = meta.track_id
                schedule(self.clock, SKIP_FORWARD_DELAY_S, lambda: self._skip_forward(track_id))
            return
        if phantom:
            self.skipped += 1
            self._notify("track.skipped", {"id": take_id, "reason": "incomplete", "path": None})
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
            self._error(
                "player_volume_low",
                f"the player's volume is {self.player.volume}%: takes are marked (low volume)",
                fatal=False,
                facts={"volume_percent": self.player.volume},
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

    def _close_take(self, *, reason: str = "incomplete", delay_s: float | None = None) -> None:
        take, self._take = self._take, None
        self._cancel("_level_timer")
        self._cancel("_watchdog")
        if take is None:
            return
        if take.silent:
            reason = "silent"
        elif take.seeked:
            reason = "seeked"  # a jump inside the take: it can't be a clean recording
        if not take.complete or take.silent or take.seeked:
            self.skipped += 1
            self._notify("track.skipped", {"id": take.take_id, "reason": reason, "path": None})
            return
        self._encode(take, delay_s=self.recorder.encode_s if delay_s is None else delay_s)

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
        size = duration_ms * int(self.settings["encode.bitrate_kbps"]) // 8
        counted = not (take.low_volume or take.paused or partial)
        _write_take(path, size, self.spec.umask)
        if counted:
            self._index[take.key] = str(path)
            _append_index(self.out_dir, take.key, path, self.spec.umask)
            self.recorded += 1
        self._notify(
            "track.finished",
            {
                "id": take.take_id,
                "path": str(path),
                "bytes": size,
                "duration_ms": duration_ms,
                "low_volume": take.low_volume,
                "pause_fade": take.paused,
                "partial": partial,
            },
        )
        if self._ended and not self._encoding:
            self._exit_later(self.recorder.exit_delay_s, 0)

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
        self._log("info", "SIGTERM: finishing the current take, then stopping")
        self._stopping = True
        self._set_state("stopping")
        if self._take is None or self.player.status != "Playing":
            self._end()

    def _stop_now(self) -> None:
        """The current take is held for track.keep; takes already encoding still finish."""
        self._log("info", "stopping now")
        take, self._take = self._take, None
        if take is not None:
            self._held = take
            self._notify("track.keepable", {"id": take.take_id})
            _leave_wav(self.out_dir, take.take_id)  # bug 4: --once exits without removing it
        self._pending = None
        self._end()
        if not self._encoding:
            self._exit_later(0.2, 0)

    def _no_target(self) -> None:
        self._wait_timer = None
        self._log("error", f"no player {self.recorder.mpris_name} after {self.spec.wait_target_s}s")
        self._ended = True
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
        self._ended = True
        self._returncode = code
        if self._on_player in self.player.listeners:
            self.player.listeners.remove(self._on_player)
        self._write_files()
        self._queue.put_nowait(None)
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
        if method == "core.info":
            return self._core_info()
        if method == "player.control":
            return self._player_control(str(params.get("cmd", "")))
        if method == "settings.get":
            keys = params.get("keys") or sorted(self.settings)
            return {"values": {key: self.settings.get(key) for key in keys}}
        if method == "settings.set":
            return self._settings_set(params.get("values") or {})
        if method == "session.stop":
            if params.get("now"):
                self._stop_now()
            else:
                self._stop_after_take()
            return {}
        if method == "session.start":
            raise RecorderRpcError(method, -32000, "a session is already running")
        if method == "track.keep":
            return self._keep(str(params.get("id", "")))
        raise RecorderRpcError(method, -32601, "method not found")

    def _core_info(self) -> dict[str, Any]:
        volume = self.recorder.storage.volumes.get(self.out_dir)
        checks = {
            "target": True,
            "player_running": self.player.on_bus,
            "ffmpeg": True,
            "encoder": True,
            "capture": self.recorder.capture != "stalled",
            "session_bus": True,
            "player_heard": self.player.on_bus,
            "output_writable": volume.writable if volume is not None else True,
        }
        return {
            "version": SPYTIFY_VERSION,
            "target": self.recorder.mpris_name,
            "checks": [{"id": name, "ok": ok} for name, ok in checks.items()],
            "warnings": ["turn crossfade and gapless playback off in the player"],
        }

    def _player_control(self, cmd: str) -> dict[str, Any]:
        method = "player.control"
        if cmd == "full_volume":
            if self.player.volume < 100:
                self._log(
                    "info",
                    f"player volume raised from {self.player.volume}% to 100% for the session",
                )
                self.player.set_volume(100)
                if "player_volume_low" in self._reported:
                    self._reported.discard("player_volume_low")
                    self._error("player_volume_low", "", fatal=False, facts=None, withdrawn=True)
            return {}
        actions = {
            "play": self.player.mpris_play,
            "pause": self.player.mpris_pause,
            "next": self.player.mpris_next,
            "previous": self.player.mpris_previous,
        }
        action = actions.get(cmd)
        if action is None:
            raise RecorderRpcError(method, -32602, f"unknown command {cmd!r}")
        if self.player.entry is None or not self.player.on_bus:
            raise RecorderRpcError(method, -32005, f'the player does not accept "{cmd}"')
        action()
        return {}

    def _settings_set(self, values: Mapping[str, Any]) -> dict[str, Any]:
        applied = []
        for key, raw in values.items():
            value = _setting_text(raw)
            check = SETTINGS.get(key)
            if check is None or not check(value):
                raise RecorderRpcError("settings.set", -32602, f"bad setting {key}={value!r}")
            self.settings[key] = value
            self.recorder.persisted_settings[key] = value
            applied.append(key)
        if applied:
            self._notify("settings.changed", {"keys": applied})
        return {"applied": applied}

    def _keep(self, take_id: str) -> dict[str, Any]:
        held = self._held
        if held is None or held.take_id != take_id:
            raise RecorderRpcError("track.keep", -32602, f"no held take {take_id!r}")
        self._held = None
        held.complete = True
        self._encode(held, delay_s=self.recorder.encode_s, partial=True)
        if self._exit_timer is not None:
            self._cancel("_exit_timer")
        return {}

    # --- Notifications -------------------------------------------------------------------------

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        if self._returncode is not None:
            return
        notification = RecorderNotification(
            method=method, params=params, received_at=self.clock.now()
        )
        self.records.append(notification)
        if self._ended and self.recorder.lose_final_notifications:
            return
        self._queue.put_nowait(notification)

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self._notify("session.state", {"state": state})

    def _log(self, level: str, message: str, *, notify: bool = True) -> None:
        self.log_lines.append(f"{iso_ms(self.clock.now())} {level:5} {message}")
        if notify:
            self._notify("log", {"level": level, "message": message})

    def _error(
        self,
        code: str,
        message: str,
        *,
        fatal: bool,
        facts: dict[str, Any] | None,
        withdrawn: bool = False,
    ) -> None:
        """Spytify's `error`. A withdrawal is the same code sent again with no message."""
        params: dict[str, Any] = {"code": code, "message": message, "fatal": fatal, "facts": facts}
        if not withdrawn:
            self._log("error" if fatal else "warn", f"{code}: {message}")
        self._notify("error", params)

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
        channel = {"peak_dbfs": peak, "rms_dbfs": rms}
        self._notify(
            "level", {"peak_dbfs": peak, "rms_dbfs": rms, "channels": [channel, dict(channel)]}
        )
        self._arm_level()

    def _arm_watchdog(self) -> None:
        self._cancel("_watchdog")
        self._watchdog = schedule(self.clock, WATCHDOG_S, self._watchdog_fired)

    def _watchdog_fired(self) -> None:
        self._watchdog = None
        capture = self.recorder.capture
        if capture == "silent":
            if self._take is not None:
                self._take.silent = True
            if "capture_silent" not in self._reported:
                self._reported.add("capture_silent")
                self._error(
                    "capture_silent",
                    "no sound from the player for 10 s",
                    fatal=False,
                    facts={"seconds": int(WATCHDOG_S), "peak_dbfs": -90.0},
                )
        elif capture == "stalled":
            self._error(
                "capture_stalled",
                "the capture delivered no audio for 10 s",
                fatal=True,
                facts={"seconds": int(WATCHDOG_S)},
            )
            if self._take is not None:
                self._take.complete = False
            self._end(exit_code=1)

    # --- Files ---------------------------------------------------------------------------------

    def _path_for(self, take: _Take, suffix: str) -> Path:
        """Where Spytify's naming settings put a take (contracts/vectors/layouts.json rules)."""
        settings = self.settings
        title = take.meta.title or ""
        album = take.meta.album or ""
        number = take.track_number
        name = settings["output.template"]
        values = {
            "{album_artist}": take.album_artist,
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
            name = f"{self.recorder.counter_next:03d} {name}"
            self.recorder.counter_next += 1
        elif prefix == "album_track" and number:
            name = f"{number:02d} {name}"
        group = settings["output.group_by"]
        folders = []
        if group in ("artist", "artist/album"):
            folders.append(take.album_artist)
        if group == "artist/album":
            folders.append(album)
        parts = [self._clean(part) for part in (*folders, name + suffix)]
        extension = _FORMATS[settings["encode.format"]]
        return self.out_dir.joinpath(*parts[:-1], parts[-1] + extension)

    def _clean(self, part: str) -> str:
        cleaned = "".join(c for c in part if c not in '/\\:*?"<>|' and ord(c) >= 32).strip()
        if self.settings["output.ascii_filenames"] == "true":
            decomposed = unicodedata.normalize("NFKD", cleaned)
            cleaned = decomposed.encode("ascii", "ignore").decode("ascii")
        if self.settings["output.underscores"] == "true":
            cleaned = cleaned.replace(" ", "_")
        return cleaned or "_"

    def _write_files(self) -> None:
        """The --events and --log-file files, written as the process ends."""
        lines = [
            json.dumps({"jsonrpc": "2.0", "method": n.method, "params": n.params})
            for n in self.records
        ]
        _write_text(self.spec.events_file, lines)
        _write_text(self.spec.log_file, self.log_lines)

    def _cancel(self, name: str) -> None:
        timer = getattr(self, name)
        if timer is not None:
            timer.cancel()
            setattr(self, name, None)


# --- Spytify's duplicate index ------------------------------------------------------------------


def go_lower(text: str) -> str:
    """Go's strings.ToLower (prototype/probe.py): Python's lower() differs for İ and final Σ."""
    return "".join("i" if c == "İ" else c.lower() for c in text)


def go_trim(text: str) -> str:
    """Go's strings.TrimSpace: unlike Python's strip(), it keeps U+001C–U+001F."""
    return text.strip(" \t\n\v\f\r\x85\xa0                　")


def track_key(artist: str, title: str) -> str:
    """Spytify's index key: first artist + U+001F + title, trimmed and lowercased the Go way."""
    return go_lower(go_trim(artist)) + "\x1f" + go_lower(go_trim(title))


def read_index(out_dir: Path) -> dict[str, str]:
    """`<out_dir>/.spytify/recorded.jsonl` as key → path, later lines winning, keeping only
    entries whose file still exists. Blocking: call it through asyncio.to_thread."""
    index: dict[str, str] = {}
    path = out_dir / ".spytify" / "recorded.jsonl"
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                    index[entry["Key"]] = entry["Path"]
                except (ValueError, KeyError, TypeError):
                    continue
    except FileNotFoundError:
        return {}
    return {key: value for key, value in index.items() if os.path.exists(value)}


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


# --- Settings ---------------------------------------------------------------------------------


def _template_ok(template: str) -> bool:
    """Spytify refuses a template with a backslash, or without a placeholder ({year} alone
    doesn't count: it's always empty on Linux)."""
    if "\\" in template:
        return False
    return any(p in template for p in _PLACEHOLDERS if p != "{year}")


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _setting_text(value: Any) -> str:
    """A settings.set value as --set would spell it: JSON booleans become true/false."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
