"""Following the logs as they grow, for the live tail (events.md `log.lines`). Blocking: `start()`
and `poll()` run in a thread.

    tail = TailReader(logs_dir)
    recent = tail.start()       # positions at the end of every file; the last RECENT_NS of lines
    new = tail.poll()           # the whole lines written since, in key order
    tail.missed                 # and the lines it couldn't give, by file (an estimate)

**Rotation:** s6-log renames `current` to `@<tai64n>.s` and starts a new `current`. A file is
followed by its inode: when `current` has another inode, the rest of the old one is read from
its rotated name, then every file rotated after it (s6-log may have rotated more than once
between two polls), then the new `current` from its start. A folder whose `current` is missing
for a moment (between s6-log's rename and its new file) is still followed. A file that got
shorter was cut: it's read again from its start.

**Spytify:** each item's log is followed by its name. A log that appears after `start()` is read
from its start; one that's deleted is forgotten.

**Partial lines:** only whole lines are parsed. The bytes after the last newline wait for the
next poll.

**Missed lines:** a file that grew by more than MAX_READ in one poll is read from MAX_READ before
its end; the bytes before are skipped. The lines skipped are counted in `missed` (from the bytes,
at the size of the lines read), so the followers' `dropped` says so and the UI offers to read
them.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from spotivault.logview.files import (
    BOUNDS_READ,
    CURRENT,
    S6_ROTATED,
    SERVICE_NAME,
    SPYTIFY_DIR,
    SPYTIFY_LOG,
    LogFile,
    service_source,
)
from spotivault.logview.lines import NS, Line, LineParser

RECENT_NS = 10 * NS  # start() gives back the lines of the last 10 s, for the race with a page read
MAX_READ = (
    4 * 1024 * 1024
)  # bytes read from one file in one poll; beyond it, the oldest are skipped


@dataclass(slots=True)
class _Followed:
    file: LogFile
    inode: int
    offset: int
    parser: LineParser
    pending: bytes = field(default=b"")
    rotated: str = ""  # s6: the name of the newest rotated file read, or "" for none


class TailReader:
    """Follows every log file in `logs_dir`: s6-log's `current` files and Spytify's item logs."""

    def __init__(self, logs_dir: Path) -> None:
        self.logs_dir = logs_dir
        self._followed: dict[Path, _Followed] = {}  # by the folder for s6, by the file for Spytify
        self._started = False
        self.skipped_bytes = 0  # bytes jumped over because a file grew by more than MAX_READ
        self.missed: list[tuple[LogFile, int]] = []  # the last poll's lines skipped, per file

    def start(self, now_ns: int) -> list[Line]:
        """Follows every file from its end. Returns the lines of the last RECENT_NS before
        `now_ns`, read from each file's last BOUNDS_READ bytes."""
        recent: list[Line] = []
        for key, file in self._current_files():
            try:
                stat = file.path.stat()
            except OSError:
                continue
            followed = _Followed(file, stat.st_ino, stat.st_size, file.parser(stat.st_mtime_ns))
            followed.rotated = _newest_rotated(key) if file.kind == "s6" else ""
            self._followed[key] = followed
            recent.extend(self._recent(followed, stat.st_size, now_ns - RECENT_NS))
        self._started = True
        recent.sort(key=lambda line: line.key)
        return recent

    def poll(self) -> list[Line]:
        """The whole lines written since the last poll (or start), in key order. `missed` then
        holds the lines this poll skipped."""
        if not self._started:
            raise RuntimeError("TailReader.poll() before start()")
        self.missed = []
        lines: list[Line] = []
        seen: set[Path] = set()
        for key, file in self._current_files():
            seen.add(key)
            lines.extend(self._poll_one(key, file))
        for key, followed in list(self._followed.items()):
            if key in seen:
                continue
            if followed.file.kind == "s6" and key.is_dir():
                continue  # `current` is between s6-log's rename and its new file: keep following
            del self._followed[key]
        lines.sort(key=lambda line: line.key)
        return lines

    def _current_files(self) -> list[tuple[Path, LogFile]]:
        """Each followed file now: (its key, the file)."""
        found: list[tuple[Path, LogFile]] = []
        try:
            folders = sorted(entry for entry in self.logs_dir.iterdir() if entry.is_dir())
        except OSError:
            return found
        for folder in folders:
            if folder.name == SPYTIFY_DIR:
                try:
                    names = sorted(os.listdir(folder))
                except OSError:
                    continue
                for name in names:
                    match = SPYTIFY_LOG.fullmatch(name)
                    if match is not None:
                        path = folder / name
                        file = LogFile(path, name[:-4], "spytify", int(match["run"]), "spytify")
                        found.append((path, file))
            elif SERVICE_NAME.fullmatch(folder.name) and (folder / CURRENT).exists():
                file = LogFile(
                    folder / CURRENT, folder.name, service_source(folder.name), None, "s6"
                )
                found.append((folder, file))
        return found

    def _poll_one(self, key: Path, file: LogFile) -> list[Line]:
        try:
            stat = file.path.stat()
        except OSError:
            return []
        followed = self._followed.get(key)
        if followed is None:  # new since start(): from its start
            followed = _Followed(file, stat.st_ino, 0, file.parser(stat.st_mtime_ns))
            followed.rotated = _newest_rotated(key) if file.kind == "s6" else ""
            self._followed[key] = followed
        lines: list[Line] = []
        if followed.inode != stat.st_ino:
            # s6-log rotated it: the rest of the old file, under its new name, then every file
            # rotated after it, then the new one.
            lines.extend(self._read_rotated(key, followed))
            followed.inode = stat.st_ino
            followed.offset = 0
            followed.pending = b""
        elif stat.st_size < followed.offset:
            followed.offset = 0  # cut short: read it again
            followed.pending = b""
        lines.extend(self._read(followed, file.path, stat.st_size))
        return lines

    def _read_rotated(self, folder: Path, followed: _Followed) -> list[Line]:
        """After a rotation: the rest of the file that was `current` (found by its inode), then
        each file rotated after it, whole. Rotated files are named by time, so by name is in
        order. If the old file is gone (deleted already), the files rotated since the last one
        known are read."""
        try:
            names = sorted(name for name in os.listdir(folder) if S6_ROTATED.fullmatch(name))
        except OSError:
            names = []
        old_name = ""
        for name in reversed(names):
            try:
                if (folder / name).stat().st_ino == followed.inode:
                    old_name = name
                    break
            except OSError:
                continue
        lines: list[Line] = []
        after = followed.rotated
        if old_name:
            lines.extend(self._read(followed, folder / old_name, None))
            after = old_name
        for name in names:
            if name <= after:
                continue
            followed.offset = 0
            followed.pending = b""
            lines.extend(self._read(followed, folder / name, None))
            after = name
        followed.rotated = after
        return lines

    def _read(self, followed: _Followed, path: Path, size: int | None) -> list[Line]:
        """The whole lines from `followed.offset` to `size` (None: to the end)."""
        try:
            with path.open("rb") as handle:
                end = size if size is not None else os.fstat(handle.fileno()).st_size
                if end <= followed.offset:
                    return []
                start = followed.offset
                skipped = end - start - MAX_READ if end - start > MAX_READ else 0
                if skipped:
                    self.skipped_bytes += skipped
                    start = end - MAX_READ
                handle.seek(start)
                data = handle.read(end - start)
        except OSError:
            return []
        followed.offset = start + len(data)
        if skipped:  # started mid-line: drop up to the first whole one
            data = data[data.find(b"\n") + 1 :]
        else:
            data = followed.pending + data
        cut = data.rfind(b"\n")
        if cut < 0:
            followed.pending = data
            return []
        followed.pending = data[cut + 1 :]
        text = data[:cut].decode("utf-8", errors="replace")
        lines = [followed.parser.parse(raw) for raw in text.split("\n") if raw.strip()]
        if skipped:
            self._miss(followed, skipped, cut / max(1, len(lines)))
        return lines

    def _miss(self, followed: _Followed, skipped_bytes: int, line_bytes: float) -> None:
        """Counts the lines in `skipped_bytes` as missed, at `line_bytes` a line (at least 1)."""
        self.missed.append((followed.file, max(1, round(skipped_bytes / max(1.0, line_bytes)))))

    def _recent(self, followed: _Followed, size: int, since_ns: int) -> list[Line]:
        """The lines at the end of a file newer than `since_ns`. The parser isn't touched."""
        start = max(0, size - BOUNDS_READ)
        try:
            with followed.file.path.open("rb") as handle:
                handle.seek(start)
                data = handle.read(size - start)
        except OSError:
            return []
        if start > 0:
            data = data[data.find(b"\n") + 1 :]
        cut = data.rfind(b"\n")
        followed.pending = data[cut + 1 :] if cut >= 0 else data
        if cut < 0:
            return []
        parser = followed.file.parser(followed.parser.last_ns)
        text = data[:cut].decode("utf-8", errors="replace")
        lines = [parser.parse(raw) for raw in text.split("\n") if raw.strip()]
        followed.parser.last_ns = parser.last_ns
        followed.parser.dup = parser.dup
        followed.parser.level = parser.level
        return [line for line in lines if line.at_ns >= since_ns]


def _newest_rotated(folder: Path) -> str:
    """The name of an s6 folder's newest rotated file, or "" for none."""
    try:
        names = [name for name in os.listdir(folder) if S6_ROTATED.fullmatch(name)]
    except OSError:
        return ""
    return max(names, default="")
