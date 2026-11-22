"""recorder/process.py, rpc.py and events_file.py with a stub spytifyd (tests/recorder_stub/
spytifyd.py: a small script that speaks recorder/protocol.py on a socket, as `--once --serve`).

Owner: recorder. The stub runs as a real subprocess; most tests use the system clock with short
timings (the stub's knobs), and the ones about waits use the FakeClock. The JSON-RPC tests talk
to a socket server inside the test instead, to script every line. Sockets live in a short folder
under /tmp: a Unix socket path holds at most 107 bytes.
"""

import asyncio
import dataclasses
import json
import os
import shlex
import shutil
import signal
import socket
import sys
import tempfile
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from portcheck import assert_implements
from spotivault import ports
from spotivault.clock import SystemClock
from spotivault.config import Config
from spotivault.fake.clock import FakeClock
from spotivault.ports import (
    Clock,
    RecorderGone,
    RecorderNotification,
    RecorderRpcError,
    RecorderSpec,
    RecorderStartError,
)
from spotivault.recorder import events_file as events_file_module
from spotivault.recorder import protocol as sp
from spotivault.recorder.events_file import load_events_file, read_events_file
from spotivault.recorder.process import (
    MAX_SOCKET_PATH_BYTES,
    STDERR_TAIL_LINES,
    SpytifyRecorder,
    SpytifySession,
    command_line,
    find_orphans,
    read_proc,
    socket_path_ok,
    still_running,
)
from spotivault.recorder.rpc import JsonRpcConnection, wait_on_clock

STUB = Path(__file__).parent / "recorder_stub" / "spytifyd.py"


# --- Fixtures ----------------------------------------------------------------------------------


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """A folder with a short path, for sockets."""
    base = "/tmp" if os.path.isdir("/tmp") else None
    path = Path(tempfile.mkdtemp(prefix="sv-rec-", dir=base))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def launcher(folder: Path, name: str = "spytifyd") -> Path:
    """An executable named like spytifyd that runs the stub with this venv's Python. A shell
    script, because the venv's path may hold a space, which a #! line can't."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(STUB))} "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


@pytest.fixture
def stub_config(config: Config, tmp_path: Path) -> Config:
    return dataclasses.replace(config, spytifyd_path=launcher(tmp_path / "bin"))


class Specs:
    """RecorderSpecs for the stub: `make(knob=value, ...)` turns knobs into `--set stub.*`."""

    def __init__(self, config: Config, tmp_path: Path, short_dir: Path) -> None:
        self.config = config
        self.tmp_path = tmp_path
        self.short_dir = short_dir
        self.count = 0

    def make(
        self,
        *,
        socket_name: str | None = None,
        umask: int = 0o022,
        idle_exit_s: int = 20,
        wait_target_s: int = 60,
        socket_timeout_s: float = 10.0,
        work_dir: Path | None = None,
        **knobs: object,
    ) -> RecorderSpec:
        self.count += 1
        settings = [("output.dir", str(self.config.music_dir)), ("encode.format", "aac")]
        settings += [(f"stub.{key}", str(value)) for key, value in knobs.items()]
        logs = self.config.spytify_logs_dir
        return RecorderSpec(
            run_id=1,
            item_id=f"item{self.count}",
            settings=settings,
            log_file=logs / f"1-item{self.count}.log",
            events_file=logs / f"1-item{self.count}.events.jsonl",
            socket_path=self.short_dir / (socket_name or f"s{self.count}.sock"),
            work_dir=work_dir or self.tmp_path / "cwd",
            umask=umask,
            idle_exit_s=idle_exit_s,
            wait_target_s=wait_target_s,
            socket_timeout_s=socket_timeout_s,
        )

    def report(self) -> Path:
        return self.tmp_path / f"report-{self.count + 1}.json"


@pytest.fixture
def specs(stub_config: Config, tmp_path: Path, short_dir: Path) -> Specs:
    return Specs(stub_config, tmp_path, short_dir)


@pytest.fixture
def recorder(stub_config: Config) -> SpytifyRecorder:
    return SpytifyRecorder(stub_config, SystemClock())


@pytest.fixture
async def sessions() -> AsyncIterator[list[SpytifySession]]:
    """Sessions a test started; any still running at the end is killed."""
    started: list[SpytifySession] = []
    yield started
    for session in started:
        if session.returncode is None:
            await session.kill()


async def collect(session: SpytifySession) -> list[RecorderNotification]:
    return [note async for note in session.notifications()]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def gone(pid: int) -> bool:
    """The process has exited (a zombie waiting for its parent counts as exited)."""
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return True
    return "\nState:\tZ" in status


async def until(condition: Callable[[], bool], *, within: float = 5.0) -> None:
    """Waits in real time until `condition()` is true."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + within
    while not condition():
        if loop.time() > deadline:
            raise AssertionError("still not true after the wait")
        await asyncio.sleep(0.02)


# --- The ports and the command line ------------------------------------------------------------


def test_both_classes_implement_their_ports() -> None:
    assert_implements(SpytifyRecorder, ports.Recorder)
    assert_implements(SpytifySession, ports.RecorderSession)


def test_command_line_and_environment(config: Config, tmp_path: Path) -> None:
    spec = RecorderSpec(
        run_id=3,
        item_id="abc",
        settings=[("output.dir", "/music"), ("output.template", "{track} - {title}")],
        log_file=Path("/config/logs/spytify/3-abc.log"),
        events_file=Path("/config/logs/spytify/3-abc.events.jsonl"),
        socket_path=Path("/tmp/runtime-app/spytify-3-1.sock"),
        work_dir=tmp_path,
        umask=0o002,
    )
    argv, env = command_line(spec, config)
    assert argv == [
        "/usr/local/bin/spytifyd",
        "--once",
        "--serve",
        "--idle-exit",
        "20s",
        "--wait-target",
        "60s",
        "--log-file",
        "/config/logs/spytify/3-abc.log",
        "--events",
        "/config/logs/spytify/3-abc.events.jsonl",
        "--set",
        "output.dir=/music",
        "--set",
        "output.template={track} - {title}",
    ]
    assert env == {
        "HOME": str(config.config_dir / "home"),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "XDG_RUNTIME_DIR": str(config.runtime_dir),
        "DISPLAY": ":99",
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={config.runtime_dir / 'bus'}",
        "PULSE_SERVER": f"unix:{config.runtime_dir}/pulse/native",
        "SPYTIFY_TARGET_PROCESS": "spotify",
        "SPYTIFY_TARGET_MPRIS": "org.mpris.MediaPlayer2.spotify",
        "SPYTIFY_SOCKET": "/tmp/runtime-app/spytify-3-1.sock",
        "SPYTIFY_CONFIG": str(config.config_dir / "spytify" / "config.toml"),
        "SPYTIFY_FFMPEG": "/usr/local/bin/ffmpeg",
    }


def test_socket_paths_fit_in_sun_path() -> None:
    assert MAX_SOCKET_PATH_BYTES == 107
    assert socket_path_ok(Path("/" + "a" * 106))
    assert not socket_path_ok(Path("/" + "a" * 107))
    assert not socket_path_ok(Path("/" + "é" * 54))  # 108 bytes in UTF-8


async def test_a_socket_path_too_long_starts_nothing(
    recorder: SpytifyRecorder, specs: Specs, tmp_path: Path
) -> None:
    report = specs.report()
    spec = dataclasses.replace(
        specs.make(report=report), socket_path=tmp_path / ("x" * MAX_SOCKET_PATH_BYTES)
    )
    with pytest.raises(RecorderStartError, match="longer than 107 bytes") as caught:
        await recorder.start(spec)
    assert caught.value.exit_code is None
    assert not report.exists()


# --- Starting ----------------------------------------------------------------------------------


async def test_start_waits_for_the_socket_and_the_session(
    recorder: SpytifyRecorder, specs: Specs, sessions: list[SpytifySession]
) -> None:
    spec = specs.make(listen_after=0.4, session_after=0.6, idle_s=1.0)
    session = await recorder.start(spec)
    sessions.append(session)

    status = sp.SessionStatus.from_params(await session.call(sp.SESSION_STATUS))
    assert status.session_id == "20261116-000000"
    assert session.core_info is not None and session.core_info.version == "v2.0.2"
    assert session.core_info.target.process == "spotify"
    assert session.returncode is None and session.pid > 0

    notes = await collect(session)  # the idle exit ends it
    assert session.returncode == 0
    states = [n.params["state"] for n in notes if n.method == sp.SESSION_STATE]
    assert states == ["waiting", "idle"]
    assert spec.log_file.exists()  # the folders were made for spytifyd


@pytest.mark.parametrize(
    ("knobs", "code", "cause"),
    [
        ({"exit_early": "2:--set encode.format: must be one of aac, mp3"}, 2, "bad_setting"),
        (
            {
                "fail_session": "1:session.start: the output folder cannot be written to: open "
                "/music: permission denied (code -32007)"
            },
            1,
            "output_dir",
        ),
        ({"fail_session": "1:session.start: ffmpeg not found (code -32002)"}, 1, "ffmpeg"),
        ({"session_after": "never"}, 1, "no_player"),
        ({"exit_early": "1:--events: open /config/x: permission denied"}, 1, "files"),
        ({"fail_session": "1:session.start: something else"}, 1, "other"),
    ],
)
async def test_an_exit_before_ready_is_a_start_error_with_the_log_tail(
    recorder: SpytifyRecorder, specs: Specs, knobs: dict[str, str], code: int, cause: str
) -> None:
    report = specs.report()
    spec = specs.make(report=report, wait_target_s=1, **knobs)
    with pytest.raises(RecorderStartError) as caught:
        await recorder.start(spec)
    error = caught.value
    assert error.exit_code == code
    assert error.log_tail and " error " in error.log_tail[-1]
    assert f"exited with code {code}" in str(error)
    assert sp.classify_exit(error.exit_code, error.log_tail).cause == cause
    assert gone(read_json(report)["pid"])


async def test_another_spytifyd_on_the_socket_is_socket_in_use(
    recorder: SpytifyRecorder, specs: Specs, sessions: list[SpytifySession]
) -> None:
    first = await recorder.start(specs.make(socket_name="same.sock", idle_s=30))
    sessions.append(first)

    # The second one's connection reaches the first: start() must not take it as its own.
    with pytest.raises(RecorderStartError) as caught:
        await recorder.start(specs.make(socket_name="same.sock"))
    error = caught.value
    assert error.exit_code == 1
    assert "another spytifyd is listening" in error.log_tail[-1]
    assert sp.classify_exit(error.exit_code, error.log_tail).action == "retry_once"

    status = sp.SessionStatus.from_params(await first.call(sp.SESSION_STATUS))
    assert status.session_id and first.returncode is None


async def test_the_socket_must_appear_in_time(recorder: SpytifyRecorder, specs: Specs) -> None:
    report = specs.report()
    spec = specs.make(report=report, listen_after=30, socket_timeout_s=0.5)
    with pytest.raises(RecorderStartError, match="socket didn't appear") as caught:
        await recorder.start(spec)
    assert caught.value.exit_code is None
    assert sp.classify_exit(None, caught.value.log_tail).action == "fail_item"
    assert gone(read_json(report)["pid"])  # killed, not left running


async def test_a_cancelled_start_leaves_nothing_running(
    recorder: SpytifyRecorder, specs: Specs
) -> None:
    report = specs.report()
    start = asyncio.ensure_future(recorder.start(specs.make(report=report, session_after=30)))
    await until(report.exists)
    await asyncio.sleep(0.3)
    start.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start
    assert gone(read_json(report)["pid"])


async def test_an_exit_0_before_the_session_shows_returns_the_ended_session(
    recorder: SpytifyRecorder, specs: Specs
) -> None:
    spec = specs.make(end_at_once=1)
    session = await recorder.start(spec)
    assert await session.wait() == 0
    await collect(session)  # ends at once
    records = await session.events_file()
    states = [r.params["state"] for r in records if r.method == sp.SESSION_STATE]
    assert states == ["waiting", "idle"]


async def test_umask_process_group_and_empty_cwd(
    recorder: SpytifyRecorder, specs: Specs, stub_config: Config, tmp_path: Path
) -> None:
    report = specs.report()
    work_dir = tmp_path / "new" / "cwd"  # made by start()
    spec = specs.make(report=report, umask=0o027, work_dir=work_dir, end_at_once=1)
    session = await recorder.start(spec)
    await session.wait()

    seen = read_json(report)
    assert seen["pid"] == session.pid
    assert seen["pgid"] == session.pid  # its own process group
    assert seen["cwd"] == str(work_dir) and seen["cwd_entries"] == []
    assert seen["umask"] == 0o027
    _, env = command_line(spec, stub_config)
    shell_added = {"PWD", "OLDPWD", "SHLVL", "_"}  # the launcher is a shell script
    assert {k: v for k, v in seen["env"].items() if k not in shell_added} == env
    folder = stub_config.music_dir / "umask-check"
    assert folder.stat().st_mode & 0o777 == 0o750
    assert (folder / "file.m4a").stat().st_mode & 0o777 == 0o640


async def test_a_dotenv_in_the_work_dir_starts_nothing(
    recorder: SpytifyRecorder, specs: Specs, tmp_path: Path
) -> None:
    work_dir = tmp_path / "cwd"
    work_dir.mkdir()
    (work_dir / ".env").write_text("SPYTIFY_TAP=x\n", encoding="utf-8")
    report = specs.report()
    with pytest.raises(RecorderStartError, match=r"\.env") as caught:
        await recorder.start(specs.make(report=report, work_dir=work_dir))
    assert caught.value.exit_code is None
    assert not report.exists()


async def test_a_missing_binary_is_a_start_error(specs: Specs, stub_config: Config) -> None:
    config = dataclasses.replace(stub_config, spytifyd_path=Path("/nonexistent/spytifyd"))
    with pytest.raises(RecorderStartError, match="can't run") as caught:
        await SpytifyRecorder(config, SystemClock()).start(specs.make())
    assert caught.value.exit_code is None


async def test_version_reads_spytifyd_version(recorder: SpytifyRecorder) -> None:
    assert await recorder.version() == "2.0.2"


# --- A session ---------------------------------------------------------------------------------


async def test_notifications_end_after_eof_and_exit(
    recorder: SpytifyRecorder, specs: Specs
) -> None:
    session = await recorder.start(specs.make(session_after=0.6, takes=2, take_s=0.2, idle_s=0.3))
    notes = await collect(session)
    assert session.returncode == 0

    tracks = [(n.method, n.params["id"]) for n in notes if n.method.startswith("track.")]
    assert tracks == [
        (sp.TRACK_STARTED, "20261116-000000-001"),
        (sp.TRACK_FINISHED, "20261116-000000-001"),
        (sp.TRACK_STARTED, "20261116-000000-002"),
        (sp.TRACK_FINISHED, "20261116-000000-002"),  # sent as it ends, before the socket closed
    ]
    assert all(n.received_at.tzinfo is not None for n in notes)

    # The events file holds everything but `level`, the socket's notifications in the same order.
    records = await session.events_file()
    file_lines = [(r.method, r.params) for r in records]
    socket_lines = [(n.method, n.params) for n in notes if n.method != sp.LEVEL]
    position = 0
    for line in socket_lines:  # .index raises ValueError for one missing or out of order
        position = file_lines.index(line, position) + 1


async def test_rpc_errors_hangs_and_calls_after_the_exit(
    recorder: SpytifyRecorder, specs: Specs
) -> None:
    session = await recorder.start(specs.make(hang=sp.PLAYER_CONTROL, idle_s=30))

    with pytest.raises(RecorderRpcError) as caught:
        await session.call("test.unknown", {"a": 1})
    assert caught.value.code == sp.METHOD_NOT_FOUND
    assert caught.value.method == "test.unknown"
    assert caught.value.data == {"method": "test.unknown"}

    with pytest.raises(TimeoutError):
        await session.call(sp.PLAYER_CONTROL, {"cmd": "full_volume"}, timeout_s=0.3)
    assert await session.call(sp.SESSION_STATUS)  # the session goes on

    stopped = sp.SessionStopResult.from_params(await session.call(sp.SESSION_STOP, {"now": True}))
    assert not stopped.stopping
    assert await session.wait() == 0
    with pytest.raises(RecorderGone):
        await session.call(sp.SESSION_STATUS)


async def test_the_stderr_tail_keeps_the_last_lines(
    recorder: SpytifyRecorder, specs: Specs
) -> None:
    session = await recorder.start(specs.make(flood=STDERR_TAIL_LINES + 30, end_at_once=1))
    await session.wait()
    tail = session.log_tail
    assert len(tail) == STDERR_TAIL_LINES
    assert tail[-1].endswith("session ended")
    assert any(line.endswith(f"flood {STDERR_TAIL_LINES + 29}") for line in tail)
    assert not any(line.endswith(" flood 0") for line in tail)


# --- Stopping ----------------------------------------------------------------------------------


async def test_terminate_lets_the_current_take_finish(
    recorder: SpytifyRecorder, specs: Specs
) -> None:
    session = await recorder.start(specs.make(session_after=0.6, takes=3, take_s=30, idle_s=30))
    notes: list[RecorderNotification] = []

    async def read() -> None:
        async for note in session.notifications():
            notes.append(note)

    async with asyncio.TaskGroup() as group:
        group.create_task(read())
        await until(lambda: any(n.method == sp.TRACK_STARTED for n in notes))
        assert await session.terminate() == 0
    finished = [n.params["id"] for n in notes if n.method == sp.TRACK_FINISHED]
    assert finished == ["20261116-000000-001"]


async def test_terminate_escalates_sigterm_sigterm_sigkill(
    stub_config: Config, specs: Specs
) -> None:
    """The waits run on the clock: with the FakeClock nothing escalates until it's moved."""
    clock = FakeClock()
    recorder = SpytifyRecorder(stub_config, clock)
    start = asyncio.ensure_future(
        recorder.start(specs.make(sigterm="ignore", idle_s=300, socket_timeout_s=120))
    )
    while not start.done():  # start() polls the socket on the clock
        await asyncio.sleep(0.02)
        await clock.advance(0.25)
    session = start.result()

    def sigterms() -> int:
        return sum("terminated received, ignored" in line for line in session.log_tail)

    stop = asyncio.ensure_future(session.terminate())
    await until(lambda: sigterms() == 1)
    await clock.advance(44.9)
    await asyncio.sleep(0.3)
    assert sigterms() == 1 and not stop.done()
    await clock.advance(0.1)  # 45 s: the second SIGTERM
    await until(lambda: sigterms() == 2)
    await clock.advance(14.9)
    await asyncio.sleep(0.3)
    assert not stop.done() and session.returncode is None
    await clock.advance(0.1)  # 15 s more: SIGKILL
    assert await stop == -signal.SIGKILL
    assert session.returncode == -signal.SIGKILL


async def test_sigterm_goes_to_spytifyd_alone_and_sigkill_to_its_group(
    recorder: SpytifyRecorder, specs: Specs
) -> None:
    # SIGTERM: spytifyd finishes its take while its children (parec, ffmpeg) carry on.
    report = specs.report()
    session = await recorder.start(specs.make(report=report, child=1, idle_s=30))
    child = read_json(report)["child_pid"]
    try:
        assert await session.terminate() == 0
        await asyncio.sleep(0.2)
        assert not gone(child)
    finally:
        os.kill(child, signal.SIGKILL)

    # SIGKILL: the whole group, children included.
    report = specs.report()
    session = await recorder.start(specs.make(report=report, child=1, idle_s=30))
    child = read_json(report)["child_pid"]
    assert await session.kill() == -signal.SIGKILL
    await until(lambda: gone(child))


async def test_a_child_holding_stderr_is_ended_with_the_group(
    recorder: SpytifyRecorder, specs: Specs
) -> None:
    """asyncio's wait() waits for stderr to close too. A child of spytifyd still holding it
    after spytifyd exited gets the group's SIGKILL, so terminate() can't hang."""
    report = specs.report()
    session = await recorder.start(specs.make(report=report, child="stderr", idle_s=30))
    child = read_json(report)["child_pid"]
    try:
        assert await session.terminate(first_grace_s=0.3, second_grace_s=0.3) == 0
        await until(lambda: gone(child))
    finally:
        if not gone(child):
            os.kill(child, signal.SIGKILL)


async def test_terminate_with_short_graces_on_the_system_clock(
    recorder: SpytifyRecorder, specs: Specs
) -> None:
    session = await recorder.start(specs.make(sigterm="ignore", idle_s=300))
    code = await session.terminate(first_grace_s=0.3, second_grace_s=0.3)
    assert code == -signal.SIGKILL
    assert sum("terminated received, ignored" in line for line in session.log_tail) == 2
    assert await session.terminate() == code  # already over: just the code


# --- Orphans -----------------------------------------------------------------------------------


def fake_proc(root: Path, pid: int, *, uid: int, ppid: int, argv0: str, state: str = "S") -> None:
    folder = root / str(pid)
    folder.mkdir(parents=True)
    (folder / "status").write_text(
        f"Name:\tx\nState:\t{state} (sleeping)\nPPid:\t{ppid}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n",
        encoding="utf-8",
    )
    (folder / "cmdline").write_bytes(argv0.encode() + b"\0--once\0")


def test_find_orphans_reads_proc(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    fake_proc(proc, 101, uid=1000, ppid=1, argv0="/usr/local/bin/spytifyd")  # left running
    fake_proc(proc, 102, uid=1000, ppid=500, argv0="/usr/local/bin/spytifyd")  # our child
    fake_proc(proc, 103, uid=0, ppid=1, argv0="/usr/local/bin/spytifyd")  # another user's
    fake_proc(proc, 104, uid=1000, ppid=1, argv0="/usr/bin/notspytifyd")
    fake_proc(proc, 105, uid=1000, ppid=1, argv0="spytifyd", state="Z")  # already dead
    fake_proc(proc, 106, uid=1000, ppid=1, argv0="")  # a kernel thread
    (proc / "self").mkdir()
    (proc / "107").mkdir()  # exited while being read
    assert find_orphans(proc, uid=1000, name="spytifyd", our_pid=500) == [101]
    assert still_running(proc, [101, 105, 107], name="spytifyd") == [101]
    info = read_proc(proc, 101)
    assert info is not None and (info.uid, info.ppid, info.state) == (1000, 1, "S")


ORPHAN = """
import subprocess, sys
child = subprocess.Popen([sys.argv[1], "300"], executable="sleep", process_group=0,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
print(child.pid)
"""


async def test_kill_orphans_kills_only_ones_left_running(config: Config, tmp_path: Path) -> None:
    # A unique name, so no other spytifyd on this machine is touched.
    name = f"sv-test-spytifyd-{os.getpid()}"
    recorder = SpytifyRecorder(
        dataclasses.replace(config, spytifyd_path=tmp_path / name), SystemClock()
    )
    # One left from "before a restart": its parent is gone, so it isn't ours.
    maker = await asyncio.create_subprocess_exec(
        sys.executable, "-c", ORPHAN, name, stdout=asyncio.subprocess.PIPE
    )
    output, _ = await maker.communicate()
    orphan = int(output)
    # One of our own (a running session): never an orphan.
    ours = await asyncio.create_subprocess_exec(name, "300", executable="sleep")
    try:
        assert await recorder.kill_orphans() == 1
        await until(lambda: gone(orphan))
        assert ours.returncode is None and not gone(ours.pid)
    finally:
        ours.kill()
        await ours.wait()
        if not gone(orphan):
            os.kill(orphan, signal.SIGKILL)


# --- The events file ---------------------------------------------------------------------------


def test_read_events_file_skips_a_cut_line_and_levels(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"method":"track.started","params":{"id":"t1","artist":"a","title":"b","length_ms":1}}\n'
        '{"method":"level","params":{"channels":[{"peak_dbfs":-3,"rms_dbfs":-9}]}}\n'
        '{"params":{"channels":[]},"method":"level"}\n'
        '{"method":"session.state","params":null}\n'
        "[1, 2]\n"
        '{"params":{}}\n'
        '{"method":5,"params":{}}\n'
        "\n"
        "not json\n"
        '{"method":"track.finished","params":{"id":"t1","pa',
        encoding="utf-8",
    )
    at = datetime(2026, 11, 16, tzinfo=UTC)
    records = read_events_file(path, received_at=at)
    assert [(r.method, dict(r.params)) for r in records] == [
        ("track.started", {"id": "t1", "artist": "a", "title": "b", "length_ms": 1}),
        ("session.state", {}),
    ]
    assert all(r.received_at == at for r in records)
    assert read_events_file(tmp_path / "missing.jsonl", received_at=at) == []


async def test_load_events_file_reads_on_the_clock(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"method":"log","params":{"level":"info","msg":"x","ts":"t"}}\n')
    clock = FakeClock()
    records = await load_events_file(path, clock)
    assert [r.method for r in records] == ["log"]
    assert records[0].received_at == clock.now()


async def test_a_long_items_events_file_is_read_off_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spytifyd writes every level record (10 a second: about 860,000 for a 24-hour item), so
    the file is read on a worker thread, never on the event loop (design.md § Stack)."""
    path = tmp_path / "events.jsonl"
    level = '{"method":"level","params":{"peak_dbfs":-3,"rms_dbfs":-15,"channels":[]}}\n'
    finished = '{"method":"track.finished","params":{"id":"t1","path":"/music/a.m4a"}}\n'
    path.write_text(level * 36_000 + finished, encoding="utf-8")  # one hour of recording
    threads: list[int] = []

    def read(path: Path, *, received_at: datetime) -> list[RecorderNotification]:
        threads.append(threading.get_ident())
        return read_events_file(path, received_at=received_at)

    monkeypatch.setattr(events_file_module, "read_events_file", read)
    records = await load_events_file(path, FakeClock())
    assert [r.method for r in records] == ["track.finished"]
    assert len(threads) == 1 and threads[0] != threading.get_ident()


# --- JSON-RPC (recorder/rpc.py) against a scripted server --------------------------------------


class Daemon:
    """A socket server in the test: records request lines, answers what `answer` returns."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.writers: list[asyncio.StreamWriter] = []
        self.answer: Callable[[dict[str, Any]], dict[str, Any] | None] = lambda r: {
            "jsonrpc": "2.0",
            "id": r["id"],
            "result": {"echo": r["method"]},
        }
        self.server: asyncio.Server | None = None

    async def start(self, path: Path) -> None:
        self.server = await asyncio.start_unix_server(self._serve, path=str(path))

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writers.append(writer)
        while line := await reader.readline():
            request = json.loads(line)
            self.requests.append(request)
            reply = self.answer(request)
            if reply is not None:
                self.send(reply)

    def send(self, message: dict[str, Any] | bytes) -> None:
        data = message if isinstance(message, bytes) else json.dumps(message).encode() + b"\n"
        for writer in self.writers:
            writer.write(data)

    async def hang_up(self) -> None:
        for writer in self.writers:
            writer.close()
        assert self.server is not None
        self.server.close()


@pytest.fixture
async def daemon(short_dir: Path) -> AsyncIterator[tuple[Daemon, Path]]:
    server = Daemon()
    path = short_dir / "d.sock"
    await server.start(path)
    yield server, path
    await server.hang_up()


async def connected(path: Path, clock: Clock, daemon: Daemon) -> JsonRpcConnection:
    connection = await JsonRpcConnection.open(path, clock=clock)
    await until(lambda: bool(daemon.writers))
    return connection


async def test_rpc_integer_ids_answers_errors_and_timeouts(
    daemon: tuple[Daemon, Path],
) -> None:
    server, path = daemon
    clock = FakeClock()
    connection = await connected(path, clock, server)
    assert connection.peer_pid == os.getpid()

    assert await connection.call("core.info") == {"echo": "core.info"}
    assert await connection.call("player.control", {"cmd": "pause"}) == {"echo": "player.control"}
    assert server.requests == [
        {"jsonrpc": "2.0", "id": 1, "method": "core.info", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "player.control", "params": {"cmd": "pause"}},
    ]

    server.answer = lambda r: {
        "jsonrpc": "2.0",
        "id": r["id"],
        "error": {"code": -32005, "message": 'the player does not accept "pause"', "data": [1]},
    }
    with pytest.raises(RecorderRpcError) as caught:
        await connection.call("player.control", {"cmd": "pause"})
    assert (caught.value.method, caught.value.code, caught.value.data) == (
        "player.control",
        sp.UNSUPPORTED,
        [1],
    )
    assert caught.value.message == 'the player does not accept "pause"'

    # No answer: TimeoutError after timeout_s of clock time, and the late answer is dropped.
    server.answer = lambda r: None
    call = asyncio.ensure_future(connection.call("session.stop", timeout_s=15))
    await until(lambda: len(server.requests) == 4)
    await clock.advance(14.9)
    assert not call.done()
    await clock.advance(0.1)
    with pytest.raises(TimeoutError):
        await call
    server.send({"jsonrpc": "2.0", "id": 4, "result": {"late": True}})
    server.answer = lambda r: {"jsonrpc": "2.0", "id": r["id"], "result": None}
    assert await connection.call("session.status") is None  # id 5 still works
    assert server.requests[-1]["id"] == 5
    await connection.close()
    await connection.close()  # twice is fine
    assert connection.closed
    with pytest.raises(RecorderGone):
        await connection.call("core.info")


async def test_rpc_notifications_in_order_and_garbage_skipped(
    daemon: tuple[Daemon, Path],
) -> None:
    server, path = daemon
    clock = FakeClock()
    connection = await connected(path, clock, server)
    server.send({"jsonrpc": "2.0", "method": "session.state", "params": {"state": "waiting"}})
    server.send(b"not json\n")
    server.send(b"[1, 2]\n")
    server.send({"jsonrpc": "2.0", "id": 77, "result": {}})  # an answer nobody waits for
    server.send({"jsonrpc": "2.0", "id": 0, "error": {"code": -32700, "message": "parse error"}})
    server.send(b'{"jsonrpc": "2.0", "method": "track.keepable", "params": null}\n')
    server.send(b"x" * (sp.MAX_LINE_BYTES + 10) + b"\n")  # longer than spytifyd ever sends
    server.send({"jsonrpc": "2.0", "method": "log", "params": {"level": "info", "msg": "m"}})
    await asyncio.sleep(0.2)
    await server.hang_up()  # EOF

    notes = [note async for note in connection.notifications()]
    assert [(n.method, dict(n.params)) for n in notes] == [
        ("session.state", {"state": "waiting"}),
        ("track.keepable", {}),
        ("log", {"level": "info", "msg": "m"}),
    ]
    assert all(n.received_at == clock.now() for n in notes)
    assert connection.closed
    assert [note async for note in connection.notifications()] == []  # ended for good


async def test_rpc_eof_fails_the_waiting_calls(daemon: tuple[Daemon, Path]) -> None:
    server, path = daemon
    connection = await connected(path, FakeClock(), server)
    server.answer = lambda r: None
    call = asyncio.ensure_future(connection.call("session.stop"))
    await until(lambda: bool(server.requests))
    await server.hang_up()
    with pytest.raises(RecorderGone):
        await call
    assert connection.closed


async def test_rpc_open_raises_while_nothing_listens(short_dir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        await JsonRpcConnection.open(short_dir / "none.sock", clock=FakeClock())
    stale = short_dir / "stale.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(stale))  # bound, never listening: what a crashed spytifyd leaves
    sock.close()
    with pytest.raises(ConnectionRefusedError):
        await JsonRpcConnection.open(stale, clock=FakeClock())


async def test_wait_on_clock() -> None:
    clock = FakeClock()
    future: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    waiting = asyncio.ensure_future(wait_on_clock(future, clock, 10))
    await clock.settle()  # it starts sleeping on the clock
    await clock.advance(5)
    future.set_result(3)
    assert await waiting == 3

    never: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    waiting = asyncio.ensure_future(wait_on_clock(never, clock, 10))
    await clock.settle()
    await clock.advance(9.9)
    assert not waiting.done()
    await clock.advance(0.1)
    with pytest.raises(TimeoutError):
        await waiting
    assert not never.done()  # left alone
