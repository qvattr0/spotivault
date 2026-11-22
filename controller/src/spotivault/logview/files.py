"""The log files in /config/logs, and reading them (History › Logs). Everything here blocks: call it
from a thread (asyncio.to_thread), never on the event loop.

    /config/logs/<service>/current        s6-log's live file, for each s6 service
    /config/logs/<service>/@<tai64n>.s    its rotated files (`.u`: one cut short by a crash)
    /config/logs/init/current             the start-up checks (init-spotivault), in s6-log's format
    /config/logs/spytify/<run>-<item>.log Spytify's log for one item (`-2`: the second attempt)
    /config/logs/spytify/*.events.jsonl   Spytify's raw events: never read here

**Sources:** `controller` is the controller's folder, `client` is `spotify` (the client's
stdout and stderr), `spytify` the item logs, and every other folder `system` (dbus, pulseaudio,
vnc, wm, xserver, init).

**Partial lines:** a file's last line is read only once it ends with a newline. s6-log and
Spytify write whole lines, so an unfinished one is still being written.
"""

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from spotivault.logview.lines import Line, LineParser, Source

SPYTIFY_DIR = "spytify"
CURRENT = "current"
S6_ROTATED = re.compile(r"@[0-9a-f]{24}\.[su]")
SPYTIFY_LOG = re.compile(
    r"(?P<run>\d{1,12})-(?P<item>[0-9A-Za-z]{1,40})(?:-(?P<attempt>\d{1,3}))?\.log"
)
SPYTIFY_EVENTS = re.compile(
    r"(?P<run>\d{1,12})-(?P<item>[0-9A-Za-z]{1,40})(?:-(?P<attempt>\d{1,3}))?\.events\.jsonl"
)
SERVICE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
BOUNDS_READ = 8192  # bytes read at each end of a file for its first and last times, to start with
BOUNDS_MAX = 1024 * 1024  # and at most, for a very long line


def service_source(service: str) -> Source:
    if service == "controller":
        return "controller"
    if service == "spotify":
        return "client"
    return "system"


@dataclass(frozen=True, slots=True)
class LogFile:
    """One file to read. `service` is the folder's name, or a Spytify log's name without `.log`."""

    path: Path
    service: str
    source: Source
    run_id: int | None
    kind: Literal["s6", "spytify"]

    @property
    def archive_name(self) -> str:
        """Its name in the logs zip: `controller/current`, `spytify/42-liked.log`."""
        return f"{self.path.parent.name}/{self.path.name}"

    def parser(self, fallback_ns: int = 0) -> LineParser:
        return LineParser(
            kind=self.kind,
            source=self.source,
            service=self.service,
            run_id=self.run_id,
            fallback_ns=fallback_ns,
        )


def list_files(logs_dir: Path) -> list[LogFile]:
    """Every log file to show, oldest first within each service. A folder that can't be read is
    left out."""
    files: list[LogFile] = []
    try:
        folders = sorted(entry for entry in logs_dir.iterdir() if entry.is_dir())
    except OSError:
        return files
    for folder in folders:
        if folder.name == SPYTIFY_DIR:
            files.extend(_spytify_files(folder))
        elif SERVICE_NAME.fullmatch(folder.name):
            files.extend(_s6_files(folder))
    return files


def _names(folder: Path) -> list[str]:
    try:
        return sorted(os.listdir(folder))
    except OSError:
        return []


def _s6_files(folder: Path) -> Iterator[LogFile]:
    service = folder.name
    source = service_source(service)
    names = _names(folder)
    # Rotated files are named by the time they were closed (TAI64N, hex): by name is by time.
    for name in names:
        if S6_ROTATED.fullmatch(name):
            yield LogFile(folder / name, service, source, None, "s6")
    if CURRENT in names:
        yield LogFile(folder / CURRENT, service, source, None, "s6")


def _spytify_files(folder: Path) -> Iterator[LogFile]:
    for name in _names(folder):
        match = SPYTIFY_LOG.fullmatch(name)
        if match is not None:
            yield LogFile(
                folder / name, name[: -len(".log")], "spytify", int(match["run"]), "spytify"
            )


def complete_text(data: bytes) -> str:
    """The whole lines in `data`, decoded: anything after the last newline is left out."""
    end = data.rfind(b"\n")
    if end < 0:
        return ""
    return data[:end].decode("utf-8", errors="replace")


def parse_text(file: LogFile, text: str, parser: LineParser) -> list[Line]:
    return [parser.parse(raw) for raw in text.split("\n") if raw.strip()]


def read_file(file: LogFile) -> tuple[list[Line], int]:
    """The file's lines in key order, and how many bytes it holds. [] if it's gone."""
    try:
        stat = file.path.stat()
        data = file.path.read_bytes()
    except OSError:
        return [], 0
    lines = parse_text(file, complete_text(data), file.parser(stat.st_mtime_ns))
    lines.sort(key=lambda line: line.key)  # in order already, unless the clock went back
    return lines, len(data)


@dataclass(frozen=True, slots=True)
class Bounds:
    """The times a file's lines lie between: its first line's, and the newest in its last lines.
    Lines are in time order in a file (unless the clock went back), so these hold."""

    lower_ns: int
    upper_ns: int
    size: int
    mtime_ns: int


def bounds(file: LogFile) -> Bounds | None:
    """None for a file that's gone or holds no whole line.

    Each end is read BOUNDS_READ bytes at a time, doubled until it holds a whole line, up to
    BOUNDS_MAX. A line longer than that (Spytify's have no limit) leaves the safe bounds: from 0,
    or up to the file's last write."""
    try:
        with file.path.open("rb") as handle:
            stat = os.fstat(handle.fileno())
            if stat.st_size == 0:
                return None
            first = _first_time(file, handle, stat.st_size, stat.st_mtime_ns)
            if first is None:
                return None
            last = _last_time(file, handle, stat.st_size)
    except OSError:
        return None
    upper = max(last if last is not None else stat.st_mtime_ns, first)
    return Bounds(lower_ns=first, upper_ns=upper, size=stat.st_size, mtime_ns=stat.st_mtime_ns)


def _first_time(file: LogFile, handle: BinaryIO, size: int, mtime_ns: int) -> int | None:
    """The first line's time; None when the file holds no whole line; 0 when its first line is
    longer than BOUNDS_MAX."""
    window = BOUNDS_READ
    while True:
        handle.seek(0)
        head = handle.read(min(window, size))
        if b"\n" in head:
            break
        if len(head) >= size:
            return None  # no newline at all: nothing to show yet
        if window >= BOUNDS_MAX:
            return 0
        window *= 2
    parser = file.parser(mtime_ns)
    for raw in complete_text(head).split("\n"):
        if raw.strip():
            return parser.parse(raw).at_ns
    return mtime_ns


def _last_time(file: LogFile, handle: BinaryIO, size: int) -> int | None:
    """The newest time in the file's last whole lines, or None when there's none within
    BOUNDS_MAX of its end."""
    window = BOUNDS_READ
    while True:
        start = max(0, size - window)
        handle.seek(start)
        tail = handle.read(size - start)
        # The window may start mid-line: drop up to the first newline, unless it's the file's start.
        if start > 0:
            tail = tail[tail.find(b"\n") + 1 :]
        parser = file.parser(0)
        newest: int | None = None
        for raw in complete_text(tail).split("\n"):
            if raw.strip():
                line = parser.parse(raw)
                if line.at_ns and (newest is None or line.at_ns > newest):
                    newest = line.at_ns
        if newest is not None or start == 0 or window >= BOUNDS_MAX:
            return newest
        window *= 2
