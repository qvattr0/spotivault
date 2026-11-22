"""History › Logs: `services.logs` (web-ui.md § Logs tab, openapi.yaml listLogs and downloadLogs,
events.md § Logs).

    await services.logs.page(sources=…, levels=…, run=…, q=…, before=…, limit=…)  → LogPage
    await services.logs.download(days)        → (zip file, its name); stream() sends it
    await services.logs.follow(sub, message)  # WS /api/events: `logs.follow`
    services.logs.unfollow(sub)               # `logs.unfollow`

**Never on the loop:** every file read, the zip, the retention pass, and the live tail's
matching run in threads.

**The live tail** runs only while a connection follows the logs: the `logs.tail` background
task waits on an event until `follow()` wakes it. Then every TAIL_INTERVAL_S (real time: it's
how often a browser gets a batch, not world time) it reads what the files gained
(tail.TailReader), and gives each follower the lines its filter matches, as one `log.lines`.
The matching happens in a thread (`make_batches`): each follower's newest LOG_BATCH_MAX matches
become LogLines, and the rest are only counted, in `dropped`, with the lines the reader skipped.
It keeps the last 10 s of lines, which a new follower gets at once: a page read and the follow
race, and the UI drops the lines it already has by `id`. A poll that fails is logged, and the
tail starts again after TAIL_RETRY_S: it never stops the controller.

**A run's filter, live:** the run's lines pass until it ends. A run still going has no end yet;
once `services.runs.active()` is another run or none, the follower's end is set to then + 5 s.

**Retention** (retention.py): at start-up and every RETENTION_EVERY_S, on the services' clock.

**Real time against the files:** retention's 14 days and the zip's last `days` compare with the
files' last-write times, so they use real time (`wall_ns`), never the fake world's clock, which
can run ahead.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import IO, TYPE_CHECKING, Any

from spotivault.api.models import LogPage
from spotivault.errors import ApiError, validation_failed
from spotivault.events import LOG_BATCH_MAX, Subscription
from spotivault.logview.archive import build_zip, read_chunk
from spotivault.logview.files import LogFile
from spotivault.logview.lines import (
    DEFAULT_LEVELS,
    LEVELS,
    SOURCES,
    Level,
    Line,
    Source,
    datetime_ns,
    decode_key,
    encode_key,
)
from spotivault.logview.reader import RUN_MARGIN_NS, LogFilter, read_page
from spotivault.logview.retention import BUDGET_BYTES, DAY_NS, Pruned, prune
from spotivault.logview.tail import RECENT_NS, TailReader

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

TAIL_INTERVAL_S = 0.5  # events.md § Logs: at most twice a second
TAIL_RETRY_S = 5.0  # after a poll that failed
RETENTION_EVERY_S = 3600.0
RECENT_MAX = 2000  # lines kept for a new follower, at most
QUERY_MAX = 200
FOLLOW_ID_MAX = 64


@dataclass(slots=True)
class Following:
    """What one connection follows: its filter, and the id it gave (echoed in `log.lines`)."""

    filter: LogFilter
    follow_id: Any


@dataclass(slots=True)
class Batch:
    """One follower's `log.lines`: its newest matching lines, as LogLines, and how many more
    matched (or may have: lines the reader skipped)."""

    lines: list[dict[str, Any]]
    dropped: int


class LogsService:
    """The Logs tab's endpoints and live tail, and log retention. `services.logs`."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        self.logs_dir = services.config.logs_dir
        password = services.config.ui_password
        self.secrets: tuple[str, ...] = (password,) if password else ()
        self.tail_interval_s = TAIL_INTERVAL_S
        self.wall_ns: Callable[[], int] = time.time_ns  # real time, for the files' times
        self._wake = asyncio.Event()
        self._tail: TailReader | None = None
        self._recent: deque[Line] = deque(maxlen=RECENT_MAX)
        self._zip_lock = asyncio.Lock()
        services.add_background("logs.tail", self.tail)
        services.add_background("logs.retention", self.keep_tidy)

    # --- GET /api/logs --------------------------------------------------------------------------

    async def page(
        self,
        *,
        sources: Sequence[Source] | None = None,
        levels: Sequence[Level] | None = None,
        run: int | None = None,
        q: str | None = None,
        before: str | None = None,
        limit: int = 200,
    ) -> LogPage:
        key = None
        if before is not None:
            key = decode_key(before)
            if key is None:
                raise validation_failed("before", "before isn't a line's id.")
        flt = await self.make_filter(sources=sources, levels=levels, run=run, q=q)
        if run is not None and flt.span is None:
            raise ApiError(404, "not_found", "No run with this id.")
        page = await asyncio.to_thread(read_page, self.logs_dir, flt, before=key, limit=limit)
        return LogPage.model_validate(
            {
                "lines": [line.to_api(self.secrets) for line in page.lines],
                "next_before": encode_key(page.next_before) if page.next_before else None,
            }
        )

    async def make_filter(
        self,
        *,
        sources: Sequence[Source] | None = None,
        levels: Sequence[Level] | None = None,
        run: int | None = None,
        q: str | None = None,
    ) -> LogFilter:
        """The filter for these parameters. For a run that isn't in History (or isn't a run),
        `span` is None."""
        span = await self.run_span(run) if run is not None else None
        return LogFilter(
            sources=frozenset(sources) if sources else None,
            levels=frozenset(levels) if levels else DEFAULT_LEVELS,
            run_id=run,
            span=span,
            query=q.lower() if q else None,
            secrets=self.secrets,
        )

    async def run_span(self, run_id: int) -> tuple[int, int | None] | None:
        """The run's time, in ns, with the margin either side; end None while it goes on."""
        row = await self.services.store.fetchone(
            "SELECT kind, started_at, ended_at FROM runs WHERE id = ?", (run_id,)
        )
        if row is None or row["kind"] != "run":
            return None
        start = datetime_ns(datetime.fromisoformat(row["started_at"])) - RUN_MARGIN_NS
        ended = row["ended_at"]
        if ended is None:
            return (start, None)
        return (start, datetime_ns(datetime.fromisoformat(ended)) + RUN_MARGIN_NS)

    # --- GET /api/logs/download -----------------------------------------------------------------

    async def download(self, days: int) -> tuple[IO[bytes], str]:
        """The zip of the last `days` days (in a spooled temporary file), and its file name.
        One zip is built at a time."""
        now = self.services.clock.now()
        since_ns = self.wall_ns() - days * DAY_NS
        async with self._zip_lock:
            handle = await asyncio.to_thread(build_zip, self.logs_dir, since_ns, self.secrets)
        local = now.astimezone(self.services.config.zone)
        return handle, f"spotivault-logs-{local:%Y%m%d-%H%M}.zip"

    @staticmethod
    async def stream(handle: IO[bytes]) -> AsyncIterator[bytes]:
        """The zip's bytes, read in a thread, then the file closed (also when the client leaves)."""
        try:
            while chunk := await asyncio.to_thread(read_chunk, handle):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    # --- The live tail --------------------------------------------------------------------------

    async def follow(self, sub: Subscription, message: dict[str, Any]) -> bool:
        """`logs.follow`: starts or changes what `sub` follows. False (and nothing changes) for a
        message that doesn't fit events.md § Logs."""
        parsed = parse_follow(message)
        if parsed is None:
            log.debug("logs: a logs.follow message that doesn't fit; ignored")
            return False
        sources, levels, run, q, follow_id = parsed
        flt = await self.make_filter(sources=sources, levels=levels, run=run, q=q)
        if run is not None and flt.span is None:
            flt.span = (0, 0)  # no such run: nothing matches
        following = Following(flt, follow_id)
        sub.log_follow = following
        self._wake.set()
        # The last seconds' lines at once: the page the UI reads may have missed them.
        recent = list(self._recent)
        if recent:
            (batch,) = await asyncio.to_thread(make_batches, [flt], recent, [], self.secrets)
            if batch is not None and sub.log_follow is following:
                self._push(sub, following, batch)
        return True

    def unfollow(self, sub: Subscription) -> None:
        """`logs.unfollow`."""
        sub.log_follow = None

    async def tail(self) -> None:
        """Background task: the live tail, while anyone follows. A poll that fails is logged and
        the tail starts again: it never ends the task."""
        bus = self.services.bus
        while True:
            if not bus.log_followers():
                self._tail = None
                self._recent.clear()
                self._wake.clear()
                await self._wake.wait()
                continue
            try:
                await self._tail_once()
            except Exception:
                log.exception("logs: the live tail failed; it starts again in %.0f s", TAIL_RETRY_S)
                self._tail = None
                await asyncio.sleep(TAIL_RETRY_S)

    async def _tail_once(self) -> None:
        """Starts the reader, or waits TAIL_INTERVAL_S and polls it; then delivers."""
        reader = self._tail
        if reader is None:
            reader = TailReader(self.logs_dir)
            lines = await asyncio.to_thread(reader.start, self._now_ns())
            self._tail = reader
            await self.deliver(lines)
            return
        await asyncio.sleep(self.tail_interval_s)
        if self._tail is not reader:
            return  # nobody follows any more, or it started again
        lines = await asyncio.to_thread(reader.poll)
        await self.deliver(lines, reader.missed)

    async def deliver(self, lines: list[Line], missed: Sequence[tuple[LogFile, int]] = ()) -> None:
        """Gives each follower the lines its filter matches (worked out in a thread), and keeps
        them for new followers. `missed`: lines the reader skipped, per file, counted in each
        follower's `dropped`."""
        now_ns = self._now_ns()
        self._remember(lines[-RECENT_MAX:], now_ns)
        self._end_finished_runs(now_ns)
        if not lines and not missed:
            return
        targets = [
            (sub, sub.log_follow)
            for sub in self.services.bus.log_followers()
            if isinstance(sub.log_follow, Following)
        ]
        if not targets:
            return
        filters = [following.filter for _, following in targets]
        batches = await asyncio.to_thread(make_batches, filters, lines, list(missed), self.secrets)
        for (sub, following), batch in zip(targets, batches, strict=True):
            # A follow that changed meanwhile got these lines from `_recent` already.
            if batch is not None and sub.log_follow is following:
                self._push(sub, following, batch)

    def _push(self, sub: Subscription, following: Following, batch: Batch) -> None:
        sub.push_logs(
            batch.lines,
            at=self.services.clock.now(),
            follow_id=following.follow_id,
            dropped=batch.dropped,
        )

    def _remember(self, lines: list[Line], now_ns: int) -> None:
        self._recent.extend(lines)
        while self._recent and self._recent[0].at_ns < now_ns - RECENT_NS:
            self._recent.popleft()

    def _end_finished_runs(self, now_ns: int) -> None:
        """A follower of a run that was going: once it isn't any more, its lines end 5 s on."""
        active = self.services.runs.active()
        for sub in self.services.bus.log_followers():
            following = sub.log_follow
            if not isinstance(following, Following):
                continue
            flt = following.filter
            if flt.span is None or flt.span[1] is not None or flt.run_id is None:
                continue
            if active is None or active.run_id != flt.run_id:
                flt.span = (flt.span[0], now_ns + RUN_MARGIN_NS)

    def _now_ns(self) -> int:
        return datetime_ns(self.services.clock.now())

    # --- Retention ------------------------------------------------------------------------------

    async def keep_tidy(self) -> None:
        """Background task: the retention pass at start-up, then every RETENTION_EVERY_S. A pass
        that fails is logged and tried again next time."""
        while True:
            try:
                await self.prune_once()
            except Exception:
                log.exception("logs: the retention pass failed")
            await self.services.clock.sleep(RETENTION_EVERY_S)

    async def prune_once(self, *, budget_bytes: int = BUDGET_BYTES) -> Pruned:
        """One retention pass. The files of a run still going are never deleted, nor the rotated
        s6-log files written since it started. Times against the files are real time: a run's
        start is its age on the services' clock, back from now."""
        store = self.services.store
        rows = await store.fetchall(
            "SELECT id, started_at FROM runs "
            "WHERE kind = 'run' AND (state IS NULL OR state <> 'ended')"
        )
        newest = await store.fetchval("SELECT coalesce(max(id), 0) FROM runs")
        protected = {int(row["id"]) for row in rows}
        active = self.services.runs.active()
        if active is not None:
            protected.add(active.run_id)
        wall_ns = self.wall_ns()
        world_ns = self._now_ns()
        keep_since: int | None = None
        for row in rows:
            age = max(0, world_ns - datetime_ns(datetime.fromisoformat(row["started_at"])))
            keep_since = wall_ns - age if keep_since is None else min(keep_since, wall_ns - age)
        return await asyncio.to_thread(
            prune,
            self.logs_dir,
            wall_ns,
            protected=frozenset(protected),
            newest_run=int(newest or 0),
            keep_since_ns=keep_since,
            budget_bytes=budget_bytes,
        )


def make_batches(
    filters: Sequence[LogFilter],
    lines: Sequence[Line],
    missed: Sequence[tuple[LogFile, int]],
    secrets: tuple[str, ...] = (),
) -> list[Batch | None]:
    """For each filter, its `log.lines`: the newest LOG_BATCH_MAX lines it matches, as LogLines
    (each line made once, shared between filters), and the count of the others plus the missed
    lines of the files it wants. None when there's nothing to send. Blocking: run it in a
    thread."""
    made: dict[str, dict[str, Any]] = {}
    batches: list[Batch | None] = []
    for flt in filters:
        picked: list[Line] = []
        dropped = sum(count for file, count in missed if flt.wants_file(file))
        for line in reversed(lines):
            if not flt.matches(line):
                continue
            if len(picked) < LOG_BATCH_MAX:
                picked.append(line)
            else:
                dropped += 1
        if not picked and not dropped:
            batches.append(None)
            continue
        api: list[dict[str, Any]] = []
        for line in reversed(picked):
            key = line.id
            if key not in made:
                made[key] = line.to_api(secrets)
            api.append(made[key])
        batches.append(Batch(api, dropped))
    return batches


def parse_follow(
    message: dict[str, Any],
) -> tuple[list[Source] | None, list[Level] | None, int | None, str | None, Any] | None:
    """A `logs.follow` message's filter and follow_id, or None when it doesn't fit."""
    follow_id = message.get("follow_id")
    if follow_id is not None and not (
        (isinstance(follow_id, int) and not isinstance(follow_id, bool))
        or (isinstance(follow_id, str) and len(follow_id) <= FOLLOW_ID_MAX)
    ):
        return None
    raw = message.get("filter")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        return None
    sources = _choices(raw.get("source"), SOURCES)
    levels = _choices(raw.get("level"), LEVELS)
    if sources is False or levels is False:
        return None
    run = raw.get("run")
    if run is not None and (not isinstance(run, int) or isinstance(run, bool) or run < 1):
        return None
    q = raw.get("q")
    if q is not None and (not isinstance(q, str) or len(q) > QUERY_MAX):
        return None
    return sources or None, levels or None, run, q or None, follow_id


def _choices(value: Any, allowed: tuple[str, ...]) -> list[Any] | None | bool:
    """A list of allowed strings (None for none given), or False when it isn't one."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > len(allowed):
        return False
    if not all(isinstance(item, str) and item in allowed for item in value):
        return False
    return list(value)
