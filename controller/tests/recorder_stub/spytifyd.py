"""A stub `spytifyd` for tests/test_recorder_process.py: a small Python script that speaks Spytify
2.0.2's protocol (recorder/protocol.py) on a Unix socket, the way cmd/spytifyd/main.go does in
`--once --serve` mode. It records nothing.

It takes spytifyd's flags (`--once --serve --idle-exit --wait-target --log-file --events --set`)
and `SPYTIFY_SOCKET`. Like spytifyd it:
- writes every log line as `<ts> <level> <msg>` to stderr and the --log-file, and broadcasts it
  as a `log` notification;
- listens on the socket before its session starts, replaces a stale socket, and exits 1 with
  "socket <path>: another spytifyd is listening on <path>" when a live one answers there;
- appends every notification to the --events file as `{"method", "params"}`;
- on its first SIGTERM (or `session.stop`) finishes the current take and ends; on the second
  (or `session.stop {now}`) stops at once; the last take's `track.finished` is sent as it ends,
  before the socket closes.

Test knobs come as `--set stub.<knob>=<value>` (the recorder passes no environment through):
- `report=<path>`: writes a JSON report at start (pid, pgid, cwd and its entries, umask, env,
  argv). With `output.dir` set, it also makes a folder and a file there, for the umask.
- `exit_early=<code>:<msg>`: logs `msg` as an error and exits `code` before listening (a bad
  --set is 2).
- `listen_after=<s>`: waits that long before listening.
- `session_after=<s>`: the session starts that long after listening (0). `never`: it waits
  --wait-target, then exits 1 (no player).
- `fail_session=<code>:<msg>`: 0.3 s after listening, logs `msg` and exits `code` (session.start
  failed, as for an output folder it can't write to).
- `end_at_once=1`: the session starts and ends at once (exit 0).
- `takes=<n>`, `take_s=<s>`: records `n` takes of `take_s` (0.2) seconds each.
- `idle_s=<s>`: the idle exit, in place of --idle-exit.
- `sigterm=ignore`: SIGTERM is logged and otherwise ignored.
- `hang=<method>`: never answers that method.
- `flood=<n>`: sends `n` log lines at once when the session starts.
- `child=1`: starts `sleep 300` in its process group, as spytifyd's parec and ffmpeg are, with
  its own stderr (as Go's exec gives them). `child=stderr`: the child holds the stub's stderr.
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from spotivault.recorder import protocol as sp

SESSION_ID = "20261116-000000"


class Args:
    def __init__(self, argv: list[str]) -> None:
        self.version = False
        self.idle_exit_s = 30.0
        self.wait_target_s = 15.0
        self.log_file = ""
        self.events = ""
        self.settings: list[tuple[str, str]] = []
        i = 0
        while i < len(argv):
            flag = argv[i]
            if flag in ("--once", "--serve"):
                i += 1
                continue
            if flag == "--version":
                self.version = True
                i += 1
                continue
            value = argv[i + 1]
            if flag == "--idle-exit":
                self.idle_exit_s = float(value.removesuffix("s"))
            elif flag == "--wait-target":
                self.wait_target_s = float(value.removesuffix("s"))
            elif flag == "--log-file":
                self.log_file = value
            elif flag == "--events":
                self.events = value
            elif flag == "--set":
                key, _, setting = value.partition("=")
                self.settings.append((key, setting))
            else:
                raise SystemExit(f"spytifyd: unknown flag {flag}")
            i += 2


class Stub:
    def __init__(self, args: Args, log_file: TextIO | None, events: TextIO | None) -> None:
        self.args = args
        self.knobs = {key[5:]: value for key, value in args.settings if key.startswith("stub.")}
        self.settings = dict(args.settings)
        self.socket_path = Path(os.environ["SPYTIFY_SOCKET"])
        self.log_file = log_file
        self.events = events
        self.clients: set[asyncio.StreamWriter] = set()
        self.state = "idle"
        self.session_id = ""
        self.take: str | None = None
        self.recorded = 0
        self.skipped = 0
        self.stop_mode: str | None = None  # None, "after_take" or "now"
        self.stop_changed = asyncio.Event()

    # --- Output -------------------------------------------------------------------------------

    def log(self, level: str, msg: str) -> None:
        line = sp.LogLine(level=level, msg=msg, ts=datetime.now(UTC).isoformat())
        text = line.text() + "\n"
        sys.stderr.write(text)
        sys.stderr.flush()
        if self.log_file is not None:
            self.log_file.write(text)
            self.log_file.flush()
        self.notify(sp.LOG, line.to_params())

    def notify(self, method: str, params: dict[str, Any] | None) -> None:
        line = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
        for writer in list(self.clients):
            writer.write(line.encode())
        if self.events is not None:
            self.events.write(json.dumps({"method": method, "params": params}) + "\n")
            self.events.flush()

    def set_state(self, state: str) -> None:
        self.state = state
        self.notify(sp.SESSION_STATE, sp.SessionStateChanged(state=state).to_params())

    # --- The process ----------------------------------------------------------------------------

    async def run(self) -> int:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, self.on_sigterm)
        if "exit_early" in self.knobs:
            code, _, msg = self.knobs["exit_early"].partition(":")
            self.log("error", msg)
            return int(code)
        await asyncio.sleep(float(self.knobs.get("listen_after", "0")))
        sock = bind_socket(self.socket_path)
        if isinstance(sock, str):
            self.log("error", f"socket {self.socket_path}: {sock}")
            return 1
        server = await asyncio.start_unix_server(self.serve, sock=sock)
        self.log("info", f"listening on unix {self.socket_path}")
        try:
            return await self.once()
        finally:
            await self.close(server)

    async def close(self, server: asyncio.Server) -> None:
        """bus.Server.Close: stop accepting, remove the socket, send what's queued, disconnect."""
        server.close()
        self.socket_path.unlink(missing_ok=True)
        for writer in list(self.clients):
            try:
                await writer.drain()
            except ConnectionError:
                pass
            writer.close()
        if self.events is not None:
            self.events.close()

    def on_sigterm(self) -> None:
        if self.knobs.get("sigterm") == "ignore":
            self.log("info", "terminated received, ignored")
            return
        if self.stop_mode is None:
            self.log("info", "terminated received, finishing the current track (again to stop now)")
            self.request_stop("after_take")
        else:
            self.log("info", "terminated received, stopping now")
            self.request_stop("now")

    def request_stop(self, mode: str) -> None:
        if self.stop_mode != "now":
            self.stop_mode = mode
        self.stop_changed.set()
        if self.session_id:
            self.set_state("stopping")

    async def wait_or_stop(self, seconds: float) -> str | None:
        """Waits `seconds`, or less when a stop comes. The stop mode, if any."""
        self.stop_changed.clear()
        if self.stop_mode is not None:
            return self.stop_mode
        try:
            await asyncio.wait_for(self.stop_changed.wait(), seconds)
        except TimeoutError:
            pass
        return self.stop_mode

    # --- The --once session -------------------------------------------------------------------

    async def once(self) -> int:
        if "fail_session" in self.knobs:
            await asyncio.sleep(0.3)
            code, _, msg = self.knobs["fail_session"].partition(":")
            self.log("error", msg)
            return int(code)
        session_after = self.knobs.get("session_after", "0")
        if session_after == "never":
            await asyncio.sleep(self.args.wait_target_s)
            self.log(
                "error",
                f"session.start: the player is not running (code {sp.TARGET_NOT_RUNNING})",
            )
            return 1
        await asyncio.sleep(float(session_after))
        self.session_id = SESSION_ID
        self.set_state("waiting")
        if "flood" in self.knobs:
            for n in range(int(self.knobs["flood"])):
                self.log("debug", f"flood {n}")
        if "end_at_once" in self.knobs:
            return self.end()

        takes = int(self.knobs.get("takes", "0"))
        take_s = float(self.knobs.get("take_s", "0.2"))
        for n in range(1, takes + 1):
            self.start_take(n)
            stop = await self.wait_or_stop(take_s)
            if stop == "now":
                self.skip_take()
                return self.end()
            if stop == "after_take" or n == takes:
                break
            self.finish_take()
        if self.stop_mode is None:
            # The player paused at the end: the idle exit ends the session, unless a stop does.
            idle_s = float(self.knobs.get("idle_s", self.args.idle_exit_s))
            self.log("info", "player paused")
            if await self.wait_or_stop(idle_s) == "now":
                self.skip_take()
                return self.end()
            self.log("info", f"player idle for {idle_s:g}s, ending the session")
        if self.take is not None:
            self.finish_take()  # the last take is saved as the session ends
        return self.end()

    def end(self) -> int:
        self.set_state("idle")
        self.session_id = ""
        self.log("info", "session ended")
        return sp.EXIT_OK

    def start_take(self, n: int) -> None:
        self.take = f"{SESSION_ID}-{n:03d}"
        self.set_state("recording")
        self.notify(
            sp.TRACK_STARTED,
            sp.TrackStarted(
                id=self.take, artist="Stub Artist", title=f"Take {n}", length_ms=200
            ).to_params(),
        )
        level = sp.Level(-3.1, -17.4, (sp.ChannelLevel(-3.1, -17.2), sp.ChannelLevel(-3.4, -17.6)))
        self.notify(sp.LEVEL, level.to_params())

    def finish_take(self) -> None:
        assert self.take is not None
        out = self.settings.get("output.dir", "/music")
        finished = sp.TrackFinished(
            id=self.take,
            path=f"{out}/Stub Artist/{self.take}.m4a",
            duration_ms=200,
            bytes=1000,
            tagged=True,
        )
        self.notify(sp.TRACK_FINISHED, finished.to_params())
        self.recorded += 1
        self.take = None

    def skip_take(self) -> None:
        if self.take is None:
            return
        self.notify(
            sp.TRACK_SKIPPED, sp.TrackSkipped(id=self.take, reason="incomplete").to_params()
        )
        self.notify(sp.TRACK_KEEPABLE, sp.TrackKeepable(id=self.take, keepable=True).to_params())
        self.skipped += 1
        self.take = None

    # --- Requests -----------------------------------------------------------------------------

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.clients.add(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                self.answer(writer, line)
        except ConnectionError:
            pass
        finally:
            self.clients.discard(writer)

    def answer(self, writer: asyncio.StreamWriter, line: bytes) -> None:
        try:
            request = json.loads(line)
        except ValueError:
            error = {"code": sp.PARSE_ERROR, "message": "parse error"}
            reply(writer, {"jsonrpc": "2.0", "id": 0, "error": error})
            return
        method, request_id = request.get("method"), request.get("id")
        if method == self.knobs.get("hang"):
            return
        params = request.get("params") or {}
        try:
            result = self.handle(method, params)
        except RpcError as exc:
            error = {"code": exc.code, "message": exc.message, "data": exc.data}
            reply(writer, {"jsonrpc": "2.0", "id": request_id, "error": error})
            return
        reply(writer, {"jsonrpc": "2.0", "id": request_id, "result": result})

    def handle(self, method: str, params: dict[str, Any]) -> Any:
        if method == sp.CORE_INFO:
            checks = tuple(sp.Check(name=name, ok=True) for name in ("target", "ffmpeg"))
            target = sp.TargetInfo(
                process=os.environ.get("SPYTIFY_TARGET_PROCESS", ""),
                mpris=os.environ.get("SPYTIFY_TARGET_MPRIS", ""),
            )
            info = sp.CoreInfo("v2.0.2", sp.PROTOCOL, target, "linux", checks)
            return info.to_params()
        if method == sp.SESSION_STATUS:
            counters = sp.Counters(recorded=self.recorded, skipped=self.skipped)
            state = self.state if self.session_id else "idle"
            return sp.SessionStatus(state, counters, session_id=self.session_id).to_params()
        if method == sp.SESSION_STOP:
            if not self.session_id:
                raise RpcError(sp.NO_SESSION, "no session is running")
            now = params.get("now") is True
            self.request_stop("now" if now else "after_take")
            stopped = sp.SessionStopResult(self.recorded, self.skipped, stopping=not now)
            return stopped.to_params()
        if method in sp.METHODS:
            return {}
        raise RpcError(sp.METHOD_NOT_FOUND, f"unknown method {method}", data={"method": method})


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def reply(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    writer.write((json.dumps(message) + "\n").encode())


def bind_socket(path: Path) -> socket.socket | str:
    """bus.Server.ListenUnix: replaces a stale socket, refuses one a live daemon answers on."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        try:
            probe.connect(str(path))
        except OSError:
            path.unlink()
        else:
            return f"another spytifyd is listening on {path}"
        finally:
            probe.close()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    os.chmod(path, 0o600)
    sock.listen()
    sock.setblocking(False)
    return sock


def write_report(args: Args, knobs: dict[str, str], child_pid: int | None) -> None:
    """What the tests check about how it was started."""
    umask = os.umask(0)
    os.umask(umask)
    out = dict(args.settings).get("output.dir")
    if out:
        folder = Path(out) / "umask-check"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "file.m4a").write_bytes(b"")
    cwd = Path.cwd()
    report = {
        "pid": os.getpid(),
        "pgid": os.getpgid(0),
        "cwd": str(cwd),
        "cwd_entries": sorted(entry.name for entry in cwd.iterdir()),
        "umask": umask,
        "env": dict(os.environ),
        "argv": sys.argv[1:],
        "child_pid": child_pid,
    }
    Path(knobs["report"]).write_text(json.dumps(report), encoding="utf-8")


def main() -> int:
    args = Args(sys.argv[1:])
    if args.version:
        print(f"spytifyd v2.0.2 (protocol {sp.PROTOCOL})")
        return 0
    knobs = {key[5:]: value for key, value in args.settings if key.startswith("stub.")}
    child_pid = None
    if knobs.get("child") in ("1", "stderr"):
        child = subprocess.Popen(
            ["sleep", "300"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=None if knobs["child"] == "stderr" else subprocess.DEVNULL,
        )
        child_pid = child.pid
    if "report" in knobs:
        write_report(args, knobs, child_pid)
    log_file = open(args.log_file, "a", encoding="utf-8") if args.log_file else None
    events = open(args.events, "a", encoding="utf-8") if args.events else None
    try:
        return asyncio.run(Stub(args, log_file, events).run())
    finally:
        if log_file is not None:
            log_file.close()


if __name__ == "__main__":
    sys.exit(main())
