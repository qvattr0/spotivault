"""webapi/usage.py: the usage log's rows, warnings, summaries, pruning and GET /api/webapi/usage.

Rows are written straight into `api_requests` here (or through UsageRecorder), so each test
says exactly what the log holds. The real port writing them is in test_webapi_client.py.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from contract import assert_response, assert_schema
from spotivault.clock import iso_ms
from spotivault.fake.clock import FakeClock
from spotivault.ports import OTHER, ApiScope
from spotivault.services import Services
from spotivault.store import Store
from spotivault.webapi.endpoints import (
    ME,
    MY_PLAYLISTS,
    PLAY,
    PLAYLIST,
    PLAYLIST_ITEMS,
    SAVED_TRACKS,
    TOKEN,
    Endpoint,
)
from spotivault.webapi.usage import (
    SUMMARY_DAY_KEY,
    Attempt,
    AttemptError,
    ScopeSummary,
    UsageRecorder,
    UsageService,
)

NOON = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
async def opened(services: Services) -> AsyncIterator[Services]:
    """The services with the store open, but no lifespan: no background task runs."""
    await services.store.open()
    yield services
    await services.store.close()


@pytest.fixture
def usage(opened: Services) -> UsageService:
    return opened.webapi_usage


@pytest.fixture
def recorder(opened: Services) -> UsageRecorder:
    return UsageRecorder(opened.store, opened.clock)


async def add(
    store: Store,
    at: datetime,
    endpoint: Endpoint,
    status: int | None,
    *,
    attempt: int = 1,
    latency_ms: int = 100,
    retry_after_s: int | None = None,
    scope: ApiScope = OTHER,
    error: AttemptError | None = None,
) -> None:
    """One `api_requests` row, as the real port writes it."""
    if status is None and error is None:
        error = "timeout"
    await store.execute(
        "INSERT INTO api_requests (at, endpoint_id, status, error, latency_ms, attempt, "
        "retry_after_s, scope_kind, scope_id) VALUES (?, "
        "(SELECT id FROM api_endpoints WHERE method = ? AND template = ?), ?, ?, ?, ?, ?, ?, ?)",
        (
            iso_ms(at),
            endpoint.method,
            endpoint.template,
            status,
            error,
            latency_ms,
            attempt,
            retry_after_s,
            scope.kind,
            scope.id,
        ),
    )


def attempt(
    clock: FakeClock,
    endpoint: Endpoint,
    status: int | None,
    *,
    retry_after_s: int | None = None,
    scope: ApiScope = OTHER,
) -> Attempt:
    return Attempt(
        at=clock.now(),
        endpoint=endpoint,
        status=status,
        error=None if status is not None else "network",
        latency_ms=120,
        attempt=1,
        retry_after_s=retry_after_s,
        scope=scope,
    )


async def warnings(store: Store) -> list[dict[str, Any]]:
    rows = await store.fetchall(
        "SELECT w.*, e.method || ' ' || e.template AS endpoint FROM api_warnings w "
        "LEFT JOIN api_endpoints e ON e.id = w.endpoint_id ORDER BY w.id"
    )
    return [dict(row) for row in rows]


# --- The live warnings ---------------------------------------------------------------------------


async def test_every_attempt_is_a_row(
    recorder: UsageRecorder, opened: Services, fake_clock: FakeClock
) -> None:
    scope = ApiScope("run", 3)
    await recorder.record(attempt(fake_clock, PLAY, 204, scope=scope))
    await recorder.record(attempt(fake_clock, ME, None))
    rows = await opened.store.fetchall("SELECT * FROM api_requests ORDER BY id")
    assert [
        (r["endpoint_id"], r["status"], r["error"], r["scope_kind"], r["scope_id"]) for r in rows
    ] == [(11, 204, None, "run", 3), (2, None, "network", "other", None)]
    assert rows[0]["at"] == iso_ms(fake_clock.now())


async def test_every_429_is_a_warning(
    recorder: UsageRecorder,
    opened: Services,
    fake_clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await recorder.record(attempt(fake_clock, SAVED_TRACKS, 429, retry_after_s=30))
    await recorder.record(attempt(fake_clock, ME, 429))
    rows = await warnings(opened.store)
    assert [(w["kind"], w["endpoint"], w["message"]) for w in rows] == [
        ("rate_limited", "GET /me/tracks", "Web API: 429 on GET /me/tracks, Retry-After 30 s"),
        ("rate_limited", "GET /me", "Web API: 429 on GET /me, no Retry-After"),
    ]
    assert "Web API: 429 on GET /me/tracks, Retry-After 30 s" in caplog.text


async def test_a_burst_warns_once_until_it_is_over(
    recorder: UsageRecorder, opened: Services, fake_clock: FakeClock
) -> None:
    await opened.settings.set_value("webapi_burst_threshold", 3)
    for _ in range(6):
        await recorder.record(attempt(fake_clock, MY_PLAYLISTS, 200))
    bursts = [w for w in await warnings(opened.store) if w["kind"] == "burst"]
    assert [w["message"] for w in bursts] == [
        "Web API: 4 requests in the last 30 s, over the warning threshold of 3"
    ]
    assert bursts[0]["endpoint_id"] is None
    # 31 s later the window is empty again; a new burst is a new warning.
    await fake_clock.advance(31)
    for _ in range(4):
        await recorder.record(attempt(fake_clock, MY_PLAYLISTS, 200))
    bursts = [w for w in await warnings(opened.store) if w["kind"] == "burst"]
    assert len(bursts) == 2


async def test_the_default_burst_threshold_is_30(
    recorder: UsageRecorder, opened: Services, fake_clock: FakeClock
) -> None:
    for _ in range(30):
        await recorder.record(attempt(fake_clock, MY_PLAYLISTS, 200))
    assert await warnings(opened.store) == []
    await recorder.record(attempt(fake_clock, MY_PLAYLISTS, 200))
    [burst] = await warnings(opened.store)
    assert burst["kind"] == "burst"


async def test_five_4xx_in_a_row_from_one_endpoint(
    recorder: UsageRecorder, opened: Services, fake_clock: FakeClock
) -> None:
    for _ in range(4):
        await recorder.record(attempt(fake_clock, PLAYLIST, 404))
    await recorder.record(attempt(fake_clock, ME, 404))  # another endpoint: its own count
    await recorder.record(attempt(fake_clock, PLAYLIST, 200))  # an answer ends the run
    assert await warnings(opened.store) == []

    for status in (403, 404, 429, 404, 404):  # a 429 neither counts nor ends the run
        await recorder.record(attempt(fake_clock, PLAYLIST_ITEMS, status))
    await recorder.record(attempt(fake_clock, PLAYLIST_ITEMS, None))  # nor does a timeout
    await recorder.record(attempt(fake_clock, PLAYLIST_ITEMS, 404))
    await recorder.record(attempt(fake_clock, PLAYLIST_ITEMS, 404))  # the sixth: no new warning
    repeated = [w for w in await warnings(opened.store) if w["kind"] == "repeated_4xx"]
    assert [(w["endpoint"], w["message"]) for w in repeated] == [
        (
            "GET /playlists/{id}/items",
            "Web API: 5 4xx answers in a row from GET /playlists/{id}/items (the last one 404)",
        )
    ]


async def test_a_usage_log_that_fails_never_raises(
    services: Services, fake_clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    closed = UsageRecorder(services.store, fake_clock)  # the store was never opened
    await closed.record(attempt(fake_clock, ME, 200))
    assert "the usage log couldn't record GET /me" in caplog.text


# --- Scopes ------------------------------------------------------------------------------------


async def test_finish_scope_counts_and_logs_the_summary_line(
    usage: UsageService,
    opened: Services,
    fake_clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    now = fake_clock.now()
    scope = ApiScope("refresh", 12)
    await add(opened.store, now, MY_PLAYLISTS, 200, scope=scope)
    await add(opened.store, now, SAVED_TRACKS, 429, retry_after_s=2, scope=scope)
    await add(opened.store, now, SAVED_TRACKS, 200, attempt=2, scope=scope)
    await add(opened.store, now, TOKEN, 200, scope=scope)
    await add(opened.store, now, ME, 200, scope=ApiScope("refresh", 13))
    summary = await usage.finish_scope(scope)
    assert summary == ScopeSummary(requests=4, retried=1, rate_limited=1)
    assert "Web API: 4 requests · 1 retried · 1 rate-limited (refresh:12)" in caplog.text
    assert await usage.finish_scope(ApiScope("run", 99)) == ScopeSummary(0, 0, 0)


async def test_a_scope_over_twice_the_7_day_median_is_a_warning(
    usage: UsageService, opened: Services, fake_clock: FakeClock
) -> None:
    now = fake_clock.now()
    store = opened.store

    async def scope_with(scope_id: int, count: int, at: datetime) -> ApiScope:
        scope = ApiScope("refresh", scope_id)
        for _ in range(count):
            await add(store, at, MY_PLAYLISTS, 200, scope=scope)
        return scope

    await scope_with(1, 100, now - timedelta(days=8))  # too old to count
    await scope_with(2, 3, now - timedelta(days=2))
    await scope_with(3, 5, now - timedelta(days=1))
    # Only two earlier refreshes: too few to compare.
    await usage.finish_scope(await scope_with(4, 50, now))
    assert await warnings(store) == []
    # Earlier ones: 3, 5, 50 → median 5. Ten is not more than twice that.
    await usage.finish_scope(await scope_with(5, 10, now))
    assert await warnings(store) == []
    # Earlier ones: 3, 5, 10, 50 → median 7.5. Sixteen is more than twice that.
    await usage.finish_scope(await scope_with(6, 16, now))
    [warning] = await warnings(store)
    assert warning["kind"] == "above_median"
    assert warning["message"] == (
        "Web API: refresh:6 made 16 requests, more than twice the 7-day median of 7.5"
    )
    assert (warning["scope_kind"], warning["scope_id"]) == ("refresh", 6)
    # A run is compared with runs only: there are none yet.
    run = ApiScope("run", 1)
    for _ in range(40):
        await add(store, now, MY_PLAYLISTS, 200, scope=run)
    await usage.finish_scope(run)
    assert len(await warnings(store)) == 1


async def test_the_rolling_30_s_counter(
    usage: UsageService, opened: Services, fake_clock: FakeClock
) -> None:
    now = fake_clock.now()
    await add(opened.store, now - timedelta(seconds=31), ME, 200)
    await add(opened.store, now - timedelta(seconds=29), ME, 200)
    await add(opened.store, now, PLAY, 204)
    assert await usage.requests_last_30s() == 2


# --- GET /api/webapi/usage ---------------------------------------------------------------------


async def seed_two_days(store: Store) -> None:
    day1 = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
    day2 = datetime(2026, 11, 15, 1, 0, tzinfo=UTC)
    await add(store, datetime(2026, 11, 13, 23, 59, tzinfo=UTC), ME, 200)  # before the period
    await add(store, day1, ME, 200, latency_ms=100)
    await add(store, day1 + timedelta(minutes=1), ME, 503, latency_ms=300)
    await add(store, day1 + timedelta(minutes=2), ME, 200, attempt=2, latency_ms=200)
    await add(store, day1 + timedelta(hours=1), ME, None, latency_ms=20000)  # a timeout
    refresh = ApiScope("refresh", 4)
    await add(store, day2, PLAYLIST_ITEMS, 429, retry_after_s=30, scope=refresh)
    await add(store, day2, PLAYLIST_ITEMS, 403, attempt=1, latency_ms=50, scope=refresh)
    await add(store, day2, PLAYLIST_ITEMS, 200, attempt=2, latency_ms=150, scope=refresh)
    await add(store, day2 + timedelta(hours=1), PLAY, 204, scope=ApiScope("run", 9))
    await add(store, day2 + timedelta(hours=2), SAVED_TRACKS, 429, retry_after_s=5)
    await add(store, day2 + timedelta(hours=3), TOKEN, 200, scope=ApiScope("setup"))


async def test_usage_per_endpoint_per_day(
    usage: UsageService, opened: Services, fake_clock: FakeClock
) -> None:
    fake_clock.set_now(NOON)
    await seed_two_days(opened.store)
    await opened.store.execute(
        "INSERT INTO api_warnings (at, kind, message) VALUES (?, 'burst', 'old'), "
        "(?, 'burst', 'Web API: 31 requests in the last 30 s, over the warning threshold of 30')",
        ("2026-11-10T00:00:00.000Z", "2026-11-15T01:00:00.000Z"),
    )
    report = await usage.usage(2)
    body = report.model_dump(mode="json", by_alias=True)
    assert_schema("WebApiUsage", body)
    assert (body["days"], body["from"], body["to"]) == (2, "2026-11-14", "2026-11-15")
    assert body["totals"] == {
        "requests": 10,
        "retried": 2,
        "rate_limited": 2,
        "errors_4xx": 3,
        "errors_5xx": 1,
    }
    by_day = {(d["day"], d["method"] + " " + d["endpoint"]): d for d in body["by_day"]}
    assert list(by_day) == [
        ("2026-11-14", "GET /me"),
        ("2026-11-15", "POST /api/token"),
        ("2026-11-15", "GET /playlists/{id}/items"),
        ("2026-11-15", "GET /me/tracks"),
        ("2026-11-15", "PUT /me/player/play"),
    ]
    me = by_day[("2026-11-14", "GET /me")]
    assert me == {
        "day": "2026-11-14",
        "method": "GET",
        "endpoint": "/me",
        "lane": "catalog",
        "requests": 4,
        "retried": 1,
        "rate_limited": 0,
        "status_2xx": 2,
        "status_4xx": 0,
        "status_5xx": 1,
        "p50_ms": 200,  # answered attempts only: 100, 200, 300
        "p95_ms": 300,
    }
    items = by_day[("2026-11-15", "GET /playlists/{id}/items")]
    assert (items["status_4xx"], items["rate_limited"], items["retried"]) == (2, 1, 1)
    assert body["rate_limits"] == [
        {
            "at": "2026-11-15T03:00:00Z",
            "method": "GET",
            "endpoint": "/me/tracks",
            "retry_after_s": 5,
            "scope": "other",
        },
        {
            "at": "2026-11-15T01:00:00Z",
            "method": "GET",
            "endpoint": "/playlists/{id}/items",
            "retry_after_s": 30,
            "scope": "refresh:4",
        },
    ]
    assert [w["kind"] for w in body["warnings"]] == ["burst"]


async def test_usage_of_an_empty_log(usage: UsageService) -> None:
    body = (await usage.usage(7)).model_dump(mode="json", by_alias=True)
    assert_schema("WebApiUsage", body)
    assert body["totals"]["requests"] == 0 and body["by_day"] == []
    assert (body["from"], body["to"]) == ("2026-11-09", "2026-11-15")


async def test_a_day_of_timeouts_has_no_latency(
    usage: UsageService, opened: Services, fake_clock: FakeClock
) -> None:
    await add(opened.store, fake_clock.now(), ME, None, latency_ms=20000)
    [row] = (await usage.usage(1)).by_day
    assert (row.requests, row.p50_ms, row.p95_ms) == (1, None, None)


async def test_the_endpoint(
    client: httpx.AsyncClient, services: Services, fake_clock: FakeClock
) -> None:
    fake_clock.set_now(NOON)
    response = await client.get("/api/webapi/usage")
    assert response.status_code == 200
    assert_response(response, "/api/webapi/usage")
    assert response.json()["days"] == 7
    await seed_two_days(services.store)
    response = await client.get("/api/webapi/usage", params={"days": 2})
    assert response.status_code == 200
    assert_response(response, "/api/webapi/usage")
    assert response.json()["totals"]["requests"] == 10
    assert "{id}" in response.text
    assert (await client.get("/api/webapi/usage", params={"days": 91})).status_code == 422


# --- The daily upkeep --------------------------------------------------------------------------


async def meta_day(store: Store) -> str | None:
    return await store.fetchval("SELECT value FROM meta WHERE key = ?", (SUMMARY_DAY_KEY,))


async def test_daily_summary_lines_and_pruning(
    usage: UsageService,
    opened: Services,
    fake_clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    store = opened.store
    fake_clock.set_now(datetime(2026, 11, 15, 0, 1, tzinfo=UTC))
    await add(store, datetime(2026, 8, 7, tzinfo=UTC), ME, 200)  # over 90 days old
    await add(store, datetime(2026, 11, 13, 5, tzinfo=UTC), MY_PLAYLISTS, 200, latency_ms=210)
    await add(store, datetime(2026, 11, 14, 5, tzinfo=UTC), ME, 200, latency_ms=90)
    await add(store, datetime(2026, 11, 14, 6, tzinfo=UTC), ME, 429, retry_after_s=3)
    await add(store, datetime(2026, 11, 14, 6, 1, tzinfo=UTC), ME, 200, attempt=2)
    await add(store, datetime(2026, 11, 15, 0, 0, 30, tzinfo=UTC), ME, 200)  # today: not over
    await store.execute(
        "INSERT INTO api_warnings (at, kind, message) VALUES ('2026-08-07T00:00:00.000Z', "
        "'burst', 'old')"
    )
    await usage.maintain_once()
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Web API on")]
    assert lines == [
        "Web API on 2026-11-13: GET /me/playlists 1 requests · 0 retried · 0 rate-limited · "
        "p95 210 ms",
        "Web API on 2026-11-14: GET /me 3 requests · 1 retried · 1 rate-limited · p95 100 ms",
    ]
    assert await meta_day(store) == "2026-11-14"
    assert await store.fetchval("SELECT count(*) FROM api_requests") == 5
    assert await store.fetchval("SELECT count(*) FROM api_warnings") == 0
    assert "removed 1 usage-log rows older than 90 days" in caplog.text

    caplog.clear()
    await usage.maintain_once()  # the same day again: nothing new to say
    assert not [r for r in caplog.records if r.getMessage().startswith("Web API on")]

    fake_clock.set_now(datetime(2026, 11, 16, 0, 1, tzinfo=UTC))
    await usage.maintain_once()
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Web API on")]
    assert lines == [
        "Web API on 2026-11-15: GET /me 1 requests · 0 retried · 0 rate-limited · p95 100 ms"
    ]
    assert await meta_day(store) == "2026-11-15"


async def test_the_upkeep_runs_at_start_up_and_after_each_midnight(
    usage: UsageService,
    opened: Services,
    fake_clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    store = opened.store
    task = asyncio.ensure_future(usage.maintain())
    try:
        await wait_for_day(store, "2026-11-14")  # the clock starts at 2026-11-15 00:00 UTC
        await add(store, fake_clock.now() + timedelta(hours=3), PLAY, 204)
        await wait_for_sleep(fake_clock)
        await fake_clock.advance(24 * 3600 + 60)  # one minute past the next midnight
        await wait_for_day(store, "2026-11-15")
        assert "Web API on 2026-11-15: PUT /me/player/play 1 requests" in caplog.text
        assert not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def wait_for_sleep(clock: FakeClock) -> None:
    for _ in range(1000):
        if clock.sleepers:
            return
        await asyncio.sleep(0.002)
    raise AssertionError("the upkeep never went to sleep")


async def wait_for_day(store: Store, day: str) -> None:
    for _ in range(1000):
        if await meta_day(store) == day:
            return
        await asyncio.sleep(0.002)
    raise AssertionError(f"the summary day never reached {day}")


def test_it_is_registered_as_a_background_task(services: Services) -> None:
    assert "webapi.usage" in [hook.name for hook in services._background]
