"""metrics.py: the 60 s run metrics sampler (S6, history-files-metrics; plan § Long runs).

The sampler reads /proc, so these tests point it at a fake /proc tree, with the same files a real
one has for the processes they name. The run engine is replaced by the two calls the sampler
makes on it (`active`, `recorder_pid`), and the clock is the fake one.
"""

import asyncio
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI

from spotivault.clock import iso_ms
from spotivault.fake.clock import FakeClock
from spotivault.metrics import SAMPLE_INTERVAL_S, MetricsSample
from spotivault.services import Services

CLOCK_TICKS = 100  # the value Linux uses; set on the service so the tests don't depend on it


def make_proc(
    root: Path,
    pid: int,
    comm: str,
    *,
    rss_kb: int | None,
    ticks: tuple[int, int] = (0, 0),
    exe: Path | None = None,
) -> None:
    """A process in the fake /proc: its comm, stat (with utime and stime), status and exe."""
    base = root / str(pid)
    base.mkdir(parents=True, exist_ok=True)
    (base / "comm").write_text(comm + "\n", encoding="utf-8")
    utime, stime = ticks
    # Fields 3 to 13 are placeholders; utime and stime are fields 14 and 15, as in the kernel.
    stat = f"{pid} ({comm}) S " + " ".join(["0"] * 10) + f" {utime} {stime} 0 0 20 0"
    (base / "stat").write_text(stat + "\n", encoding="utf-8")
    status = f"Name:\t{comm}\n"
    if rss_kb is not None:
        status += f"VmRSS:\t{rss_kb} kB\n"
    (base / "status").write_text(status, encoding="utf-8")
    if exe is not None and not (base / "exe").is_symlink():
        os.symlink(exe, base / "exe")


def kib(value: int) -> int:
    return value * 1024


async def new_run(services: Services) -> int:
    """A run row, for run_metrics' foreign key. Finished, so several can exist: the one-active
    index allows only one going."""
    cursor = await services.store.execute(
        "INSERT INTO runs (kind, trigger, state, outcome, started_at, ended_at) "
        "VALUES ('run', 'run_now', 'ended', 'completed', '2026-11-15T00:00:00.000Z', "
        "'2026-11-15T00:00:00.000Z')"
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def stored(services: Services) -> list[sqlite3.Row]:
    return await services.store.fetchall("SELECT * FROM run_metrics ORDER BY at")


async def until_rows(services: Services, count: int) -> None:
    """Waits, in real time, until run_metrics has `count` rows: the loop runs the background
    task the fake clock woke, and its write is on the database thread."""

    async def current() -> int:
        return int(await services.store.fetchval("SELECT count(*) FROM run_metrics"))

    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while await current() < count:
        if loop.time() > deadline:
            raise AssertionError(f"fewer than {count} samples")
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.02)  # the task has gone back to sleeping on the fake clock


def going(services: Services, run_id: int | None, recorder: int | None = None) -> None:
    """Makes the run engine report `run_id` going (None: idle) and `recorder` as spytifyd."""
    active = None if run_id is None else SimpleNamespace(run_id=run_id)
    services.runs.active = lambda: active  # type: ignore[method-assign]
    services.runs.recorder_pid = lambda: recorder  # type: ignore[method-assign]


@pytest.fixture
def proc(tmp_path: Path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    return root


@pytest.fixture
def sampler(services: Services, proc: Path) -> None:
    """The metrics service reads the fake /proc, with the clock's ticks fixed."""
    services.metrics.proc_root = proc
    services.metrics.clk_tck = CLOCK_TICKS


# --- When it samples


async def test_a_sample_every_60_s_while_a_run_is_going(
    running_app: FastAPI, services: Services, fake_clock: FakeClock, sampler: None
) -> None:
    run_id = await new_run(services)
    going(services, run_id)
    assert SAMPLE_INTERVAL_S == 60.0
    await fake_clock.advance(60)
    await until_rows(services, 1)
    await fake_clock.advance(60)
    await until_rows(services, 2)
    rows = await stored(services)
    assert [row["run_id"] for row in rows] == [run_id, run_id]
    assert rows[0]["at"] != rows[1]["at"]


async def test_nothing_is_sampled_when_idle(
    running_app: FastAPI, services: Services, fake_clock: FakeClock, sampler: None
) -> None:
    going(services, None)
    await fake_clock.advance(3 * 60)
    await asyncio.sleep(0.05)  # the wake-ups have run
    assert await stored(services) == []


async def test_a_failing_sample_is_skipped_and_the_task_lives_on(
    running_app: FastAPI,
    services: Services,
    fake_clock: FakeClock,
    sampler: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = await new_run(services)
    going(services, run_id)

    async def broken(_: int) -> MetricsSample:
        raise RuntimeError("the sampler broke")

    monkeypatch.setattr(services.metrics, "sample", broken)
    await fake_clock.advance(60)
    await asyncio.sleep(0.05)
    assert services.fatal_errors == [] and await stored(services) == []

    monkeypatch.undo()
    await fake_clock.advance(60)
    await until_rows(services, 1)
    assert services.fatal_errors == []


# --- What it reads


async def test_the_spotify_spytifyd_and_controller_rss_and_cpu(
    running_app: FastAPI, services: Services, fake_clock: FakeClock, sampler: None, proc: Path
) -> None:
    spotify = services.config.spotify_dir
    make_proc(proc, 100, "spotify", rss_kb=1000, ticks=(1000, 0))
    make_proc(proc, 101, "Web Content", rss_kb=2000, exe=spotify / "spotify")
    make_proc(proc, 102, "bash", rss_kb=9999)  # not Spotify: not counted
    make_proc(proc, 200, "spytifyd", rss_kb=3000)
    make_proc(proc, os.getpid(), "python", rss_kb=4000)
    run_id = await new_run(services)
    going(services, None, recorder=200)  # the sampler is driven by hand here

    first = await services.metrics.sample(run_id)
    assert first.spotify_rss_bytes == kib(3000)
    assert first.spytifyd_rss_bytes == kib(3000)
    assert first.controller_rss_bytes == kib(4000)
    assert first.spotify_cpu_pct is None  # the first sample of a run has no interval
    assert first.spytifyd_cpu_pct is None and first.controller_cpu_pct is None

    # A minute later: the client used one core (6000 ticks = 60 s), spytifyd half a core.
    make_proc(proc, 100, "spotify", rss_kb=1000, ticks=(4000, 0))
    make_proc(proc, 101, "Web Content", rss_kb=2000, ticks=(3000, 0), exe=spotify / "spotify")
    make_proc(proc, 200, "spytifyd", rss_kb=3000, ticks=(3000, 0))
    await fake_clock.advance(60)
    second = await services.metrics.sample(run_id)
    assert second.spotify_cpu_pct == pytest.approx(100.0)
    assert second.spytifyd_cpu_pct == pytest.approx(50.0)
    assert second.controller_cpu_pct == pytest.approx(0.0)


async def test_a_new_run_starts_without_cpu(
    running_app: FastAPI, services: Services, fake_clock: FakeClock, sampler: None, proc: Path
) -> None:
    going(services, None)  # driven by hand
    make_proc(proc, 100, "spotify", rss_kb=1000, ticks=(0, 0))
    first_run = await new_run(services)
    await services.metrics.sample(first_run)
    await fake_clock.advance(60)
    make_proc(proc, 100, "spotify", rss_kb=1000, ticks=(6000, 0))
    assert (await services.metrics.sample(first_run)).spotify_cpu_pct == pytest.approx(100.0)

    second_run = await new_run(services)
    await fake_clock.advance(60)
    make_proc(proc, 100, "spotify", rss_kb=1000, ticks=(12000, 0))
    sample = await services.metrics.sample(second_run)
    assert sample.spotify_cpu_pct is None and sample.spotify_rss_bytes == kib(1000)


async def test_a_client_that_isnt_running_has_no_rss_or_cpu(
    running_app: FastAPI, services: Services, sampler: None
) -> None:
    run_id = await new_run(services)
    going(services, None)
    sample = await services.metrics.sample(run_id)
    assert sample.spotify_rss_bytes is None and sample.spotify_cpu_pct is None
    assert sample.spytifyd_rss_bytes is None  # no recorder between items
    assert sample.controller_rss_bytes is None  # this process isn't in the fake /proc either


async def test_the_client_cache_is_summed(
    running_app: FastAPI, services: Services, sampler: None
) -> None:
    cache = services.config.home_dir / ".cache" / "spotify"
    (cache / "deep").mkdir(parents=True)
    (cache / "a.bin").write_bytes(b"x" * 10)
    (cache / "deep" / "b.bin").write_bytes(b"x" * 20)
    run_id = await new_run(services)
    going(services, None)
    assert (await services.metrics.sample(run_id)).client_cache_bytes == 30


async def test_a_missing_cache_is_zero(
    running_app: FastAPI, services: Services, sampler: None
) -> None:
    run_id = await new_run(services)
    going(services, None)
    assert (await services.metrics.sample(run_id)).client_cache_bytes == 0


async def test_free_space_is_the_storage_ports_answer(
    running_app: FastAPI, services: Services, sampler: None
) -> None:
    run_id = await new_run(services)
    going(services, None)
    sample = await services.metrics.sample(run_id)
    music = await services.ports.storage.volume(services.config.music_dir)
    config = await services.ports.storage.volume(services.config.config_dir)
    assert sample.music_free_bytes == music.free_bytes
    assert sample.config_free_bytes == config.free_bytes


async def test_values_that_cant_be_read_are_null(
    running_app: FastAPI,
    services: Services,
    sampler: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_volume(path: Path) -> Any:
        raise OSError("the volume can't be read")

    monkeypatch.setattr(services.ports.storage, "volume", no_volume)
    run_id = await new_run(services)
    going(services, None)
    sample = await services.metrics.sample(run_id)
    assert sample.music_free_bytes is None and sample.config_free_bytes is None
    assert sample.spotify_rss_bytes is None  # and the rest of the sample is still there
    assert sample.webapi_requests_30s == 0


# --- The Web API rate and the loop lag


async def test_the_web_api_rate_and_the_loop_lag(
    running_app: FastAPI, services: Services, fake_clock: FakeClock, sampler: None
) -> None:
    now = iso_ms(fake_clock.now())
    await services.store.executemany(
        "INSERT INTO api_requests (at, endpoint_id, status, latency_ms, attempt, scope_kind) "
        "VALUES (?, 1, 200, 10, 1, 'other')",
        [(now,), (now,), (now,)],
    )
    services.loopwatch.record(0.3)
    run_id = await new_run(services)
    going(services, None)
    sample = await services.metrics.sample(run_id)
    assert sample.webapi_requests_30s == 3
    assert sample.loop_lag_max_ms == 300
    # The loop lag is the largest since the last sample: it starts over.
    assert (await services.metrics.sample(run_id)).loop_lag_max_ms == 0


async def test_the_sample_is_stored_with_every_column(
    running_app: FastAPI, services: Services, sampler: None
) -> None:
    run_id = await new_run(services)
    going(services, None)
    sample = await services.metrics.sample(run_id)
    await services.metrics.store(sample)
    (row,) = await stored(services)
    assert row["run_id"] == run_id and row["at"] == sample.at
    assert row["loop_lag_max_ms"] == sample.loop_lag_max_ms
    assert row["client_cache_bytes"] == sample.client_cache_bytes
    assert row["webapi_requests_30s"] == sample.webapi_requests_30s


async def test_the_sampler_reads_the_real_proc_by_default(
    running_app: FastAPI, services: Services
) -> None:
    assert services.metrics.proc_root == Path("/proc")
    assert services.metrics.clk_tck == os.sysconf("SC_CLK_TCK")
