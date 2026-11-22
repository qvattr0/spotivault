"""The real recorder port: one `spytifyd --once --serve` process per item.

Owner: **recorder** (controller/ARCHITECTURE.md § S6's parts). Specs: plan § Starting Spytify
for an item; design.md § Container (the Spytify defaults) and § Run flow step 3; prototype/probe.py
`Spytify` and `cmd_record` (socket wait, SIGTERM); Spytify's cmd/spytifyd/main.go at 2.0.2. The
protocol itself is recorder/protocol.py (frozen); `ports.Recorder` and `ports.RecorderSession`
are the interface (frozen). The fake one, `fake/recorder.py`, is the reference for behaviour.

**Starting one** (`SpytifyRecorder.start`), exactly:

    spytifyd --once --serve --idle-exit <spec.idle_exit_s>s --wait-target <spec.wait_target_s>s
      --log-file <spec.log_file> --events <spec.events_file>
      --set <key>=<value> …           # spec.settings, in order: settings.recorder_settings(mode)
    env:   only what command_line() lists (never os.environ: config.py is the one reader)
    cwd:   spec.work_dir, created if missing; it must hold no `.env` (Spytify loads one from there)
    asyncio.create_subprocess_exec(..., process_group=0, umask=spec.umask,
                                   stdin=DEVNULL, stdout=DEVNULL, stderr=PIPE)

- Never `preexec_fn` (not safe with threads; the store has one). `process_group=0` puts it in its
  own process group, so SIGKILL reaches it and its children (parec, ffmpeg) together.
- **stderr** carries the same log lines as `--log-file`. The session's one task drains it all the
  time (a full pipe would block spytifyd), keeps the last 50 lines for RecorderStartError.log_tail
  and protocol.classify_exit, then collects the exit code.
- **The socket**: poll for `spec.socket_path` every 0.25 s on the clock until it accepts, at most
  `spec.socket_timeout_s`; if the process exits first, raise RecorderStartError(exit_code=code,
  log_tail=...). The listener must be our own process (SO_PEERCRED): a spytifyd left running on
  the same path answers too, and ours then exits 1 "another spytifyd is listening". Then
  `core.info` (logged), then poll `session.status` every 0.5 s until it has a `session_id` (the
  --once session started; spytifyd waits up to --wait-target for the player), or the process
  exits (RecorderStartError). An exit 0 there means the session already ran and ended: start()
  returns the session as it is, and its notifications and events file tell what happened.
- **Exit codes** (protocol.classify_exit): 2 bad setting, 1 output folder / ffmpeg / files → the
  run fails; 1 "another spytifyd is listening" → `kill_orphans()` and start again once (the
  engine does the retry from the verdict); anything else → the item fails. A start that fails
  without an exit code (the socket never came, spytifyd can't be run) has exit_code None.
- Unix socket paths are limited to 107 bytes. The run engine builds short ones under
  config.runtime_dir (`spytify-<run>-<n>.sock`); a longer one is a RecorderStartError.

**Stopping** (`SpytifySession.terminate`): SIGTERM (spytifyd finishes the current take), wait
`first_grace_s` (45 s), SIGTERM again (stop at once), wait `second_grace_s` (15 s), then SIGKILL.
All within docker's 60 s stop grace. Waits use the clock (`clock.sleep`) raced against the
process's exit, so a FakeClock test can drive them.
- **SIGTERM goes to spytifyd alone, SIGKILL to its whole group.** Its capture (`parec`) and
  encoder (`ffmpeg`) are its children in the same group: a SIGTERM to the group would end the
  capture and the encode under it, the opposite of "finish the current take". SIGKILL must reach
  them, or they'd outlive it.

**Orphans** (`kill_orphans`, start-up recovery and the socket-in-use retry): spytifyd processes
left from before a controller restart. Read /proc (through asyncio.to_thread) for processes owned
by this uid whose argv[0] is named like config.spytifyd_path (`spytifyd`) and whose parent isn't
this controller (our own running sessions are never orphans). SIGTERM each (its group when it
leads one), then SIGKILL the ones still there after 5 s. Return how many.

**Tasks:** a session has one task of its own (stderr, then the exit code), started by the
session and awaited by `wait()`, `terminate()` and `kill()`; its socket's reader is the
JsonRpcConnection's (recorder/rpc.py). The recorder port has no Services, so neither can go
through `services.add_background`; a done-callback logs any failure, so none is lost.

Tests: tests/test_recorder_process.py with a stub executable (tests/recorder_stub/spytifyd.py,
which speaks the protocol from protocol.py on a socket), and tests/test_recorder_integration.py
with the real `spytifyd --fake`, skipped unless SPOTIVAULT_TEST_SPYTIFYD and
SPOTIVAULT_TEST_FFMPEG name the binaries. `portcheck.assert_implements` both classes.
"""

import asyncio
import collections
import logging
import os
import signal
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spotivault.config import Config
from spotivault.container import spytifyd_version
from spotivault.ports import (
    Clock,
    RecorderGone,
    RecorderNotification,
    RecorderRpcError,
    RecorderSpec,
    RecorderStartError,
)
from spotivault.recorder import protocol as sp
from spotivault.recorder.events_file import load_events_file
from spotivault.recorder.rpc import JsonRpcConnection, log_task_failure, wait_on_clock

log = logging.getLogger(__name__)

STDERR_TAIL_LINES = 50  # kept for RecorderStartError.log_tail and classify_exit
SOCKET_POLL_S = 0.25
SESSION_POLL_S = 0.5  # spytifyd itself retries session.start every 0.5 s while it waits
MAX_SOCKET_PATH_BYTES = 107  # sun_path is 108 bytes, with the final NUL
ORPHAN_KILL_GRACE_S = 5.0
FIXED_PATH = "/usr/local/bin:/usr/bin:/bin"  # where the image has parec and pactl
PROC = Path("/proc")


def command_line(spec: RecorderSpec, config: Config) -> tuple[list[str], dict[str, str]]:
    """The argv and the environment for one item's spytifyd. Pure: tests compare it.

    argv: `[config.spytifyd_path, "--once", "--serve", "--idle-exit", f"{spec.idle_exit_s}s",
    "--wait-target", f"{spec.wait_target_s}s", "--log-file", spec.log_file, "--events",
    spec.events_file]`, then `"--set", f"{key}={value}"` for each of spec.settings, in order.

    env (nothing else; PATH is fixed): HOME=config.home_dir, PATH=/usr/local/bin:/usr/bin:/bin,
    LANG=C.UTF-8, TZ=config.tz, XDG_RUNTIME_DIR=config.runtime_dir, DISPLAY=config.display,
    DBUS_SESSION_BUS_ADDRESS=config.dbus_address, PULSE_SERVER=config.pulse_server,
    SPYTIFY_TARGET_PROCESS=config.spytify_target_process, SPYTIFY_TARGET_MPRIS=config.mpris_name,
    SPYTIFY_SOCKET=spec.socket_path, SPYTIFY_CONFIG=config.spytify_config,
    SPYTIFY_FFMPEG=config.ffmpeg_path.
    """
    argv = [
        str(config.spytifyd_path),
        "--once",
        "--serve",
        "--idle-exit",
        f"{spec.idle_exit_s}s",
        "--wait-target",
        f"{spec.wait_target_s}s",
        "--log-file",
        str(spec.log_file),
        "--events",
        str(spec.events_file),
    ]
    for key, value in spec.settings:
        argv += ["--set", f"{key}={value}"]
    env = {
        "HOME": str(config.home_dir),
        "PATH": FIXED_PATH,
        "LANG": "C.UTF-8",
        "TZ": config.tz,
        "XDG_RUNTIME_DIR": str(config.runtime_dir),
        "DISPLAY": config.display,
        "DBUS_SESSION_BUS_ADDRESS": config.dbus_address,
        "PULSE_SERVER": config.pulse_server,
        "SPYTIFY_TARGET_PROCESS": config.spytify_target_process,
        "SPYTIFY_TARGET_MPRIS": config.mpris_name,
        "SPYTIFY_SOCKET": str(spec.socket_path),
        "SPYTIFY_CONFIG": str(config.spytify_config),
        "SPYTIFY_FFMPEG": str(config.ffmpeg_path),
    }
    return argv, env


class SpytifyRecorder:
    """`ports.Recorder` on the image's spytifyd (config.spytifyd_path)."""

    def __init__(self, config: Config, clock: Clock) -> None:
        self.config = config
        self.clock = clock

    async def start(self, spec: RecorderSpec) -> "SpytifySession":
        """Spawns spytifyd for one item and returns once its --once session has started. See the
        module docstring, "Starting one"."""
        if not socket_path_ok(spec.socket_path):
            raise RecorderStartError(
                f"the recorder's socket path is longer than {MAX_SOCKET_PATH_BYTES} bytes: "
                f"{spec.socket_path}",
                exit_code=None,
            )
        argv, env = command_line(spec, self.config)
        try:
            await asyncio.to_thread(_prepare_folders, spec)
        except (OSError, _WorkDirNotEmpty) as exc:
            raise RecorderStartError(
                f"can't prepare spytifyd's folder: {exc}", exit_code=None, log_tail=[str(exc)]
            ) from exc
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                env=env,
                cwd=spec.work_dir,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                process_group=0,  # its own group, for the SIGKILL (never preexec_fn)
                umask=spec.umask,  # applies to the music files it writes
            )
        except OSError as exc:
            raise RecorderStartError(
                f"can't run {argv[0]}: {exc}", exit_code=None, log_tail=[f"spytifyd: {exc}"]
            ) from exc
        log.info(
            "spytifyd started for run %d, item %s (pid %d)", spec.run_id, spec.item_id, process.pid
        )
        session = SpytifySession(spec, self.clock, process)
        try:
            await session._until_ready()
        except BaseException:
            # A start that failed (or was cancelled) leaves nothing running.
            await session.kill()
            raise
        return session

    async def version(self) -> str | None:
        """`spytifyd --version` ("spytifyd v2.0.2 (protocol 1)") as "2.0.2"."""
        return await spytifyd_version(self.config.spytifyd_path)

    async def kill_orphans(self) -> int:
        """Kills spytifyd processes left from before a controller restart. See the module
        docstring, "Orphans"."""
        name = self.config.spytifyd_path.name
        orphans = await asyncio.to_thread(
            find_orphans, PROC, uid=os.getuid(), name=name, our_pid=os.getpid()
        )
        for pid in orphans:
            log.warning("spytifyd (pid %d) was left from before a restart: SIGTERM", pid)
            _signal_orphan(pid, signal.SIGTERM)
        alive = orphans
        deadline = self.clock.monotonic() + ORPHAN_KILL_GRACE_S
        while alive and self.clock.monotonic() < deadline:
            await self.clock.sleep(SOCKET_POLL_S)
            alive = await asyncio.to_thread(still_running, PROC, alive, name=name)
        for pid in alive:
            log.warning(
                "spytifyd (pid %d) ignored SIGTERM for %.0f s: SIGKILL", pid, ORPHAN_KILL_GRACE_S
            )
            _signal_orphan(pid, signal.SIGKILL)
        return len(orphans)


class SpytifySession:
    """`ports.RecorderSession`: one running spytifyd. Built by SpytifyRecorder.start() with the
    process it spawned; its one task starts here."""

    def __init__(
        self, spec: RecorderSpec, clock: Clock, process: asyncio.subprocess.Process
    ) -> None:
        self.spec = spec
        self.clock = clock
        self.core_info: sp.CoreInfo | None = None  # core.info's answer, once start() read it
        self._process = process
        self._rpc: JsonRpcConnection | None = None
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=STDERR_TAIL_LINES)
        # The session's one task: drains stderr, then returns the exit code. wait() awaits it.
        self._supervisor = asyncio.create_task(self._supervise(), name=f"spytifyd {process.pid}")
        self._supervisor.add_done_callback(log_task_failure)

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    @property
    def log_tail(self) -> list[str]:
        """spytifyd's last stderr lines (the same as its --log-file's), oldest first."""
        return list(self._stderr_tail)

    async def call(
        self, method: str, params: Mapping[str, Any] | None = None, *, timeout_s: float = 15.0
    ) -> Any:
        """One JSON-RPC request through recorder/rpc.py's JsonRpcConnection (integer ids).
        RecorderRpcError for an error answer (its code from protocol.py), TimeoutError after
        `timeout_s` on services.clock, RecorderGone once the socket closed."""
        if self._rpc is None:
            raise RecorderGone(f"{method}: the recorder has no socket")
        return await self._rpc.call(method, params, timeout_s=timeout_s)

    async def notifications(self) -> AsyncIterator[RecorderNotification]:
        """Every notification in order, for one consumer, `received_at` from the clock. It ends
        once the socket reached EOF **and** the process exited: the last take's track.finished
        comes as spytifyd exits (FINDINGS § End-of-item handling)."""
        if self._rpc is not None:
            async for notification in self._rpc.notifications():
                yield notification
        # spytifyd closes the socket as it exits; the exit itself comes a moment later.
        await self.wait()

    async def wait(self) -> int:
        """Waits for the exit and returns its code (negative: killed by that signal)."""
        # shield: a waiter that's cancelled mustn't cancel the session's own task.
        return await asyncio.shield(self._supervisor)

    async def terminate(self, *, first_grace_s: float = 45.0, second_grace_s: float = 15.0) -> int:
        """SIGTERM, SIGTERM, SIGKILL. See the module docstring, "Stopping"."""
        if self._supervisor.done():
            return await self.wait()
        log.info("spytifyd (pid %d): SIGTERM, to finish the current take", self.pid)
        self._signal(signal.SIGTERM, group=False)
        if not await self._exited_within(first_grace_s) and self.returncode is None:
            log.warning(
                "spytifyd (pid %d) still running %.0f s after SIGTERM: SIGTERM again, to stop "
                "at once",
                self.pid,
                first_grace_s,
            )
            self._signal(signal.SIGTERM, group=False)
            await self._exited_within(second_grace_s)
        if not self._supervisor.done():
            # Still running, or exited with something in its group holding its stderr.
            log.warning("spytifyd (pid %d) didn't stop: SIGKILL to its process group", self.pid)
            self._signal(signal.SIGKILL, group=True)
        return await self.wait()

    async def kill(self) -> int:
        """SIGKILL to the process group at once, then the exit code."""
        if not self._supervisor.done():
            log.warning("spytifyd (pid %d): SIGKILL to its process group", self.pid)
            self._signal(signal.SIGKILL, group=True)
        return await self.wait()

    async def events_file(self) -> list[RecorderNotification]:
        """The `--events` file, read after the exit: recorder/events_file.load_events_file."""
        return await load_events_file(self.spec.events_file, self.clock)

    # --- Starting --------------------------------------------------------------------------------

    async def _until_ready(self) -> None:
        """Returns once spytifyd's --once session has started, or once it exited 0 (the session
        already ran). Raises RecorderStartError otherwise. Called by SpytifyRecorder.start(),
        which kills the process when this raises."""
        spec = self.spec
        # 1. The socket. spytifyd listens before its session starts.
        deadline = self.clock.monotonic() + spec.socket_timeout_s
        while self._rpc is None:
            if self._supervisor.done():
                await self._fail_unless_ok("before its socket was up")
                return
            self._rpc = await self._connect()
            if self._rpc is not None:
                break
            if self.clock.monotonic() >= deadline:
                raise RecorderStartError(
                    f"spytifyd's socket didn't appear within {spec.socket_timeout_s:.0f} s",
                    exit_code=None,
                    log_tail=self.log_tail,
                )
            await self._exited_within(SOCKET_POLL_S)

        # 2. core.info, for the log.
        try:
            info = await self.call(sp.CORE_INFO, timeout_s=spec.socket_timeout_s)
        except RecorderGone:
            await self._fail_unless_ok("before it answered core.info")
            return
        except (RecorderRpcError, TimeoutError) as exc:
            raise RecorderStartError(
                f"spytifyd didn't answer core.info: {exc}", exit_code=None, log_tail=self.log_tail
            ) from exc
        self.core_info = sp.CoreInfo.from_params(info if isinstance(info, Mapping) else {})
        self._log_core_info(self.core_info)

        # 3. The session. spytifyd retries session.start until the player is there, for at
        # most --wait-target, then exits 1 (no_player).
        deadline = self.clock.monotonic() + spec.wait_target_s + spec.socket_timeout_s
        while True:
            try:
                result = await self.call(sp.SESSION_STATUS, timeout_s=spec.socket_timeout_s)
            except RecorderGone:
                await self._fail_unless_ok("before its session started")
                return
            except (RecorderRpcError, TimeoutError) as exc:
                raise RecorderStartError(
                    f"spytifyd didn't answer session.status: {exc}",
                    exit_code=None,
                    log_tail=self.log_tail,
                ) from exc
            status = sp.SessionStatus.from_params(result if isinstance(result, Mapping) else {})
            if status.session_id:
                log.info("spytifyd (pid %d): session %s started", self.pid, status.session_id)
                return
            if self.clock.monotonic() >= deadline:
                raise RecorderStartError(
                    f"spytifyd's session didn't start within "
                    f"{spec.wait_target_s + spec.socket_timeout_s:.0f} s",
                    exit_code=None,
                    log_tail=self.log_tail,
                )
            if await self._exited_within(SESSION_POLL_S):
                await self._fail_unless_ok("before its session started")
                return

    async def _connect(self) -> JsonRpcConnection | None:
        """A connection to our own spytifyd's socket, or None while it isn't listening yet."""
        try:
            connection = await JsonRpcConnection.open(self.spec.socket_path, clock=self.clock)
        except OSError:
            return None  # not there yet, or a stale socket nobody listens on (spytifyd replaces it)
        peer = connection.peer_pid
        if peer is not None and peer != self.pid:
            # A spytifyd left running answers on this path. Ours exits 1 with "another spytifyd
            # is listening", which start() reports; never talk to the other one.
            log.warning(
                "spytifyd: another process (pid %d) listens on %s", peer, self.spec.socket_path
            )
            await connection.close()
            return None
        return connection

    async def _fail_unless_ok(self, when: str) -> None:
        """spytifyd is exiting before it was ready: RecorderStartError with its exit code and
        last log lines, unless it exited 0 (its session ran and ended already)."""
        if not await self._exited_within(self.spec.socket_timeout_s):
            raise RecorderStartError(
                f"spytifyd closed its socket {when} but didn't exit",
                exit_code=None,
                log_tail=self.log_tail,
            )
        code = await self.wait()
        if code == sp.EXIT_OK:
            log.info("spytifyd (pid %d) exited 0 %s: its session already ended", self.pid, when)
            return
        last = self._stderr_tail[-1] if self._stderr_tail else "no log line"
        raise RecorderStartError(
            f"spytifyd exited with code {code} {when}: {last}",
            exit_code=code,
            log_tail=self.log_tail,
        )

    def _log_core_info(self, info: sp.CoreInfo) -> None:
        failed = ", ".join(check.name for check in info.failed_checks()) or "none"
        log.info(
            "spytifyd (pid %d): %s, protocol %d, target %s, failed checks: %s",
            self.pid,
            info.version,
            info.protocol,
            info.target.process,
            failed,
        )
        if info.protocol != sp.PROTOCOL:
            log.warning(
                "spytifyd speaks protocol %d; the controller knows %d", info.protocol, sp.PROTOCOL
            )
        for warning in info.warnings:
            log.info("spytifyd (pid %d) warns: %s", self.pid, warning)

    # --- The process -----------------------------------------------------------------------------

    async def _supervise(self) -> int:
        """The session's one task: reads stderr until spytifyd closes it (it exits), keeping the
        last lines, then returns the exit code.

        asyncio's Process.wait() returns only once every pipe has closed, as well as the exit. A
        child of spytifyd still holding its stderr would keep this waiting; Go starts spytifyd's
        children (parec, ffmpeg) with pipes of their own, and a group SIGKILL ends any that did.
        """
        stderr = self._process.stderr
        if stderr is not None:
            while True:
                try:
                    line = await stderr.readline()
                except ValueError:  # over asyncio's 64 KiB line limit; the buffer was dropped
                    self._stderr_tail.append("(a log line too long to keep)")
                    continue
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                self._stderr_tail.append(text)
                log.debug("spytifyd %d: %s", self._process.pid, text)
        code = await self._process.wait()
        log.info("spytifyd (pid %d) exited with code %d", self._process.pid, code)
        return code

    async def _exited_within(self, seconds: float) -> bool:
        """Waits up to `seconds` of clock time for the process to exit (and stderr to close)."""
        try:
            await wait_on_clock(self._supervisor, self.clock, seconds)
        except TimeoutError:
            return False
        return True

    def _signal(self, signum: signal.Signals, *, group: bool) -> None:
        """Sends `signum` to spytifyd alone, or to its whole process group (the group's id is its
        pid: it leads the group, from process_group=0).

        Once spytifyd has exited, only a group signal goes out, and only while its stderr is still
        open: something left in its group holds it (and keeps wait() waiting), so the group and
        its id still exist. Once everything has closed, nothing is sent: the pid may be reused.
        """
        if self._supervisor.done():
            return
        if not group and self._process.returncode is not None:
            return
        try:
            if group:
                os.killpg(self._process.pid, signum)
            else:
                os.kill(self._process.pid, signum)
        except ProcessLookupError:
            pass  # it has just exited


def socket_path_ok(path: Path) -> bool:
    """A Unix socket path fits in sun_path (MAX_SOCKET_PATH_BYTES)."""
    return len(str(path).encode()) <= MAX_SOCKET_PATH_BYTES


# --- Folders -------------------------------------------------------------------------------------


class _WorkDirNotEmpty(Exception):
    """spytifyd's cwd holds a `.env` file, which spytifyd would load."""


def _prepare_folders(spec: RecorderSpec) -> None:
    """spytifyd's cwd, and the folders its files and socket go in. Blocking.

    A folder for the log, events file or socket that can't be made is left to spytifyd, which
    fails with its own message (exit 1, protocol.classify_exit "files").
    """
    spec.work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (spec.work_dir / ".env").exists():
        raise _WorkDirNotEmpty(f"{spec.work_dir} holds a .env file, which spytifyd would load")
    for folder in (spec.log_file.parent, spec.events_file.parent, spec.socket_path.parent):
        try:
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            log.warning("spytifyd: can't make %s: %s", folder, exc)


# --- Orphans -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProcInfo:
    """What /proc says about one process."""

    pid: int
    uid: int  # the real uid
    ppid: int
    state: str  # R, S, D, Z, …
    argv0: str


def read_proc(proc: Path, pid: int) -> ProcInfo | None:
    """/proc/<pid>/status and cmdline, or None when it's gone or can't be read. Blocking."""
    try:
        status = (proc / str(pid) / "status").read_text(encoding="utf-8", errors="replace")
        cmdline = (proc / str(pid) / "cmdline").read_bytes()
    except OSError:
        return None
    fields: dict[str, str] = {}
    for line in status.splitlines():
        key, _, value = line.partition(":")
        fields[key] = value.strip()
    try:
        uid = int(fields["Uid"].split()[0])
        ppid = int(fields["PPid"])
        state = fields["State"][:1]
    except (KeyError, IndexError, ValueError):
        return None
    argv0 = cmdline.split(b"\0", 1)[0].decode("utf-8", errors="surrogateescape")
    return ProcInfo(pid=pid, uid=uid, ppid=ppid, state=state, argv0=argv0)


def _is_spytifyd(info: ProcInfo, name: str) -> bool:
    return info.state != "Z" and bool(info.argv0) and Path(info.argv0).name == name


def find_orphans(proc: Path, *, uid: int, name: str, our_pid: int) -> list[int]:
    """The pids of running processes owned by `uid`, named `name` (argv[0]'s last part), whose
    parent isn't `our_pid`: spytifyd processes this controller didn't start. Blocking."""
    found: list[int] = []
    try:
        entries = list(proc.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        info = read_proc(proc, int(entry.name))
        if info is None or info.pid == our_pid:
            continue
        if info.uid == uid and info.ppid != our_pid and _is_spytifyd(info, name):
            found.append(info.pid)
    return sorted(found)


def still_running(proc: Path, pids: Iterable[int], *, name: str) -> list[int]:
    """The ones of `pids` still running under that name (not a zombie, not reused). Blocking."""
    alive: list[int] = []
    for pid in pids:
        info = read_proc(proc, pid)
        if info is not None and _is_spytifyd(info, name):
            alive.append(pid)
    return alive


def _signal_orphan(pid: int, signum: signal.Signals) -> None:
    """Signals an orphan's process group when it leads one (ours always do), else it alone: a
    group it merely belongs to may hold other processes."""
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, signum)
        else:
            os.kill(pid, signum)
    except (ProcessLookupError, PermissionError) as exc:
        log.info("spytifyd (pid %d): %s: %s", pid, signum.name, exc)
