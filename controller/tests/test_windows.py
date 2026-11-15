"""windows.py against contracts/vectors/schedule-windows.json, and the schedule_hours reader."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from contract import CONTRACTS
from spotivault.store import Store
from spotivault.windows import (
    DAYS,
    Window,
    hours_per_week,
    load_hours,
    weekly_windows,
    window_instances,
)

VECTORS = json.loads((CONTRACTS / "vectors" / "schedule-windows.json").read_text(encoding="utf-8"))


def parse(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def local_text(moment: datetime, tz: ZoneInfo) -> str:
    """The vectors' format: RFC 3339 with the zone's offset, to the second."""
    return moment.astimezone(tz).isoformat(timespec="seconds")


def next_windows_as_vectors(windows: list[Window], tz: ZoneInfo) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for window in windows:
        if window.end is None:
            out.append({"start": local_text(window.start, tz), "end": None, "hours": None})
        else:
            seconds = (window.end - window.start).total_seconds()
            out.append(
                {
                    "start": local_text(window.start, tz),
                    "end": local_text(window.end, tz),
                    "hours": round(seconds / 3600, 3),
                }
            )
    return out


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["id"])
def test_schedule_vectors(case: dict) -> None:
    hours = case["input"]["hours"]
    tz = ZoneInfo(case["input"]["tz"])
    now = parse(case["input"]["now"])
    expected = case["expected"]

    weekly, continuous = weekly_windows(hours)
    assert continuous is expected["continuous"]
    assert len(weekly) == expected["windows_per_week"]
    assert hours_per_week(hours) == expected["hours_per_week"]
    assert [
        {"start_day": w.start_day, "start_hour": w.start_hour, "hours": w.hours} for w in weekly
    ] == expected["weekly_windows"]

    instances = window_instances(hours, tz, now, limit=3)
    assert next_windows_as_vectors(instances, tz) == expected["next_windows"]
    assert (bool(instances) and instances[0].start <= now) is expected["in_window"]


def test_the_days_are_monday_first() -> None:
    assert DAYS == ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def test_a_window_ending_exactly_now_is_over_and_one_starting_now_is_in_progress() -> None:
    hours = {"sun": [1]}  # Sunday 01:00-02:00 local, Europe/Berlin (CET in November)
    tz = ZoneInfo("Europe/Berlin")
    at_start = parse("2026-11-15T00:00:00Z")  # 01:00 local
    at_end = parse("2026-11-15T01:00:00Z")  # 02:00 local
    assert window_instances(hours, tz, at_start, limit=1)[0].start == at_start
    assert window_instances(hours, tz, at_end, limit=1)[0].start == parse("2026-11-22T00:00:00Z")


def test_a_window_across_the_end_of_the_week_is_one_window() -> None:
    weekly, _ = weekly_windows({"sun": [23], "mon": [0]})
    assert weekly == [weekly[0]]
    assert (weekly[0].start_day, weekly[0].start_hour, weekly[0].hours) == ("sun", 23, 2)


async def test_load_hours_reads_the_grid_with_every_day_present(running_app, services) -> None:
    store: Store = services.store
    await store.execute("DELETE FROM schedule_hours")
    await store.executemany(
        "INSERT INTO schedule_hours (day, hour) VALUES (?, ?)",
        [(0, 1), (0, 2), (6, 23)],
    )
    hours = await load_hours(store)
    assert list(hours) == list(DAYS)
    assert hours["mon"] == [1, 2]
    assert hours["sun"] == [23]
    assert hours["tue"] == []
