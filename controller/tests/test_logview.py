"""History › Logs (spotivault.logview): reading each log format, rotated files and partial lines,
paging, the filters, masking, the zip, retention, and the live tail with its batching.

The log files here are made up, in the formats the container writes (logview/lines.py).
"""

import asyncio
import contextlib
import io
import json
import logging
import os
import time
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from asgi_ws import websocket_connect
from contract import assert_response, assert_schema
from spotivault import logs
from spotivault.config import Config
from spotivault.events import LOG_BATCH_MAX, EventBus, Subscription
from spotivault.fake.clock import FakeClock
from spotivault.logview import archive, retention
from spotivault.logview.files import LogFile, bounds, list_files, read_file
from spotivault.logview.lines import (
    DEFAULT_LEVELS,
    LineParser,
    datetime_ns,
    decode_key,
    encode_key,
    iso_ms_ns,
    mask,
)
from spotivault.logview.reader import LogFilter, read_page
from spotivault.logview.service import Following, parse_follow
from spotivault.logview.tail import TailReader
from spotivault.services import Services

T0 = datetime(2026, 11, 15, 1, 0, 0, tzinfo=UTC)
TOKEN = "BQ" + "x" * 60  # looks like a Spotify access token
REFRESH = "AQ" + "y" * 60  # looks like a refresh token


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def s6(moment: datetime, text: str) -> str:
    """A line as s6-log's `T` writes it: UTC, nanoseconds, two spaces."""
    return f"{moment:%Y-%m-%d %H:%M:%S}.{moment.microsecond:06d}000  {text}\n"


def spytify(moment: datetime, level: str, message: str, offset_h: int = 1) -> str:
    """A line as Spytify's --log-file has it, in the container's offset."""
    local = moment + timedelta(hours=offset_h)
    sign = "+" if offset_h >= 0 else "-"
    stamp = f"{local:%Y-%m-%dT%H:%M:%S}.{local.microsecond:06d}123{sign}{abs(offset_h):02d}:00"
    return f"{stamp} {level:<5} {message}\n"


def write(path: Path, text: str, *, mtime: datetime | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        stamp = mtime.timestamp()
        os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def logs_dir(tmp_path: Path) -> Path:
    path = tmp_path / "logs"
    path.mkdir()
    return path


def sample_logs(logs_dir: Path) -> None:
    """A bit of every source, around a run 42 from T0+60 s to T0+120 s."""
    write(
        logs_dir / "controller" / "current",
        s6(at(0), "INFO spotivault.schedule: schedule: window opened")
        + s6(at(61), "INFO spotivault.engine.run: runs: run 42 started")
        + s6(at(62), "DEBUG spotivault.engine.item: item: planning")
        + s6(at(90), "ERROR spotivault.engine.item: item: the recorder failed")
        + s6(at(90.001), "    Traceback (most recent call last):")
        + s6(at(90.002), '      File "item.py", line 1, in run')
        + s6(at(130), "WARNING spotivault.loopwatch: loop: 300 ms late")
        + s6(at(131), "CRITICAL spotivault: uncaught exception"),
    )
    write(
        logs_dir / "spotify" / "current",
        s6(at(63), "Warning: no GPU found, drawing in software")
        + s6(at(64), "[1121/183738.292224:ERROR:gpu_init.cc(1)] GPU init failed")
        + s6(at(65), "plain chatter"),
    )
    write(
        logs_dir / "pulseaudio" / "current",
        s6(at(66), "E: [pulseaudio] main.c: no sink") + s6(at(67), "W: [pulseaudio] slow"),
    )
    write(logs_dir / "xserver" / "current", s6(at(68), "(EE) Failed to open"))
    write(logs_dir / "init" / "current", s6(at(-30), "warning: app can't write to /music"))
    write(
        logs_dir / "spytify" / "42-liked.log",
        spytify(at(70), "info", "session 20261115-010110 started")
        + spytify(at(71), "debug", "player: volume 100")
        + spytify(at(72), "warn", "capture: quiet")
        + spytify(at(73), "error", "session.start: failed (code -32007)"),
    )
    write(logs_dir / "spytify" / "42-liked.events.jsonl", '{"method":"log","params":{}}\n' * 3)
    write(logs_dir / "spytify" / "41-liked.log", spytify(at(-600), "info", "an older run"))


def all_lines(logs_dir: Path, flt: LogFilter | None = None, **kwargs: object) -> list[str]:
    flt = flt or LogFilter(levels=frozenset({"debug", "info", "warning", "error"}))
    page = read_page(logs_dir, flt, limit=500, **kwargs)  # type: ignore[arg-type]
    return [line.text for line in page.lines]


# --- Formats ----------------------------------------------------------------------------------


def test_controller_lines_lose_the_logger_and_take_pythons_levels() -> None:
    parser = LineParser(kind="s6", source="controller", service="controller")
    line = parser.parse(s6(at(1), "WARNING spotivault.loopwatch: loop: 300 ms late").rstrip("\n"))
    assert (line.level, line.text) == ("warning", "loop: 300 ms late")
    assert line.at_ns == datetime_ns(at(1))
    assert parser.parse(s6(at(2), "CRITICAL spotivault: boom").rstrip()).level == "error"
    head = parser.parse(s6(at(3), "ERROR spotivault.x: failed").rstrip())
    tail = parser.parse(s6(at(3.1), "    Traceback (most recent call last):").rstrip())
    assert (head.level, tail.level) == ("error", "error")  # a traceback takes its line's level
    assert tail.text == "    Traceback (most recent call last):"


@pytest.mark.parametrize(
    ("source", "text", "level"),
    [
        ("client", "Warning: no GPU found, drawing in software", "warning"),
        ("client", "[1121/183738.292224:ERROR:gpu_init.cc(1)] GPU init failed", "error"),
        ("client", "[152:152:1121/183738.29:WARNING:x.cc(3)] hm", "warning"),
        ("client", "(spotify:152): Gtk-WARNING **: 18:37:38.292: theme", "warning"),
        ("client", "not installed yet: waiting for spotify-install", "info"),
        ("system", "E: [pulseaudio] main.c: no sink", "error"),
        ("system", "W: [pulseaudio] slow", "warning"),
        ("system", "I: [pulseaudio] ok", "info"),
        ("system", "(EE) Failed to open", "error"),
        ("system", "(WW) odd", "warning"),
        ("system", "warning: app can't write to /music", "warning"),
        ("system", "The VNC desktop is:      localhost:0", "info"),
    ],
)
def test_other_programs_levels_come_from_their_markers(source: str, text: str, level: str) -> None:
    parser = LineParser(kind="s6", source=source, service="x")  # type: ignore[arg-type]
    line = parser.parse(s6(at(1), text).rstrip("\n"))
    assert (line.level, line.text) == (level, text)


def test_spytify_lines_are_made_utc_and_keep_their_level() -> None:
    parser = LineParser(kind="spytify", source="spytify", service="42-liked", run_id=42)
    line = parser.parse(spytify(at(5), "warn", "capture: quiet").rstrip("\n"))
    assert (line.level, line.text, line.run_id) == ("warning", "capture: quiet", 42)
    assert line.at_ns == datetime_ns(at(5)) + 123  # the +01:00 offset taken off
    assert parser.parse(spytify(at(6), "info", "x", offset_h=-3).rstrip()).at_ns // 1000 == (
        datetime_ns(at(6)) // 1000
    )
    assert parser.parse(spytify(at(7), "debug", "y").rstrip()).level == "debug"
    assert parser.parse(spytify(at(8), "error", "z").rstrip()).level == "error"
    # A line with no time carries on the one before.
    carried = parser.parse("  goroutine 1 [running]:")
    assert (carried.at_ns, carried.level, carried.dup) == (datetime_ns(at(8)) + 123, "error", 1)


def test_a_time_that_cant_be_one_is_read_as_text(logs_dir: Path) -> None:
    """A date-shaped line with no such date (or before 1970) carries on the line before; it never
    raises, so a page and the live tail read past it."""
    parser = LineParser(kind="spytify", source="spytify", service="42-liked", run_id=42)
    first = parser.parse(spytify(at(5), "warn", "capture: quiet").rstrip("\n"))
    for raw in (
        "0000-00-00T00:00:00Z header missing",
        "2026-13-45T00:00:00Z not a month",
        "1960-01-01T00:00:00Z before 1970",
    ):
        line = parser.parse(raw)
        assert (line.at_ns, line.level, line.text) == (first.at_ns, "warning", raw)
    s6_parser = LineParser(kind="s6", source="system", service="dbus")
    before = s6_parser.parse(s6(at(1), "E: [dbus] broke").rstrip())
    odd = s6_parser.parse("2026-02-30 00:00:00.000000000  no such day")
    assert (odd.at_ns, odd.level) == (before.at_ns, "error")

    item_log = write(logs_dir / "spytify" / "42-liked.log", spytify(at(5), "info", "started"))
    tail = TailReader(logs_dir)
    tail.start(datetime_ns(at(6)))
    with item_log.open("a") as handle:
        handle.write("0000-00-00T00:00:00Z header missing\n")
    assert [line.text for line in tail.poll()] == ["0000-00-00T00:00:00Z header missing"]
    assert all_lines(logs_dir) == ["started", "0000-00-00T00:00:00Z header missing"]


def test_ids_are_keys_and_round_trip() -> None:
    parser = LineParser(kind="s6", source="system", service="dbus")
    first = parser.parse(s6(at(1), "a").rstrip())
    second = parser.parse(s6(at(1), "b").rstrip())  # the same nanosecond
    assert (first.dup, second.dup) == (0, 1)
    assert first.key < second.key
    assert decode_key(second.id) == second.key
    assert decode_key(encode_key((5, "42-liked-2", 0))) == (5, "42-liked-2", 0)
    assert decode_key("nonsense") is None
    assert iso_ms_ns(datetime_ns(at(1.5))) == "2026-11-15T01:00:01.500Z"


# --- Files and pages --------------------------------------------------------------------------


def test_every_source_is_read_in_time_order_without_events_files(logs_dir: Path) -> None:
    sample_logs(logs_dir)
    names = {file.archive_name for file in list_files(logs_dir)}
    assert "spytify/42-liked.events.jsonl" not in names
    page = read_page(logs_dir, LogFilter(levels=frozenset(DEFAULT_LEVELS | {"debug"})), limit=500)
    times = [line.at_ns for line in page.lines]
    assert times == sorted(times)
    assert {line.source for line in page.lines} == {"controller", "client", "system", "spytify"}
    assert page.next_before is None
    sources = {line.service: line.source for line in page.lines}
    assert sources["spotify"] == "client"
    assert sources["init"] == "system"
    assert sources["42-liked"] == "spytify"


def test_rotated_files_and_partial_last_lines(logs_dir: Path) -> None:
    folder = logs_dir / "controller"
    write(
        folder / "@400000006937d3e000000000.s", s6(at(1), "INFO a: one") + s6(at(2), "INFO a: two")
    )
    write(folder / "@400000006937d3f000000000.s", s6(at(3), "INFO a: three"))
    # current's last line is still being written: no newline yet.
    write(folder / "current", s6(at(4), "INFO a: four") + s6(at(5), "INFO a: fi").rstrip("\n"))
    assert all_lines(logs_dir) == ["one", "two", "three", "four"]


def test_paging_back_covers_every_line_once(logs_dir: Path) -> None:
    folder = logs_dir / "controller"
    texts = [f"INFO a: line {n}" for n in range(57)]
    write(
        folder / "@400000006937d3e000000000.s",
        "".join(s6(at(n), t) for n, t in enumerate(texts[:20])),
    )
    write(folder / "current", "".join(s6(at(n + 20), t) for n, t in enumerate(texts[20:])))
    write(logs_dir / "dbus" / "current", "".join(s6(at(n + 0.5), f"bus {n}") for n in range(10)))
    seen: list[str] = []
    before = None
    pages = 0
    while True:
        page = read_page(logs_dir, LogFilter(), before=before, limit=10)
        pages += 1
        seen[:0] = [line.text for line in page.lines]
        if page.next_before is None:
            break
        before = page.next_before
    assert pages == 7
    expected = sorted(
        [(n, f"line {n}") for n in range(57)] + [(n + 0.5, f"bus {n}") for n in range(10)]
    )
    assert seen == [text for _, text in expected]


def test_a_page_stops_at_its_read_budget_with_a_cursor(logs_dir: Path) -> None:
    folder = logs_dir / "controller"
    write(folder / "@400000006937d3e000000000.s", s6(at(1), "INFO a: old match"))
    write(folder / "current", "".join(s6(at(10 + n), f"INFO a: filler {n}") for n in range(50)))
    flt = LogFilter(query="match")
    first = read_page(logs_dir, flt, limit=10, budget=100)  # reads current only
    assert first.lines == [] and first.next_before is not None
    second = read_page(logs_dir, flt, before=first.next_before, limit=10, budget=100)
    assert [line.text for line in second.lines] == ["old match"]


def test_a_long_line_at_either_end_hides_nothing(logs_dir: Path) -> None:
    """The bounds read past a line longer than BOUNDS_READ (s6-log's lines reach about 8.2 KB,
    Spytify's have no limit), so every line of the file is on the page."""
    long = "x" * 9000
    path = write(
        logs_dir / "spotify" / "current",
        "".join(s6(at(n), f"line {n}") for n in range(50)) + s6(at(50), long),
    )
    assert len(all_lines(logs_dir)) == 51
    found = bounds(LogFile(path, "spotify", "client", None, "s6"))
    assert found is not None and found.upper_ns == datetime_ns(at(50))

    write(path, s6(at(0), long) + "".join(s6(at(n), f"line {n}") for n in range(1, 51)))
    assert len(all_lines(logs_dir)) == 51
    item = write(
        logs_dir / "spytify" / "1-liked.log",
        spytify(at(60), "info", "y" * 40_000) + spytify(at(61), "info", "z" * 40_000),
    )
    assert len(all_lines(logs_dir)) == 53
    found = bounds(LogFile(item, "1-liked", "spytify", 1, "spytify"))
    assert found is not None
    assert (found.lower_ns, found.upper_ns) == (
        datetime_ns(at(60)) + 123,
        datetime_ns(at(61)) + 123,
    )


def test_bounds_skip_files_newer_than_the_cursor(logs_dir: Path) -> None:
    path = write(logs_dir / "dbus" / "current", s6(at(5), "a") + s6(at(9), "b"))
    found = bounds(LogFile(path, "dbus", "system", None, "s6"))
    assert found is not None
    assert found.lower_ns == datetime_ns(at(5))
    assert found.upper_ns >= datetime_ns(at(9))


# --- Filters ----------------------------------------------------------------------------------


def test_source_filter(logs_dir: Path) -> None:
    sample_logs(logs_dir)
    page = read_page(logs_dir, LogFilter(sources=frozenset({"client", "system"})), limit=500)
    assert {line.source for line in page.lines} == {"client", "system"}


def test_level_filter_hides_debug_unless_asked(logs_dir: Path) -> None:
    sample_logs(logs_dir)
    default = read_page(logs_dir, LogFilter(), limit=500).lines
    assert "debug" not in {line.level for line in default}
    errors = read_page(logs_dir, LogFilter(levels=frozenset({"error"})), limit=500).lines
    assert {line.level for line in errors} == {"error"}
    assert "    Traceback (most recent call last):" in [line.text for line in errors]
    debug = read_page(logs_dir, LogFilter(levels=frozenset({"debug"})), limit=500).lines
    assert [line.text for line in debug] == ["item: planning", "player: volume 100"]


def test_run_filter_is_the_runs_time_and_its_spytify_logs(logs_dir: Path) -> None:
    sample_logs(logs_dir)
    span = (datetime_ns(at(60)) - 5 * 10**9, datetime_ns(at(120)) + 5 * 10**9)
    texts = all_lines(logs_dir, LogFilter(run_id=42, span=span))
    assert "runs: run 42 started" in texts
    assert "session 20261115-010110 started" in texts  # its Spytify log
    assert "an older run" not in texts  # run 41's
    assert "schedule: window opened" not in texts  # before the run
    assert "loop: 300 ms late" not in texts  # after it
    assert "warning: app can't write to /music" not in texts


def test_search_is_case_insensitive_and_looks_at_the_masked_text(logs_dir: Path) -> None:
    write(
        logs_dir / "spotify" / "current",
        s6(at(1), f"Authorization: Bearer {TOKEN}") + s6(at(2), "Stall on NETWORK"),
    )
    assert all_lines(logs_dir, LogFilter(query="network")) == ["Stall on NETWORK"]
    assert all_lines(logs_dir, LogFilter(query=TOKEN[:20].lower())) == []
    page = read_page(logs_dir, LogFilter(query="bearer"), limit=10)
    assert page.lines[0].masked() == "Authorization: Bearer [redacted]"


# --- Masking ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "masked"),
    [
        (f"Authorization: Bearer {TOKEN}", "Authorization: Bearer [redacted]"),
        ("GET http://127.0.0.1:8888/callback?code=AbC123&state=k", "?code=[redacted]&state=k"),
        ("https://x.test/?access_token=abcdef&x=1", "access_token=[redacted]&x=1"),
        (f'{{"refresh_token": "{REFRESH}"}}', '"refresh_token": "[redacted]"'),
        (f"token {REFRESH} leaked", "token [redacted] leaked"),
        ("hunter2-secret-pw in a line", "[redacted] in a line"),
        # URL-encoded, and right after `_`: no word boundary before the token.
        (f"header=Authorization%3A%20Bearer%20{TOKEN}", "%20Bearer%20[redacted]"),
        (f"body=%7B%22access_token%22%3A%22{TOKEN}%22%7D", "%3A%22[redacted]%22%7D"),
        (f"saved_token_{TOKEN}", "saved_token_[redacted]"),
        (f"refresh=%22{REFRESH}%22", "refresh=%22[redacted]%22"),
    ],
)
def test_every_source_is_masked(logs_dir: Path, raw: str, masked: str) -> None:
    write(logs_dir / "spotify" / "current", s6(at(1), raw))
    write(logs_dir / "spytify" / "1-liked.log", spytify(at(2), "info", raw))
    write(logs_dir / "controller" / "current", s6(at(3), f"INFO a: {raw}"))
    secrets = ("hunter2-secret-pw",)
    page = read_page(logs_dir, LogFilter(secrets=secrets), limit=10)
    assert len(page.lines) == 3
    for line in page.lines:
        assert masked in line.to_api(secrets)["message"]
        assert TOKEN not in line.to_api(secrets)["message"]
        assert REFRESH not in line.to_api(secrets)["message"]


def test_mask_leaves_plain_text_alone() -> None:
    assert mask("runs: run 42 started") == "runs: run 42 started"
    # A long word that only has BQ inside it isn't a token.
    assert mask("ABQ" + "a" * 50) == "ABQ" + "a" * 50
    assert mask("%2BQ" + "a" * 50) == "%2BQ" + "a" * 50
    long = "x" * 5000
    parser = LineParser(kind="s6", source="system", service="dbus")
    assert len(parser.parse(s6(at(1), long).rstrip()).masked()) == 4000


# --- The zip ----------------------------------------------------------------------------------


def test_the_zip_holds_the_last_days_logs_masked_without_events(logs_dir: Path) -> None:
    sample_logs(logs_dir)
    write(logs_dir / "spotify" / "current", s6(at(63), f"Bearer {TOKEN}"), mtime=at(63))
    old = write(
        logs_dir / "controller" / "@400000006937d3e000000000.s", s6(at(-9 * 86400), "INFO a: old")
    )
    os.utime(old, ((at(-9 * 86400)).timestamp(),) * 2)
    since = datetime_ns(at(0)) - 7 * 86400 * 10**9
    handle = archive.build_zip(logs_dir, since)
    with handle, zipfile.ZipFile(io.BytesIO(handle.read())) as zf:
        names = set(zf.namelist())
        assert "controller/current" in names
        assert "spytify/42-liked.log" in names
        assert "init/current" in names
        assert "spytify/42-liked.events.jsonl" not in names
        assert "controller/@400000006937d3e000000000.s" not in names  # older than 7 days
        client = zf.read("spotify/current").decode()
        assert TOKEN not in client and "Bearer [redacted]" in client


async def test_download_streams_a_zip(
    running_app: FastAPI, client: httpx.AsyncClient, services: Services
) -> None:
    sample_logs(services.config.logs_dir)
    response = await client.get("/api/logs/download", params={"days": 3})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="spotivault-logs-'
    )
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert "controller/current" in zf.namelist()
    assert (await client.get("/api/logs/download", params={"days": 15})).status_code == 422


# --- Retention --------------------------------------------------------------------------------


def test_retention_deletes_old_files_but_never_current_or_a_running_runs(logs_dir: Path) -> None:
    now = at(30 * 86400)
    old = at(0)
    rotated = write(logs_dir / "controller" / "@400000006937d3e000000000.s", "x\n", mtime=old)
    current = write(logs_dir / "controller" / "current", "x\n", mtime=old)
    done_log = write(logs_dir / "spytify" / "7-liked.log", "x\n", mtime=old)
    done_events = write(logs_dir / "spytify" / "7-liked.events.jsonl", "x\n", mtime=old)
    going = write(logs_dir / "spytify" / "8-liked.log", "x\n", mtime=old)
    newer_run = write(logs_dir / "spytify" / "9-liked-2.log", "x\n", mtime=old)
    stray = write(logs_dir / "spytify" / "notes.txt", "x\n", mtime=old)
    recent = write(logs_dir / "spytify" / "6-liked.log", "x\n", mtime=now)
    result = retention.prune(logs_dir, datetime_ns(now), protected=frozenset({8}), newest_run=8)
    assert result.deleted == 3
    assert not rotated.exists() and not done_log.exists() and not done_events.exists()
    for kept in (current, going, newer_run, stray, recent):
        assert kept.exists(), kept.name


def test_retention_keeps_to_the_budget_events_files_first(logs_dir: Path) -> None:
    now = at(86400)
    mb = 1024 * 1024
    log_old = write(logs_dir / "spytify" / "1-liked.log", "a" * mb, mtime=at(0))
    events_new = write(logs_dir / "spytify" / "2-liked.events.jsonl", "e" * (2 * mb), mtime=at(500))
    log_new = write(logs_dir / "spytify" / "2-liked.log", "b" * mb, mtime=at(600))
    running = write(logs_dir / "spytify" / "3-liked.events.jsonl", "r" * (3 * mb), mtime=at(10))
    rotated = write(logs_dir / "dbus" / "@400000006937d3e000000000.s", "c" * mb, mtime=at(100))
    result = retention.prune(
        logs_dir,
        datetime_ns(now),
        protected=frozenset({3}),
        newest_run=3,
        budget_bytes=2 * mb,
    )
    # 5 MB it may delete (the run going's 3 MB isn't counted): the events file goes first (3 MB
    # left), then the oldest log (2 MB).
    assert not events_new.exists() and not log_old.exists()
    assert log_new.exists() and rotated.exists() and running.exists()
    assert (result.total_bytes, result.deletable_bytes) == (5 * mb, 2 * mb)


def test_retention_doesnt_count_what_it_cant_delete(logs_dir: Path) -> None:
    """A long item's events file alone passes the budget: it mustn't take every other log, nor
    the rotated files written during its run (the run's own controller lines)."""
    mb = 1024 * 1024
    now = at(86400)
    run_start = at(86400 - 9 * 3600)
    write(logs_dir / "spytify" / "8-liked.events.jsonl", "e" * (6 * mb), mtime=now)  # still going
    write(logs_dir / "spytify" / "8-liked.log", "l" * mb, mtime=now)
    write(logs_dir / "controller" / "current", "c" * mb, mtime=now)
    during = [
        write(
            logs_dir / "controller" / f"@40000000693{n}d3e000000000.s",
            "d" * mb,
            mtime=at(80000 + n),
        )
        for n in range(3)
    ]
    yesterday = [
        write(logs_dir / "spytify" / "7-liked.log", "y" * mb, mtime=at(0)),
        write(logs_dir / "dbus" / "@400000006930d3e000000000.s", "b" * mb, mtime=at(10)),
    ]
    result = retention.prune(
        logs_dir,
        datetime_ns(now),
        protected=frozenset({8}),
        newest_run=8,
        keep_since_ns=datetime_ns(run_start),
        budget_bytes=5 * mb,
    )
    assert result.deleted == 0
    for kept in [*during, *yesterday]:
        assert kept.exists(), kept.name
    # Over the budget with what it may delete: only the oldest go, never the run's rotated files.
    write(logs_dir / "spytify" / "6-liked.log", "o" * (5 * mb), mtime=at(5))
    result = retention.prune(
        logs_dir,
        datetime_ns(now),
        protected=frozenset({8}),
        newest_run=8,
        keep_since_ns=datetime_ns(run_start),
        budget_bytes=5 * mb,
    )
    assert not yesterday[0].exists() and not (logs_dir / "spytify" / "6-liked.log").exists()
    assert yesterday[1].exists() and all(path.exists() for path in during)
    assert result.deletable_bytes == mb


async def test_retention_runs_at_start_up_and_protects_the_run_going(
    services: Services, fake_clock: FakeClock, config: Config
) -> None:
    logs_dir = config.logs_dir
    old = fake_clock.now() - timedelta(days=20)
    gone = write(logs_dir / "spytify" / "5-liked.log", "x\n", mtime=old)
    kept = write(logs_dir / "spytify" / "6-liked.log", "x\n", mtime=old)
    await services.store.open()
    try:
        await services.store.execute(
            "INSERT INTO runs (id, kind, trigger, state, started_at) "
            "VALUES (6, 'run', 'run_now', 'running', '2026-11-14T23:00:00.000Z')"
        )
        await services.logs.prune_once()
    finally:
        await services.store.close()
    assert not gone.exists()
    assert kept.exists()


async def test_retention_and_the_zip_go_by_real_time_not_the_worlds(
    services: Services, fake_clock: FakeClock, config: Config
) -> None:
    """Fake mode's world can run days ahead of the files' real times: a file just written is
    neither deleted nor left out of the zip. A run's rotated files are kept from its start, its
    age on the world's clock back from real time."""
    logs_dir = config.logs_dir
    wall = datetime_ns(T0)
    services.logs.wall_ns = lambda: wall
    fresh = write(logs_dir / "spytify" / "5-liked.log", spytify(at(-1), "info", "x"), mtime=at(-1))
    during = write(logs_dir / "dbus" / "@400000006937d3e000000000.s", "d\n", mtime=at(-60))
    before = write(logs_dir / "dbus" / "@400000006937d3e000000001.s", "b\n", mtime=at(-7200))
    await fake_clock.advance(timedelta(days=20).total_seconds())  # the world is 20 days ahead
    await services.store.open()
    try:
        started = fake_clock.now() - timedelta(minutes=30)  # on the world's clock
        await services.store.execute(
            "INSERT INTO runs (id, kind, trigger, state, started_at) "
            "VALUES (6, 'run', 'run_now', 'running', ?)",
            (started.isoformat(),),
        )
        assert (await services.logs.prune_once()).deleted == 0  # nothing is 14 days old
        # Over a budget that holds `fresh` only: the oldest goes, not the run's rotated file.
        result = await services.logs.prune_once(budget_bytes=fresh.stat().st_size)
    finally:
        await services.store.close()
    assert fresh.exists() and during.exists()
    assert not before.exists() and result.deleted == 1
    handle, _ = await services.logs.download(1)
    with handle, zipfile.ZipFile(io.BytesIO(handle.read())) as zf:
        assert "spytify/5-liked.log" in zf.namelist()


# --- GET /api/logs ----------------------------------------------------------------------------


async def test_list_logs_answers_the_contracts_page(
    running_app: FastAPI, client: httpx.AsyncClient, services: Services
) -> None:
    sample_logs(services.config.logs_dir)
    response = await client.get("/api/logs", params={"limit": 3})
    assert_response(response, "/api/logs")
    body = response.json()
    assert len(body["lines"]) == 3 and body["next_before"] == body["lines"][0]["id"]
    older = await client.get("/api/logs", params={"limit": 3, "before": body["next_before"]})
    assert older.json()["lines"][-1]["at"] < body["lines"][0]["at"]

    filtered = await client.get(
        "/api/logs", params=[("source", "client"), ("source", "system"), ("level", "error")]
    )
    lines = filtered.json()["lines"]
    assert lines and {(line["source"], line["level"]) for line in lines} <= {
        ("client", "error"),
        ("system", "error"),
    }
    searched = await client.get("/api/logs", params={"q": "GPU INIT"})
    assert [line["service"] for line in searched.json()["lines"]] == ["spotify"]


async def test_list_logs_by_run_and_its_errors(
    running_app: FastAPI, client: httpx.AsyncClient, services: Services
) -> None:
    sample_logs(services.config.logs_dir)
    await services.store.execute(
        "INSERT INTO runs (id, kind, trigger, state, outcome, started_at, ended_at) VALUES "
        "(42, 'run', 'run_now', 'ended', 'completed', ?, ?)",
        ("2026-11-15T01:01:00.000Z", "2026-11-15T01:02:00.000Z"),
    )
    await services.store.execute(
        "INSERT INTO runs (id, kind, trigger, started_at) VALUES "
        "(43, 'missed', 'scheduled', '2026-11-15T02:00:00.000Z')"
    )
    response = await client.get("/api/logs", params={"run": 42})
    assert_response(response, "/api/logs")
    messages = [line["message"] for line in response.json()["lines"]]
    assert "runs: run 42 started" in messages and "session 20261115-010110 started" in messages
    assert "schedule: window opened" not in messages
    assert all(
        line["run_id"] == 42 for line in response.json()["lines"] if line["source"] == "spytify"
    )

    missing = await client.get("/api/logs", params={"run": 99})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert (await client.get("/api/logs", params={"run": 43})).status_code == 404
    bad = await client.get("/api/logs", params={"before": "x y"})
    assert bad.status_code == 422 and bad.json()["error"]["details"]["field"] == "before"
    assert (await client.get("/api/logs", params={"limit": 501})).status_code == 422
    assert (await client.get("/api/logs", params={"level": "loud"})).status_code == 422


# --- The live tail ----------------------------------------------------------------------------


def test_tail_follows_growth_rotation_partial_lines_and_new_item_logs(logs_dir: Path) -> None:
    current = write(logs_dir / "controller" / "current", s6(at(0), "INFO a: before"))
    tail = TailReader(logs_dir)
    recent = tail.start(datetime_ns(at(5)))
    assert [line.text for line in recent] == ["before"]  # within the last 10 s
    assert tail.poll() == []

    with current.open("a") as handle:
        handle.write(s6(at(6), "INFO a: grew") + s6(at(7), "INFO a: half")[:20])
    assert [line.text for line in tail.poll()] == ["grew"]
    with current.open("a") as handle:
        handle.write(s6(at(7), "INFO a: half")[20:] + s6(at(8), "INFO a: last before rotation"))
    # s6-log rotates: current is renamed, and a new one starts.
    os.rename(current, logs_dir / "controller" / "@400000006937d3e000000000.s")
    write(logs_dir / "controller" / "current", s6(at(9), "INFO a: new file"))
    write(logs_dir / "spytify" / "42-liked.log", spytify(at(10), "info", "item started"))
    texts = [line.text for line in tail.poll()]
    assert texts == ["half", "last before rotation", "new file", "item started"]


def rotate(folder: Path, n: int) -> None:
    """s6-log's rotation: `current` becomes `@<tai64n>.s` (the n-th), and a new `current` starts."""
    os.rename(folder / "current", folder / f"@400000006937d3e{n:09x}.s")


def test_tail_reads_every_rotation_between_two_polls(logs_dir: Path) -> None:
    folder = logs_dir / "controller"
    write(folder / "current", "")
    tail = TailReader(logs_dir)
    tail.start(datetime_ns(at(0)))
    for n in range(3):  # 100 lines, then a rotation, three times over; one poll for it all
        write(
            folder / "current",
            "".join(s6(at(n * 100 + k), f"INFO a: {n * 100 + k}") for k in range(100)),
        )
        if n < 2:
            rotate(folder, n)
    texts = [line.text for line in tail.poll()]
    assert texts == [str(k) for k in range(300)]
    assert tail.missed == []
    rotate(folder, 2)
    write(folder / "current", s6(at(400), "INFO a: next"))
    assert [line.text for line in tail.poll()] == ["next"]


def test_tail_keeps_a_folder_while_current_is_missing(logs_dir: Path) -> None:
    """A poll between s6-log's rename and its new `current`: the old file's last lines still
    come, at the next poll."""
    folder = logs_dir / "controller"
    current = write(folder / "current", s6(at(0), "INFO a: first"))
    tail = TailReader(logs_dir)
    tail.start(datetime_ns(at(1)))
    with current.open("a") as handle:
        handle.write("".join(s6(at(1 + k / 100), f"INFO a: before {k}") for k in range(50)))
    rotate(folder, 0)
    assert tail.poll() == []  # no `current` for now
    write(folder / "current", s6(at(3), "INFO a: after"))
    texts = [line.text for line in tail.poll()]
    assert texts == [f"before {k}" for k in range(50)] + ["after"]


async def test_lines_the_tail_skipped_are_counted_in_dropped(
    services: Services, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spotivault.logview import tail as tail_module

    monkeypatch.setattr(tail_module, "MAX_READ", 4096)
    logs_dir = config.logs_dir
    current = write(logs_dir / "spotify" / "current", "")
    write(logs_dir / "controller" / "current", "")
    reader = TailReader(logs_dir)
    reader.start(datetime_ns(at(0)))
    with current.open("a") as handle:
        handle.write("".join(s6(at(1), f"chatter {k:04d}") for k in range(1000)))
    lines = reader.poll()
    assert lines and lines[-1].text == "chatter 0999"
    ((file, count),) = reader.missed
    assert file.service == "spotify" and 800 <= count <= 1000 - len(lines) + 5

    everything, controller_only = Subscription(0), Subscription(0)
    services.bus._subscriptions.update({everything, controller_only})
    everything.log_follow = Following(LogFilter(), 1)
    controller_only.log_follow = Following(LogFilter(sources=frozenset({"controller"})), 2)
    await services.logs.deliver(lines, reader.missed)
    assert everything._logs is not None
    assert everything._logs.data["dropped"] == count + max(0, len(lines) - LOG_BATCH_MAX)
    assert controller_only._logs is None  # it wants none of the client's lines


async def test_live_batches_are_made_off_the_loop_for_the_lines_sent_only(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each follower's matching and its LogLines are worked out in a thread, and only its newest
    LOG_BATCH_MAX matches become LogLines: the rest are counted."""
    import threading

    from spotivault.logview.lines import Line

    loop_thread = threading.current_thread()
    matched_on: set[threading.Thread] = set()
    made = 0
    real_matches, real_to_api = LogFilter.matches, Line.to_api

    def matches(self: LogFilter, line: Line) -> bool:
        matched_on.add(threading.current_thread())
        return real_matches(self, line)

    def to_api(self: Line, secrets: tuple[str, ...] = ()) -> dict[str, object]:
        nonlocal made
        made += 1
        return real_to_api(self, secrets)

    monkeypatch.setattr(LogFilter, "matches", matches)
    monkeypatch.setattr(Line, "to_api", to_api)
    parser = LineParser(kind="s6", source="client", service="spotify")
    lines = [parser.parse(s6(at(k / 1000), f"chatter {k}").rstrip()) for k in range(5000)]
    subs = [Subscription(0), Subscription(0)]
    services.bus._subscriptions.update(subs)
    for n, sub in enumerate(subs):
        sub.log_follow = Following(LogFilter(), n)
    await services.logs.deliver(lines)
    assert matched_on and loop_thread not in matched_on
    assert made == LOG_BATCH_MAX  # the same 200 for both followers, made once
    for sub in subs:
        assert sub._logs is not None
        assert sub._logs.data["dropped"] == 5000 - LOG_BATCH_MAX
        assert sub._logs.data["lines"][-1]["message"] == "chatter 4999"

    # A new follower's first batch (the last seconds) is made off the loop too.
    matched_on.clear()
    late = Subscription(0)
    services.bus._subscriptions.add(late)
    await services.logs.follow(late, {"follow_id": 9})
    assert matched_on and loop_thread not in matched_on


async def test_the_tail_goes_on_after_a_poll_fails(
    services: Services,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from spotivault.logview import service as service_module

    monkeypatch.setattr(service_module, "TAIL_RETRY_S", 0.01)
    services.logs.tail_interval_s = 0.01
    current = write(config.logs_dir / "dbus" / "current", "")
    failed = 0
    real_poll = TailReader.poll

    def poll(self: TailReader) -> list:  # type: ignore[type-arg]
        nonlocal failed
        if failed == 0:
            failed += 1
            raise ValueError("year 0 is out of range")
        return real_poll(self)

    monkeypatch.setattr(TailReader, "poll", poll)
    sub = Subscription(0)
    services.bus._subscriptions.add(sub)
    await services.logs.follow(sub, {"follow_id": 1})
    task = asyncio.create_task(services.logs.tail())
    try:
        for _ in range(200):
            await asyncio.sleep(0.01)
            if failed:
                break
        with current.open("a") as handle:
            handle.write(s6(services.clock.now(), "E: [dbus] still here"))
        for _ in range(300):
            await asyncio.sleep(0.01)
            if sub._logs is not None:
                break
        assert not task.done()
        assert sub._logs is not None
        assert [line["message"] for line in sub._logs.data["lines"]] == ["E: [dbus] still here"]
        assert "the live tail failed" in caplog.text
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def test_a_batch_is_capped_and_merged_per_connection() -> None:
    sub = Subscription(hello_seq=0)
    lines = [{"id": str(n)} for n in range(LOG_BATCH_MAX + 50)]
    sub.push_logs(lines[:100], at=T0, follow_id=1)
    sub.push_logs(lines[100:], at=T0, follow_id=1)  # not sent yet: merged
    pending = sub._logs
    assert pending is not None and pending.seq is None and pending.type == "log.lines"
    assert pending.data["dropped"] == 50
    assert pending.data["lines"][0] == {"id": "50"}  # the newest are kept
    sub.push_logs([{"id": "new"}], at=T0, follow_id=2)  # a new follow replaces the old batch
    assert sub._logs is not None and sub._logs.data == {
        "lines": [{"id": "new"}],
        "dropped": 0,
        "follow_id": 2,
    }


def test_log_batches_go_only_to_followers() -> None:
    bus = EventBus(FakeClock(), version="t")
    following, other = Subscription(0), Subscription(0)
    bus._subscriptions.update({following, other})
    following.log_follow = object()
    assert bus.log_followers() == [following]


def test_follow_messages_are_checked() -> None:
    assert parse_follow({"type": "logs.follow"}) == (None, None, None, None, None)
    assert parse_follow(
        {"filter": {"source": ["spytify"], "level": ["error"], "run": 4, "q": "x"}, "follow_id": 2}
    ) == (["spytify"], ["error"], 4, "x", 2)
    for bad in (
        {"filter": {"source": ["nope"]}},
        {"filter": {"level": "error"}},
        {"filter": {"run": 0}},
        {"filter": {"run": True}},
        {"filter": {"q": "x" * 201}},
        {"filter": []},
        {"follow_id": {"a": 1}},
    ):
        assert parse_follow(bad) is None, bad


async def test_followers_get_matching_lines_in_batches(services: Services, config: Config) -> None:
    logs_dir = config.logs_dir
    now = services.clock.now()
    write(logs_dir / "controller" / "current", s6(now - timedelta(seconds=2), "INFO a: just now"))
    bus = services.bus
    errors_only, everything, not_following = Subscription(0), Subscription(0), Subscription(0)
    bus._subscriptions.update({errors_only, everything, not_following})
    await services.logs.follow(errors_only, {"filter": {"level": ["error"]}, "follow_id": "e"})
    await services.logs.follow(everything, {"follow_id": 7})

    def drain(sub: Subscription) -> list[str]:
        event, sub._logs = sub._logs, None
        return [] if event is None else [line["message"] for line in event.data["lines"]]

    reader = TailReader(logs_dir)
    await services.logs.deliver(await asyncio.to_thread(reader.start, datetime_ns(now)))
    assert drain(everything) == ["just now"]
    assert drain(errors_only) == []
    with (logs_dir / "controller" / "current").open("a") as handle:
        handle.write(
            s6(now, "DEBUG a: noisy")
            + s6(now, "ERROR a: broke")
            + s6(now, f"INFO a: Bearer {TOKEN}")
        )
    await services.logs.deliver(await asyncio.to_thread(reader.poll))
    assert drain(everything) == ["broke", "Bearer [redacted]"]  # no debug unless asked
    assert drain(errors_only) == ["broke"]
    assert not_following._logs is None

    # A new follower gets the last seconds at once.
    late = Subscription(0)
    bus._subscriptions.add(late)
    await services.logs.follow(late, {})
    assert drain(late) == ["just now", "broke", "Bearer [redacted]"]


async def test_a_runs_follow_ends_with_the_run(services: Services, config: Config) -> None:
    await services.store.open()
    try:
        await services.store.execute(
            "INSERT INTO runs (id, kind, trigger, state, started_at) VALUES "
            "(9, 'run', 'run_now', 'running', ?)",
            ((services.clock.now() - timedelta(minutes=1)).isoformat(),),
        )
        sub = Subscription(0)
        services.bus._subscriptions.add(sub)
        await services.logs.follow(sub, {"filter": {"run": 9}})
    finally:
        await services.store.close()
    following = sub.log_follow
    assert isinstance(following, Following) and following.filter.span is not None
    assert following.filter.span[1] is None  # still going
    await services.logs.deliver([])  # services.runs.active() is None: the run isn't going
    assert following.filter.span[1] is not None


async def test_follow_over_the_socket_gets_log_lines(
    running_app: FastAPI, services: Services, config: Config
) -> None:
    services.logs.tail_interval_s = 0.01
    current = write(config.logs_dir / "dbus" / "current", "")
    async with websocket_connect(running_app, "/api/events") as ws:
        assert (await ws.receive_json())["type"] == "hello"
        await ws.send_text("probe")  # not JSON: ignored
        await ws.send_text(json.dumps({"type": "logs.follow", "follow_id": 1}))
        await asyncio.sleep(0.05)  # the tail starts (real time: it isn't on the world's clock)
        with current.open("a") as handle:
            handle.write(s6(services.clock.now(), "E: [dbus] lost"))
        event = await ws.receive_json()
        assert event["type"] == "log.lines" and event["seq"] is None
        assert event["data"]["follow_id"] == 1 and event["data"]["dropped"] == 0
        (line,) = event["data"]["lines"]
        assert_schema("LogLine", line)
        assert (line["source"], line["service"], line["level"]) == ("system", "dbus", "error")
        await ws.send_text(json.dumps({"type": "logs.unfollow"}))
        await asyncio.sleep(0.05)
        assert services.bus.log_followers() == []


# --- Fake mode's own controller file -----------------------------------------------------------


def test_fake_mode_writes_the_controller_log_as_s6_log_does(
    config: Config, logs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock_ns: Callable[[], int] = lambda: datetime_ns(at(3))  # noqa: E731
    logs.use_clock(clock_ns)
    try:
        handler = logs.S6StyleFile(logs_dir / "controller")
        handler.setFormatter(logs.LineFormatter(logs.FORMAT))
        record = logging.makeLogRecord(
            {"name": "spotivault.runs", "levelname": "WARNING", "levelno": 30, "msg": "a\nb"}
        )
        handler.handle(record)
        monkeypatch.setattr(logs, "S6_FILE_BYTES", 10)  # the next record rotates the file
        handler.handle(record)
        handler.close()
    finally:
        logs.use_clock(time.time_ns)
    names = sorted(os.listdir(logs_dir / "controller"))
    assert len(names) == 1 and names[0].startswith("@4") and names[0].endswith(".s")
    lines = read_file(list_files(logs_dir)[0])[0]
    assert [(line.level, line.text) for line in lines] == [
        ("warning", "a"),
        ("warning", "    b"),
        ("warning", "a"),
        ("warning", "    b"),
    ]
    assert lines[0].at_ns == datetime_ns(at(3))


def test_fake_mode_stamps_never_go_back(logs_dir: Path) -> None:
    """A fake-mode restart starts the world's clock at real time again, behind the stamps a
    faster world left in `current`: the new lines are stamped no earlier, so a page reads them."""
    folder = logs_dir / "controller"
    write(folder / "current", s6(at(3600), "INFO spotivault.runs: from the last start"))
    logs.use_clock(lambda: datetime_ns(at(0)))  # an hour behind
    try:
        handler = logs.S6StyleFile(folder)
        handler.setFormatter(logs.LineFormatter(logs.FORMAT))
        for n in range(10):
            record = logging.makeLogRecord(
                {"name": "spotivault.runs", "levelname": "INFO", "levelno": 20, "msg": f"new {n}"}
            )
            handler.handle(record)
        handler.close()
    finally:
        logs.use_clock(time.time_ns)
    lines = read_file(list_files(logs_dir)[0])[0]
    assert all(line.at_ns >= datetime_ns(at(3600)) for line in lines)
    assert all_lines(logs_dir) == ["from the last start"] + [f"new {n}" for n in range(10)]
