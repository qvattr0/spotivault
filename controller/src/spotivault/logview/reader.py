"""GET /api/logs: a page of lines, newest first from `before` back, filtered. Blocking: run it in a
thread.

**How a page is read:** every file the filter wants goes on a heap, keyed by the time of its last
line (`files.bounds`). The heap gives back the newest thing left. A file is read when it comes
up: its lines that pass the filter are kept, and the file goes back on the heap keyed by its
newest one not given out yet. So the lines come out newest first across every source, as one
merge, and only the files a page reaches are read. A file whose lines are all newer than
`before`, or all outside the run, isn't read at all.

**Bounded:** a page stops opening files once it has read READ_BUDGET bytes, if that moves the
cursor back: it then ends with fewer lines than asked for (even none), and a cursor just above
the next file's last line. Every line left to give is at or below that file's last time, and
every line given is above it. A page that couldn't move the cursor reads on, so every page makes
progress.

**Lines written meanwhile:** a file's lines newer than its last line when the page started are
left out. They're newer than the page; the live tail has them.
"""

import heapq
from dataclasses import dataclass, field
from pathlib import Path

from spotivault.logview.files import LogFile, bounds, list_files, read_file
from spotivault.logview.lines import DEFAULT_LEVELS, NS, Key, Level, Line, Source

READ_BUDGET = 8 * 1024 * 1024  # bytes of log files one page may read
RUN_MARGIN_NS = 5 * NS  # a run's lines: from 5 s before its start to 5 s after its end
MAX_LIMIT = 500


@dataclass(slots=True)
class LogFilter:
    """The Logs tab's filters (openapi.yaml listLogs). `span` is the run's time, in ns, with the
    margin: (start, end), end None while the run goes on. `query` is lowercased."""

    sources: frozenset[Source] | None = None  # None: every source
    levels: frozenset[Level] = DEFAULT_LEVELS
    run_id: int | None = None
    span: tuple[int, int | None] | None = None
    query: str | None = None
    secrets: tuple[str, ...] = field(default=())

    def wants_file(self, file: LogFile) -> bool:
        if self.sources is not None and file.source not in self.sources:
            return False
        if self.run_id is not None and file.source == "spytify":
            return file.run_id == self.run_id
        return True

    def in_span(self, at_ns: int) -> bool:
        if self.span is None:
            return True
        start, end = self.span
        return at_ns >= start and (end is None or at_ns <= end)

    def matches(self, line: Line) -> bool:
        """Whether the line passes every filter. The search looks in the masked message."""
        if self.sources is not None and line.source not in self.sources:
            return False
        if line.level not in self.levels:
            return False
        if self.run_id is not None:
            if line.source == "spytify":
                if line.run_id != self.run_id:
                    return False
            elif not self.in_span(line.at_ns):
                return False
        if self.query is not None and self.query not in line.masked(self.secrets).lower():
            return False
        return True


@dataclass(slots=True)
class Page:
    lines: list[Line]  # oldest first
    next_before: Key | None


def read_page(
    logs_dir: Path,
    flt: LogFilter,
    *,
    before: Key | None = None,
    limit: int = 200,
    budget: int = READ_BUDGET,
) -> Page:
    """The newest `limit` lines matching `flt` with a key below `before`."""
    limit = max(1, min(limit, MAX_LIMIT))
    wanted: list[tuple[LogFile, int]] = []
    for file in list_files(logs_dir):
        if not flt.wants_file(file):
            continue
        found = bounds(file)
        if found is None:
            continue
        if before is not None and found.lower_ns > before[0]:
            continue  # every line in it is newer than the cursor
        if file.source != "spytify" and flt.span is not None:
            start, end = flt.span
            if found.upper_ns < start or (end is not None and found.lower_ns > end):
                continue
        wanted.append((file, found.upper_ns))

    # Heap entries are plain tuples, compared in C: (-at_ns, -rank, -dup, tie, lines, index).
    # `rank` orders services as the key does; a file not read yet ranks above every service, so
    # it's read before any line at its last time goes out. `lines` is None for such a file.
    services = sorted({file.service for file, _ in wanted})
    rank = {service: n for n, service in enumerate(services)}
    unread = len(services)
    files: list[LogFile] = []
    heap: list[tuple[int, int, int, int, list[Line] | None, int]] = []
    for tie, (file, upper) in enumerate(wanted):
        files.append(file)
        heap.append((-upper, -unread, 0, tie, None, 0))
    heapq.heapify(heap)
    span_start = flt.span[0] if flt.span is not None and flt.run_id is not None else None

    newest_first: list[Line] = []
    read = 0
    while heap:
        neg_at, neg_rank, _, tie, lines, index = heap[0]
        if span_start is not None and -neg_at < span_start:
            break  # everything left is older than the run (its Spytify logs are inside it)
        if lines is None:
            upper = -neg_at
            if read >= budget and (before is None or (upper + 1, "", 0) < before):
                return Page(newest_first[::-1], (upper + 1, "", 0))
            matching, size = _read_matching(files[tie], flt, before, upper)
            read += size
            if matching:
                newest = matching[-1]
                heapq.heapreplace(
                    heap,
                    (-newest.at_ns, -rank[newest.service], -newest.dup, tie, matching, 0),
                )
            else:
                heapq.heappop(heap)
            continue
        line = lines[len(lines) - 1 - index]
        newest_first.append(line)
        index += 1
        if len(newest_first) >= limit:
            more = index < len(lines) or len(heap) > 1  # this file, or another, has more
            return Page(newest_first[::-1], line.key if more else None)
        if index < len(lines):
            older = lines[len(lines) - 1 - index]
            heapq.heapreplace(
                heap, (-older.at_ns, -rank[older.service], -older.dup, tie, lines, index)
            )
        else:
            heapq.heappop(heap)
    return Page(newest_first[::-1], None)


def _read_matching(
    file: LogFile, flt: LogFilter, before: Key | None, upper: int
) -> tuple[list[Line], int]:
    """The file's lines that pass the filter, below `before` and at most `upper` (its last time
    when the page started), oldest first; and the bytes read."""
    lines, size = read_file(file)
    return [
        line
        for line in lines
        if line.at_ns <= upper and (before is None or line.key < before) and flt.matches(line)
    ], size
