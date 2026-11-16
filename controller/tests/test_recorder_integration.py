"""The real `spytifyd --fake` with the image's minimal ffmpeg (plan § Verification, Recorder).

Owner: recorder. Skipped unless SPOTIVAULT_TEST_SPYTIFYD and SPOTIVAULT_TEST_FFMPEG name the
binaries (the verify stage extracts them from the built image). Never runs the containers.

Each test runs SpytifyRecorder against spytifyd's own fake player: a timeline of short tracks,
played in real time, that ends as Spotify ends an album (track 1 loaded again, paused), so the
idle exit ends the session (FINDINGS row 27). `spytifyd` here is a small shell script that adds
`--fake <timeline> --fake-realtime` to the recorder's own command line. The --set list is the
controller's own (settings.build_recorder_settings), so the real spytifyd checks it too.
"""

import asyncio
import copy
import dataclasses
import json
import os
import shlex
import shutil
import signal
import struct
import tempfile
import zlib
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from spotivault.api.models import Layout, Settings
from spotivault.clock import SystemClock
from spotivault.config import Config
from spotivault.matching import read_recorded_index, track_key
from spotivault.ports import RecorderNotification, RecorderSpec, RecorderStartError
from spotivault.recorder import protocol as sp
from spotivault.recorder.process import SpytifyRecorder, SpytifySession
from spotivault.settings import DEFAULT_PATTERN, EXTENSIONS, build_recorder_settings

SPYTIFYD = os.environ.get("SPOTIVAULT_TEST_SPYTIFYD")
FFMPEG = os.environ.get("SPOTIVAULT_TEST_FFMPEG")

pytestmark = pytest.mark.skipif(
    not (SPYTIFYD and FFMPEG),
    reason="set SPOTIVAULT_TEST_SPYTIFYD and SPOTIVAULT_TEST_FFMPEG to run spytifyd --fake",
)

SCHEMA_FILE = Path(__file__).parent / "spytify" / "proto-2.0.2.schema.json"
TRACK_MS = 3000
ARTIST = "Fake Artist"
ALBUM = "Fake Album"
RUN_LIMIT_S = 90.0  # one recording, from start to exit


# --- Spytify's schema, strict (as tests/test_spytify_protocol.py reads it) ---------------------


def _strict(node: Any) -> Any:
    """The schema with `additionalProperties: false` on every object that lists properties."""
    if isinstance(node, dict):
        out = {key: _strict(value) for key, value in node.items()}
        if out.get("type") == "object" and "properties" in out:
            out.setdefault("additionalProperties", False)
        return out
    if isinstance(node, list):
        return [_strict(value) for value in node]
    return node


class Schema:
    """Spytify's schema, strict, with one validator per method result and event."""

    def __init__(self, path: Path) -> None:
        schema = json.loads(path.read_text(encoding="utf-8"))
        defs = _strict(copy.deepcopy(schema["$defs"]))
        self.results = {
            name: Draft202012Validator({"$defs": defs, **spec["result"]})
            for name, spec in schema["methods"].items()
        }
        self.events = {
            name: Draft202012Validator({"$defs": defs, **spec["params"]})
            for name, spec in schema["events"].items()
        }

    def check_notifications(self, notes: list[RecorderNotification]) -> None:
        """Blocking: run it on a worker thread."""
        for note in notes:
            self.events[note.method].validate(dict(note.params))


# --- Timelines and covers ----------------------------------------------------------------------


def png(width: int, height: int) -> bytes:
    """A plain RGB PNG: a cover larger than tags.cover_size=medium's 640 px."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + b"\x30\x60\x90" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def timeline(titles: list[str], *, art: Path | None = None) -> dict[str, Any]:
    """An album's tracks, then track 1 loaded again and paused, as Spotify ends an album."""
    cover = str(art) if art is not None else "none"
    items: list[dict[str, Any]] = [
        {
            "artist": ARTIST,
            "title": title,
            "album": ALBUM,
            "track_number": n,
            "length_ms": TRACK_MS,
            "gap_ms": 300,
            "art": cover,
        }
        for n, title in enumerate(titles, start=1)
    ]
    items.append({**items[0], "pause_at_ms": 1, "pause_ms": 600_000, "desync_ms": 1_200_000})
    # A lead-in of silence: the recorder connects to the socket before the first take starts.
    return {"name": "spotivault", "seed": 1, "lead_in_ms": 1500, "tail_ms": 0, "items": items}


# --- Fixtures ----------------------------------------------------------------------------------


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """A folder with a short path, for sockets (107 bytes at most)."""
    base = "/tmp" if os.path.isdir("/tmp") else None
    path = Path(tempfile.mkdtemp(prefix="sv-int-", dir=base))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def schema() -> Schema:
    return Schema(SCHEMA_FILE)


@pytest.fixture
def cover(tmp_path: Path) -> Path:
    """A 700 px PNG, bigger than tags.cover_size=medium's 640 px."""
    path = tmp_path / "cover.png"
    path.write_bytes(png(700, 700))
    return path


class Rig:
    """The real spytifyd behind SpytifyRecorder, on one fake timeline at a time."""

    def __init__(self, config: Config, tmp_path: Path, short_dir: Path) -> None:
        assert SPYTIFYD and FFMPEG
        self.tmp_path = tmp_path
        self.short_dir = short_dir
        self.count = 0
        self.sessions: list[SpytifySession] = []  # killed at the end if still running
        config.home_dir.mkdir(parents=True, exist_ok=True)
        config.spytify_config.parent.mkdir(parents=True, exist_ok=True)
        self.config = dataclasses.replace(
            config, spytifyd_path=tmp_path / "bin" / "spytifyd", ffmpeg_path=Path(FFMPEG)
        )

    def recorder(
        self, timeline: dict[str, Any], *, config: Config | None = None
    ) -> SpytifyRecorder:
        """A recorder whose `spytifyd` plays `timeline` through spytifyd's fake player."""
        path = self.tmp_path / "timeline.json"
        path.write_text(json.dumps(timeline), encoding="utf-8")
        script = self.config.spytifyd_path
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            f"#!/bin/sh\nexec {shlex.quote(SPYTIFYD or '')} --fake {shlex.quote(str(path))} "
            '--fake-realtime "$@"\n',
            encoding="utf-8",
        )
        script.chmod(0o755)
        return SpytifyRecorder(config or self.config, SystemClock())

    async def start(self, recorder: SpytifyRecorder, spec: RecorderSpec) -> SpytifySession:
        session = await recorder.start(spec)
        self.sessions.append(session)
        return session

    def spec(
        self,
        *,
        audio_format: str = "aac",
        bitrate: int | None = 256,
        umask: int = 0o022,
        extra: list[tuple[str, str]] | None = None,
        socket_name: str | None = None,
    ) -> RecorderSpec:
        self.count += 1
        settings = Settings(
            format=audio_format,
            bitrate=bitrate,
            extension=EXTENSIONS[audio_format],
            write_m3u=True,
            save_spotify_covers=True,
            auto_track_owned=True,
            layout=Layout(
                pattern=DEFAULT_PATTERN, prefix="none", underscores=False, strip_accents=False
            ),
        )
        pairs = build_recorder_settings(
            settings, music_dir=self.config.music_dir, mode="missing_only"
        )
        logs = self.config.spytify_logs_dir
        return RecorderSpec(
            run_id=1,
            item_id=f"item{self.count}",
            settings=pairs + (extra or []),
            log_file=logs / f"1-item{self.count}.log",
            events_file=logs / f"1-item{self.count}.events.jsonl",
            socket_path=self.short_dir / (socket_name or f"s{self.count}.sock"),
            work_dir=self.tmp_path / "cwd",
            umask=umask,
            idle_exit_s=2,
            wait_target_s=10,
        )


@pytest.fixture
async def rig(config: Config, tmp_path: Path, short_dir: Path) -> AsyncIterator[Rig]:
    rig = Rig(config, tmp_path, short_dir)
    yield rig
    for session in rig.sessions:
        await session.kill()  # nothing when it has exited


async def record(
    rig: Rig, recorder: SpytifyRecorder, spec: RecorderSpec
) -> tuple[SpytifySession, list[RecorderNotification], int]:
    """Starts one recording and reads it to the end (the idle exit)."""
    session = await rig.start(recorder, spec)
    async with asyncio.timeout(RUN_LIMIT_S):
        notes = [note async for note in session.notifications()]
        code = await session.wait()
    return session, notes, code


def of(notes: list[RecorderNotification], method: str) -> list[dict[str, Any]]:
    return [dict(note.params) for note in notes if note.method == method]


def mode(path: Path | str) -> int:
    """A file's permission bits (a quick stat, fine on the loop in a test)."""
    return Path(path).stat().st_mode & 0o777


def size(path: Path) -> int | None:
    """A regular file's size, or None when there's no such file."""
    return path.stat().st_size if path.is_file() else None


# --- Tests -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("audio_format", "bitrate"),
    [("aac", 256), ("aac", 320), ("mp3", 320), ("flac", None), ("wav", None)],
)
async def test_every_format_and_bitrate(rig: Rig, audio_format: str, bitrate: int | None) -> None:
    recorder = rig.recorder(timeline(["One"]))
    session = await rig.start(recorder, rig.spec(audio_format=audio_format, bitrate=bitrate))
    keys = ["encode.format", "encode.bitrate_kbps", "recorder.skip_duplicates_forward"]
    values = (await session.call(sp.SETTINGS_GET, {"keys": keys}))["values"]
    assert values["encode.format"] == audio_format
    if bitrate is not None:
        assert values["encode.bitrate_kbps"] == bitrate
    assert values["recorder.skip_duplicates_forward"] is False

    async with asyncio.timeout(RUN_LIMIT_S):
        notes = [note async for note in session.notifications()]
        assert await session.wait() == 0
    finished = [sp.TrackFinished.from_params(p) for p in of(notes, sp.TRACK_FINISHED)]
    assert len(finished) == 1 and finished[0].counted
    path = Path(finished[0].path)
    assert path.suffix == f".{EXTENSIONS[audio_format]}"
    assert finished[0].bytes > 0 and (size(path) or 0) > 0
    assert 2000 < finished[0].duration_ms <= TRACK_MS + 200


async def test_naming_keys_tags_and_covers(rig: Rig, cover: Path) -> None:
    titles = ["İstanbul Straße", "Two"]  # Go's lowercasing differs from Python's for İ
    recorder = rig.recorder(timeline(titles, art=cover))
    _, notes, code = await record(rig, recorder, rig.spec())
    assert code == 0

    started = [sp.TrackStarted.from_params(p) for p in of(notes, sp.TRACK_STARTED)]
    assert [(t.artist, t.title, t.album) for t in started[:2]] == [
        (ARTIST, titles[0], ALBUM),
        (ARTIST, titles[1], ALBUM),
    ]
    assert started[0].cover_url.startswith("file://")
    # The idle exit forces the paused track 1 in: a phantom take, skipped as a duplicate.
    assert len(started) == 3 and started[2].title == titles[0]
    skipped = [sp.TrackSkipped.from_params(p) for p in of(notes, sp.TRACK_SKIPPED)]
    assert [(s.id, s.reason) for s in skipped] == [(started[2].id, "duplicate")]

    music = rig.config.music_dir
    expected = {
        track_key(ARTIST, titles[0]): music / ARTIST / ALBUM / f"01 - {titles[0]}.m4a",
        track_key(ARTIST, titles[1]): music / ARTIST / ALBUM / "02 - Two.m4a",
    }
    finished = [sp.TrackFinished.from_params(p) for p in of(notes, sp.TRACK_FINISHED)]
    assert sorted(Path(f.path) for f in finished) == sorted(expected.values())
    assert all(f.tagged and f.counted for f in finished)
    index = await asyncio.to_thread(read_recorded_index, music / ".spytify" / "recorded.jsonl")
    assert index == {key: str(path) for key, path in expected.items()}
    for title, path in zip(titles, expected.values(), strict=True):
        data = await asyncio.to_thread(path.read_bytes)
        assert title.encode() in data  # the title tag
        assert b"\x89PNG" in data  # the cover, shrunk to 640 px and kept as a PNG


async def test_exit_codes(rig: Rig, tmp_path: Path) -> None:
    recorder = rig.recorder(timeline(["One"]))

    # A bad --set: exit 2 before the socket.
    with pytest.raises(RecorderStartError) as caught:
        await recorder.start(rig.spec(extra=[("encode.bitrate_kbps", "999")]))
    assert caught.value.exit_code == 2
    assert sp.classify_exit(2, caught.value.log_tail).action == "fail_run"

    # An output folder it can't make (under a file, so even root can't): session.start -32007.
    blocker = tmp_path / "a-file"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(RecorderStartError) as caught:
        await recorder.start(rig.spec(extra=[("output.dir", str(blocker / "music"))]))
    error = caught.value
    assert error.exit_code == 1
    assert sp.classify_exit(1, error.log_tail).cause == "output_dir"

    # No ffmpeg: session.start -32002.
    no_ffmpeg = dataclasses.replace(rig.config, ffmpeg_path=tmp_path / "no-ffmpeg")
    with pytest.raises(RecorderStartError) as caught:
        await rig.recorder(timeline(["One"]), config=no_ffmpeg).start(rig.spec())
    assert caught.value.exit_code == 1
    assert sp.classify_exit(1, caught.value.log_tail).cause == "ffmpeg"

    # Another spytifyd on the socket: exit 1, retried once by the engine.
    first = await rig.start(recorder, rig.spec(socket_name="same.sock"))
    try:
        with pytest.raises(RecorderStartError) as caught:
            await recorder.start(rig.spec(socket_name="same.sock"))
        assert caught.value.exit_code == 1
        assert sp.classify_exit(1, caught.value.log_tail).cause == "socket_in_use"
    finally:
        code = await first.kill()
    assert code == -signal.SIGKILL
    assert sp.classify_exit(code, first.log_tail).cause == "killed"

    real = dataclasses.replace(rig.config, spytifyd_path=Path(SPYTIFYD or ""))
    assert await SpytifyRecorder(real, SystemClock()).version() == "2.0.2"


async def test_sigterm_finishes_the_current_take(rig: Rig) -> None:
    recorder = rig.recorder(timeline(["One", "Two", "Three"]))
    session = await rig.start(recorder, rig.spec())
    notes: list[RecorderNotification] = []
    stop: asyncio.Future[int] | None = None
    async with asyncio.timeout(RUN_LIMIT_S):
        async for note in session.notifications():
            notes.append(note)
            if note.method == sp.TRACK_STARTED and stop is None:
                await asyncio.sleep(0.5)  # half a second into take 1
                stop = asyncio.ensure_future(session.terminate(first_grace_s=30))
        assert stop is not None and await stop == 0
    first = of(notes, sp.TRACK_STARTED)[0]["id"]
    finished = [p["id"] for p in of(notes, sp.TRACK_FINISHED)]
    assert first in finished
    assert len(of(notes, sp.TRACK_STARTED)) < 3  # it stopped instead of playing on


@pytest.mark.parametrize("now", [False, True])
async def test_a_stop_in_the_album_end_wait(rig: Rig, now: bool) -> None:
    """Spotify ended the album (track 1 loaded again, paused): the last take played in full and
    waits for the idle exit to be cut. session.stop {now: false} saves it there, which is what
    the item engine sends for a Stop now while finishing; {now: true} rejects it (Spytify's
    handleStop rejects the current segment), which is why the engine doesn't send it then."""
    recorder = rig.recorder(timeline(["One", "Two"]))
    session = await rig.start(recorder, rig.spec())
    notes: list[RecorderNotification] = []
    stopped = False
    async with asyncio.timeout(RUN_LIMIT_S):
        async for note in session.notifications():
            notes.append(note)
            waiting = note.method == sp.SESSION_STATE and note.params.get("state") == "paused"
            if waiting and not stopped and len(of(notes, sp.TRACK_STARTED)) == 2:
                stopped = True
                await asyncio.sleep(0.3)  # inside the 2 s idle exit
                await session.call(sp.SESSION_STOP, {"now": now})
        assert await session.wait() == 0
    assert stopped
    last = of(notes, sp.TRACK_STARTED)[1]["id"]
    finished = [p["id"] for p in of(notes, sp.TRACK_FINISHED)]
    skipped = {p["id"]: p["reason"] for p in of(notes, sp.TRACK_SKIPPED)}
    if now:
        assert last not in finished and skipped.get(last) == "incomplete"
    else:
        assert last in finished
        assert len(of(notes, sp.TRACK_STARTED)) == 2  # no phantom take: the stop ends at the cut


async def test_umask_applies_to_files_and_folders(rig: Rig) -> None:
    """WAV: the file ffmpeg encoded, renamed into place, and its JSON sidecar of tags."""
    recorder = rig.recorder(timeline(["One"]))
    _, notes, code = await record(
        rig, recorder, rig.spec(audio_format="wav", bitrate=None, umask=0o027)
    )
    assert code == 0
    path = Path(of(notes, sp.TRACK_FINISHED)[0]["path"])
    assert mode(path) == 0o640
    assert mode(f"{path}.json") == 0o640
    # Spytify makes folders with 0755, so the umask can only take bits away from that.
    assert mode(path.parent) == 0o750  # the album's folder
    assert mode(path.parent.parent) == 0o750  # the artist's


@pytest.mark.xfail(
    strict=False,
    reason="Spytify 2.0.2 tags AAC, MP3 and FLAC into an os.CreateTemp file (mode 0600) and "
    "renames it into place (internal/tag/writer.go), so a tagged file is 0600 whatever the umask",
)
async def test_umask_reaches_tagged_files(rig: Rig) -> None:
    recorder = rig.recorder(timeline(["One"]))
    _, notes, code = await record(rig, recorder, rig.spec(umask=0o027))
    assert code == 0
    assert mode(of(notes, sp.TRACK_FINISHED)[0]["path"]) == 0o640


async def test_the_events_file_holds_the_last_track_finished(rig: Rig) -> None:
    recorder = rig.recorder(timeline(["One", "Two"]))
    session, notes, code = await record(rig, recorder, rig.spec())
    assert code == 0
    records = await session.events_file()
    last_take = of(notes, sp.TRACK_STARTED)[1]["id"]
    assert last_take in [p["id"] for p in of(records, sp.TRACK_FINISHED)]
    # Every notification the socket delivered is in the file, in the same order; the reader
    # leaves out `level` (recorder/events_file.py).
    file_lines = [(r.method, dict(r.params)) for r in records]
    assert sp.LEVEL not in {method for method, _ in file_lines}
    position = 0
    for note in (n for n in notes if n.method != sp.LEVEL):
        position = file_lines.index((note.method, dict(note.params)), position) + 1


async def test_notifications_fit_the_vendored_schema(rig: Rig, schema: Schema) -> None:
    recorder = rig.recorder(timeline(["One", "Two"]))
    session = await rig.start(recorder, rig.spec())
    schema.results[sp.CORE_INFO].validate(await session.call(sp.CORE_INFO))
    schema.results[sp.SESSION_STATUS].validate(await session.call(sp.SESSION_STATUS))
    async with asyncio.timeout(RUN_LIMIT_S):
        notes = [note async for note in session.notifications()]
        assert await session.wait() == 0
    assert {note.method for note in notes} >= {
        sp.SESSION_STATE,
        sp.TRACK_STARTED,
        sp.TRACK_FINISHED,
        sp.TRACK_SKIPPED,
        sp.LOG,
    }
    await asyncio.to_thread(schema.check_notifications, notes)
    assert all(sp.parse_notification(note.method, note.params) is not None for note in notes)
