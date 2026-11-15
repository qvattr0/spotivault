"""The Web API usage log: every request, the warnings, the summaries (plan § Web API request
scheduler and usage log; design.md § Requests; contracts/schema.sql `api_requests`).

Owner: webapi-core. Frozen for other modules: `ScopeSummary` (with `line()`), and
`UsageService.finish_scope`, `requests_last_30s` and `usage`.

**The rows** (`UsageRecorder.record`, from the real port): one `api_requests` row per HTTP
attempt, retries included: when it was sent, the endpoint (`api_endpoints.id` of its template, so
no id or token can be stored), status or error (`timeout`, `network`, `invalid_grant`), latency,
attempt number, Retry-After, and the scope it counts against. Kept 90 days.

**The warnings**, each a WARNING line in the controller log and an `api_warnings` row
(migration 002), with endpoint templates only:
- `rate_limited`: every 429, with its endpoint and Retry-After ("Web API: 429 on GET /me/tracks,
  Retry-After 30 s").
- `burst`: more than the `webapi_burst_threshold` setting (default 30; settings.DEFAULTS) requests
  in the rolling 30 s window, the window Spotify enforces its limits over. Once per burst, not per
  request: it can warn again once the count has fallen back to the threshold.
- `repeated_4xx`: five 4xx answers in a row from one endpoint (404 and 403 included: a run of them
  can look like scraping). Once per run of them; any other answer from that endpoint ends the
  run. A 429 is left out: it has its own warning, and it neither counts nor ends a run.
- `above_median`: a refresh or run whose request count is more than twice the median of the
  same kind's scopes over the last 7 days (`finish_scope`). It needs MEDIAN_MIN_SCOPES earlier
  ones to compare.

**The summary lines:** `finish_scope` logs one per refresh and per run, "Web API: 112 requests ·
2 retried · 0 rate-limited". `maintain` logs one line per endpoint for each UTC day once it's
over ("Web API on 2026-11-14: GET /me/playlists 12 requests · 0 retried · 0 rate-limited ·
p95 210 ms"), remembering the last day it summarized in the `meta` key `webapi_summary_day`, and
deletes `api_requests` and `api_warnings` rows older than 90 days.

**Latency percentiles** count answered attempts only: a timeout's latency is the timeout, not
Spotify's. With none answered, p50 and p95 are null.

**Fake mode** has no rows: the fake port doesn't write any, so every count is 0.
"""

import json
import logging
import math
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from spotivault.api.models import WebApiUsage
from spotivault.clock import iso_ms
from spotivault.ports import ApiScope, Clock
from spotivault.settings import DEFAULTS
from spotivault.store import Store
from spotivault.webapi.endpoints import Endpoint

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

KEEP_DAYS = 90
WINDOW_S = 30  # the rolling window Spotify enforces its limits over
REPEATED_4XX = 5
SUMMARY_DAY_KEY = "webapi_summary_day"  # meta: the last UTC day summarized, "2026-11-14"
BURST_THRESHOLD_KEY = "webapi_burst_threshold"  # settings; default in settings.DEFAULTS
MEDIAN_DAYS = 7
MEDIAN_MIN_SCOPES = 3  # earlier refreshes (or runs) needed before `above_median` can apply
MAINTAIN_AFTER_MIDNIGHT_S = 60  # the daily pass runs this long after 00:00 UTC

type AttemptError = Literal["timeout", "network", "invalid_grant"]
type WarningKind = Literal["rate_limited", "burst", "repeated_4xx", "above_median"]


@dataclass(frozen=True, slots=True)
class ScopeSummary:
    """A refresh's or a run's Web API counts: `catalog_refreshes.api_*` and `runs.api_*`."""

    requests: int  # HTTP attempts, retries included
    retried: int  # attempts with attempt > 1
    rate_limited: int  # 429 answers

    def line(self) -> str:
        """The summary line: "Web API: 112 requests · 2 retried · 0 rate-limited"."""
        return (
            f"Web API: {self.requests} requests · {self.retried} retried · "
            f"{self.rate_limited} rate-limited"
        )


@dataclass(frozen=True, slots=True)
class Attempt:
    """One HTTP attempt, as the real port records it."""

    at: datetime  # when it was sent
    endpoint: Endpoint
    status: int | None  # None for a timeout or a network error
    error: AttemptError | None  # 'invalid_grant' goes with status 400
    latency_ms: int
    attempt: int  # 1, then 2… for retries of the same call
    retry_after_s: int | None  # a 429's Retry-After
    scope: ApiScope


@dataclass(frozen=True, slots=True)
class UsageWarning:
    """One warning, as logged and stored in `api_warnings`."""

    kind: WarningKind
    message: str  # endpoint templates only
    endpoint: Endpoint | None  # None for burst and above_median
    scope: ApiScope | None


class UsageRecorder:
    """Writes the rows and raises the live warnings (429, burst, repeated 4xx). Used by the real
    port only; it lives as long as the port."""

    def __init__(self, store: Store, clock: Clock) -> None:
        self.store = store
        self.clock = clock
        self._in_burst = False  # warned about the current burst already
        self._4xx_in_a_row: dict[str, int] = {}  # endpoint name → 4xx answers in a row

    async def record(self, attempt: Attempt) -> None:
        """Writes one `api_requests` row, then checks the live warnings. Never raises: a usage
        log that can't be written is logged, and the request's answer still counts."""
        try:
            await self._record(attempt)
        except Exception as exc:
            log.warning(
                "Web API: the usage log couldn't record %s (%s: %s)",
                attempt.endpoint.name,
                type(exc).__name__,
                exc,
            )

    async def _record(self, attempt: Attempt) -> None:
        endpoint = attempt.endpoint
        window_start = iso_ms(self.clock.now() - timedelta(seconds=WINDOW_S))
        row = (
            iso_ms(attempt.at),
            endpoint.method,
            endpoint.template,
            attempt.status,
            attempt.error,
            attempt.latency_ms,
            attempt.attempt,
            attempt.retry_after_s,
            attempt.scope.kind,
            attempt.scope.id,
        )

        def write(conn: sqlite3.Connection) -> tuple[int, int]:
            conn.execute(
                "INSERT INTO api_requests (at, endpoint_id, status, error, latency_ms, attempt, "
                "retry_after_s, scope_kind, scope_id) VALUES (?, "
                "(SELECT id FROM api_endpoints WHERE method = ? AND template = ?), "
                "?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            in_window = conn.execute(
                "SELECT count(*) FROM api_requests WHERE at > ?", (window_start,)
            ).fetchone()[0]
            return in_window, _burst_threshold(conn)

        in_window, threshold = await self.store.transaction(write)

        warnings: list[UsageWarning] = []
        if attempt.status == 429:
            after = (
                f"Retry-After {attempt.retry_after_s} s"
                if attempt.retry_after_s is not None
                else "no Retry-After"
            )
            warnings.append(
                UsageWarning(
                    "rate_limited",
                    f"Web API: 429 on {endpoint.name}, {after}",
                    endpoint,
                    attempt.scope,
                )
            )
        if in_window > threshold and not self._in_burst:
            self._in_burst = True
            warnings.append(
                UsageWarning(
                    "burst",
                    f"Web API: {in_window} requests in the last {WINDOW_S} s, over the warning "
                    f"threshold of {threshold}",
                    None,
                    attempt.scope,
                )
            )
        elif in_window <= threshold:
            self._in_burst = False
        repeated = self._count_4xx(endpoint, attempt.status)
        if repeated == REPEATED_4XX:
            warnings.append(
                UsageWarning(
                    "repeated_4xx",
                    f"Web API: {REPEATED_4XX} 4xx answers in a row from {endpoint.name} "
                    f"(the last one {attempt.status})",
                    endpoint,
                    attempt.scope,
                )
            )
        if warnings:
            await write_warnings(self.store, self.clock, warnings)

    def _count_4xx(self, endpoint: Endpoint, status: int | None) -> int:
        """The endpoint's 4xx answers in a row, this one included (see the module docstring)."""
        if status is None or status == 429:
            return 0  # no answer, or a 429: the run neither grows nor ends
        if 400 <= status < 500:
            count = self._4xx_in_a_row.get(endpoint.name, 0) + 1
            self._4xx_in_a_row[endpoint.name] = count
            return count
        self._4xx_in_a_row.pop(endpoint.name, None)
        return 0


class UsageService:
    """Reading the usage log, and its upkeep. Built by services.py as `services.webapi_usage`."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        services.add_background("webapi.usage", self.maintain)

    async def finish_scope(self, scope: ApiScope) -> ScopeSummary:
        """Called once when a refresh or a run ends (catalog-library; S6). Counts the scope's
        rows, logs its summary line, raises `above_median` if it applies, and returns the counts
        for `catalog_refreshes` or `runs`. A scope with no rows (fake mode) is all zeros."""
        store = self.services.store
        row = await store.fetchone(
            "SELECT count(*) AS requests, coalesce(sum(attempt > 1), 0) AS retried, "
            "coalesce(sum(status = 429), 0) AS rate_limited "
            "FROM api_requests WHERE scope_kind = ? AND scope_id IS ?",
            (scope.kind, scope.id),
        )
        assert row is not None  # an aggregate always has one row
        summary = ScopeSummary(
            requests=row["requests"], retried=row["retried"], rate_limited=row["rate_limited"]
        )
        log.info("%s (%s)", summary.line(), scope_label(scope))
        if scope.kind in ("refresh", "run") and summary.requests > 0:
            await self._check_median(scope, summary.requests)
        return summary

    async def requests_last_30s(self) -> int:
        """Rows sent in the last 30 s: the rolling counter, for S6's run metrics."""
        since = iso_ms(self.services.clock.now() - timedelta(seconds=WINDOW_S))
        count = await self.services.store.fetchval(
            "SELECT count(*) FROM api_requests WHERE at > ?", (since,)
        )
        return int(count or 0)

    async def usage(self, days: int) -> WebApiUsage:
        """GET /api/webapi/usage?days=: the last `days` UTC days, today included. Totals per
        endpoint template per day (with p50 and p95 latency), every 429 newest first (`scope`
        is `run:<id>`, `refresh:<id>`, `setup` or `other`), and the warnings in the period."""
        if not 1 <= days <= KEEP_DAYS:
            raise ValueError(f"days must be 1 to {KEEP_DAYS}")
        today = self.services.clock.now().astimezone(UTC).date()
        first = today - timedelta(days=days - 1)
        since = _day_start(first)
        # The whole report is built on the database thread: up to 90 days of rows.
        report = await self.services.store.call(lambda conn: _usage_report(conn, since))
        report.update({"days": days, "from": first.isoformat(), "to": today.isoformat()})
        return WebApiUsage.model_validate(report)

    async def maintain(self) -> None:
        """Background task: once per UTC day (and at start-up), the daily summary lines for days
        not summarized yet, and the 90-day pruning. Sleeps with services.clock. A pass that
        fails is logged and tried again the next day: it never stops the controller."""
        clock = self.services.clock
        while True:
            try:
                await self.maintain_once()
            except Exception:
                log.exception("Web API: the usage log's daily upkeep failed")
            now = clock.now().astimezone(UTC)
            next_day = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), UTC)
            wake = next_day + timedelta(seconds=MAINTAIN_AFTER_MIDNIGHT_S)
            await clock.sleep((wake - now).total_seconds())

    async def maintain_once(self) -> None:
        """One pass of `maintain`: summary lines for the days that are over and weren't
        summarized yet, then the pruning."""
        store = self.services.store
        now = self.services.clock.now().astimezone(UTC)
        today = now.date()
        stamp = iso_ms(now)
        cutoff = iso_ms(now - timedelta(days=KEEP_DAYS))
        oldest = today - timedelta(days=KEEP_DAYS)

        def summarize_and_prune(conn: sqlite3.Connection) -> tuple[list[str], int]:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (SUMMARY_DAY_KEY,)
            ).fetchone()
            last = _parse_day(row["value"]) if row is not None else None
            first = max(oldest, last + timedelta(days=1)) if last is not None else oldest
            lines = _day_summaries(conn, _day_start(first), _day_start(today))
            yesterday = (today - timedelta(days=1)).isoformat()
            conn.execute(
                "INSERT INTO meta (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (SUMMARY_DAY_KEY, yesterday, stamp),
            )
            pruned = conn.execute("DELETE FROM api_requests WHERE at < ?", (cutoff,)).rowcount
            conn.execute("DELETE FROM api_warnings WHERE at < ?", (cutoff,))
            return lines, pruned

        lines, pruned = await store.transaction(summarize_and_prune)
        for line in lines:
            log.info("%s", line)
        if pruned:
            log.info("Web API: removed %d usage-log rows older than %d days", pruned, KEEP_DAYS)

    # --- Inside --------------------------------------------------------------------------------

    async def _check_median(self, scope: ApiScope, requests: int) -> None:
        """`above_median`: more than twice the median of the same kind's other scopes with
        requests in the last 7 days."""
        since = iso_ms(self.services.clock.now() - timedelta(days=MEDIAN_DAYS))
        rows = await self.services.store.fetchall(
            "SELECT scope_id, count(*) AS n FROM api_requests "
            "WHERE scope_kind = ? AND scope_id IS NOT ? AND at >= ? GROUP BY scope_id",
            (scope.kind, scope.id, since),
        )
        counts = [row["n"] for row in rows]
        if len(counts) < MEDIAN_MIN_SCOPES:
            return
        median = statistics.median(counts)
        if requests <= 2 * median:
            return
        warning = UsageWarning(
            "above_median",
            f"Web API: {scope_label(scope)} made {requests} requests, more than twice the "
            f"{MEDIAN_DAYS}-day median of {median:g}",
            None,
            scope,
        )
        await write_warnings(self.services.store, self.services.clock, [warning])


# --- Shared ----------------------------------------------------------------------------------


async def write_warnings(store: Store, clock: Clock, warnings: list[UsageWarning]) -> None:
    """Logs each warning and stores it in `api_warnings`."""
    at = iso_ms(clock.now())
    for warning in warnings:
        log.warning("%s", warning.message)
    rows = [
        (
            at,
            w.kind,
            w.message,
            w.endpoint.method if w.endpoint else None,
            w.endpoint.template if w.endpoint else None,
            w.scope.kind if w.scope else None,
            w.scope.id if w.scope else None,
        )
        for w in warnings
    ]

    def write(conn: sqlite3.Connection) -> None:
        conn.executemany(
            "INSERT INTO api_warnings (at, kind, message, endpoint_id, scope_kind, scope_id) "
            "VALUES (?, ?, ?, (SELECT id FROM api_endpoints WHERE method = ? AND template = ?), "
            "?, ?)",
            rows,
        )

    await store.transaction(write)


def scope_label(scope: ApiScope) -> str:
    """How a scope is named in messages and GET /api/webapi/usage: "refresh:12", "run:3",
    "setup", "other"."""
    if scope.id is None:
        return scope.kind
    return f"{scope.kind}:{scope.id}"


def _burst_threshold(conn: sqlite3.Connection) -> int:
    """The `webapi_burst_threshold` setting, or its default when unset or unusable."""
    default = int(DEFAULTS[BURST_THRESHOLD_KEY])
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (BURST_THRESHOLD_KEY,)
    ).fetchone()
    if row is None:
        return default
    try:
        value = json.loads(row["value"])
    except ValueError:
        return default
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


def _day_start(day: date) -> str:
    """00:00 UTC of `day`, in the database's time format."""
    return f"{day.isoformat()}T00:00:00.000Z"


def _parse_day(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _percentile(values: list[int], fraction: float) -> int | None:
    """Nearest-rank percentile of `values` (sorted here), or None when there are none."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


@dataclass(slots=True)
class _Group:
    """One endpoint on one day, while adding its rows up."""

    day: str
    method: str
    template: str
    lane: str
    requests: int = 0
    retried: int = 0
    rate_limited: int = 0
    status_2xx: int = 0
    status_4xx: int = 0
    status_5xx: int = 0
    latencies: list[int] | None = None

    def add(self, status: int | None, attempt: int, latency_ms: int) -> None:
        self.requests += 1
        if attempt > 1:
            self.retried += 1
        if status is None:
            return  # a timeout or network error: no status, and no latency for the percentiles
        if status == 429:
            self.rate_limited += 1
        if 200 <= status < 300:
            self.status_2xx += 1
        elif 400 <= status < 500:
            self.status_4xx += 1  # 429s included: they're 4xx answers too
        elif 500 <= status < 600:
            self.status_5xx += 1
        if self.latencies is None:
            self.latencies = []
        self.latencies.append(latency_ms)


def _groups(conn: sqlite3.Connection, since: str, until: str | None) -> list[_Group]:
    """Every endpoint's rows per UTC day from `since` (until `until`, when given), in day and
    endpoint order. Runs on the database thread."""
    sql = (
        "SELECT substr(r.at, 1, 10) AS day, e.id AS endpoint_id, e.method, e.template, e.lane, "
        "r.status, r.attempt, r.latency_ms "
        "FROM api_requests r JOIN api_endpoints e ON e.id = r.endpoint_id WHERE r.at >= ?"
    )
    params: tuple[str, ...] = (since,)
    if until is not None:
        sql += " AND r.at < ?"
        params = (since, until)
    groups: dict[tuple[str, int], _Group] = {}
    for row in conn.execute(sql, params):
        key = (row["day"], row["endpoint_id"])
        group = groups.get(key)
        if group is None:
            group = _Group(row["day"], row["method"], row["template"], row["lane"])
            groups[key] = group
        group.add(row["status"], row["attempt"], row["latency_ms"])
    return [groups[key] for key in sorted(groups)]


def _day_summaries(conn: sqlite3.Connection, since: str, until: str) -> list[str]:
    """The daily summary lines for the days from `since` up to `until` (not included)."""
    lines = []
    for group in _groups(conn, since, until):
        p95 = _percentile(group.latencies or [], 0.95)
        latency = f" · p95 {p95} ms" if p95 is not None else ""
        lines.append(
            f"Web API on {group.day}: {group.method} {group.template} {group.requests} requests "
            f"· {group.retried} retried · {group.rate_limited} rate-limited{latency}"
        )
    return lines


def _usage_report(conn: sqlite3.Connection, since: str) -> dict[str, Any]:
    """GET /api/webapi/usage's totals, by_day, rate_limits and warnings, from `since` on, as
    plain data. Runs on the database thread."""
    groups = _groups(conn, since, None)
    by_day = [
        {
            "day": g.day,
            "method": g.method,
            "endpoint": g.template,
            "lane": g.lane,
            "requests": g.requests,
            "retried": g.retried,
            "rate_limited": g.rate_limited,
            "status_2xx": g.status_2xx,
            "status_4xx": g.status_4xx,
            "status_5xx": g.status_5xx,
            "p50_ms": _percentile(g.latencies or [], 0.50),
            "p95_ms": _percentile(g.latencies or [], 0.95),
        }
        for g in groups
    ]
    totals = {
        "requests": sum(g.requests for g in groups),
        "retried": sum(g.retried for g in groups),
        "rate_limited": sum(g.rate_limited for g in groups),
        "errors_4xx": sum(g.status_4xx for g in groups),
        "errors_5xx": sum(g.status_5xx for g in groups),
    }
    rate_limits = [
        {
            "at": row["at"],
            "method": row["method"],
            "endpoint": row["template"],
            "retry_after_s": row["retry_after_s"],
            "scope": scope_label(ApiScope(row["scope_kind"], row["scope_id"])),
        }
        for row in conn.execute(
            "SELECT r.at, e.method, e.template, r.retry_after_s, r.scope_kind, r.scope_id "
            "FROM api_requests r JOIN api_endpoints e ON e.id = r.endpoint_id "
            "WHERE r.status = 429 AND r.at >= ? ORDER BY r.at DESC, r.id DESC",
            (since,),
        )
    ]
    warnings = [
        {"at": row["at"], "kind": row["kind"], "message": row["message"]}
        for row in conn.execute(
            "SELECT at, kind, message FROM api_warnings WHERE at >= ? ORDER BY at DESC, id DESC",
            (since,),
        )
    ]
    return {"totals": totals, "by_day": by_day, "rate_limits": rate_limits, "warnings": warnings}
