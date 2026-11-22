"""The schedule's windows: contiguous active hours of the weekly grid, as real instants.

Owner: matching-backlog (the backlog's finish date needs them). Frozen for S6, whose scheduler
engine reuses them: `DAYS`, `Hours`, `WeeklyWindow`, `Window`, `weekly_windows`,
`window_instances` and `load_hours`.

The rules are contracts/vectors/schedule-windows.json's, as contracts/vectors/generate.py encodes
them (`weekly_windows`, `resolve`, `window_instances`): port that code, then check it against
every case of schedule-windows.json (and backlog.json's finish dates).
- The grid is 168 hours, Monday 00:00 first, in the container's TZ (`config.zone`). Contiguous
  active hours form one window, across midnight and from Sunday 23:00 to Monday 00:00.
- No active hours: Manual only, no windows. All 168 active: one window that never ends.
- Wall-clock times: a start or end in the spring-forward gap moves forward by the gap; a repeated
  time on fall-back night takes its first occurrence (`fold=0`), so the 02:00 cell covers both.
  A window whose end isn't after its start that night is skipped.
- A window in progress is included; one ending exactly now is over.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from spotivault.store import Store

type Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAYS: tuple[Day, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# The grid as openapi.yaml `Hours`: day → active hours (0–23).
type Hours = Mapping[str, Sequence[int]]

WEEK_HOURS = 168


@dataclass(frozen=True, slots=True)
class WeeklyWindow:
    start_day: Day
    start_hour: int
    hours: int


@dataclass(frozen=True, slots=True)
class Window:
    """One concrete window, as aware UTC instants. `end` is None for the never-ending one."""

    start: datetime
    end: datetime | None


def _grid(hours: Hours) -> list[bool]:
    """168 cells, Monday 00:00 first: True where the hour is active."""
    cells = [False] * WEEK_HOURS
    for day_index, day in enumerate(DAYS):
        for hour in hours.get(day, ()):
            cells[day_index * 24 + hour] = True
    return cells


def hours_per_week(hours: Hours) -> int:
    """The number of active hours in the grid."""
    return sum(_grid(hours))


def weekly_windows(hours: Hours) -> tuple[list[WeeklyWindow], bool]:
    """The grid's windows, sorted by start, and whether the grid is continuous (all 168 hours)."""
    cells = _grid(hours)
    if not any(cells):
        return [], False
    if all(cells):
        return [WeeklyWindow("mon", 0, WEEK_HOURS)], True
    found: list[WeeklyWindow] = []
    for j in range(WEEK_HOURS):
        # A block starts where this cell is active and the one before it isn't. For Monday
        # 00:00 the one before is Sunday 23:00 (index -1), so a Sunday block wraps to Monday.
        if cells[j] and not cells[j - 1]:
            length = 0
            while cells[(j + length) % WEEK_HOURS]:
                length += 1
            found.append(WeeklyWindow(DAYS[j // 24], j % 24, length))
    found.sort(key=lambda window: (DAYS.index(window.start_day), window.start_hour))
    return found, False


def _resolve(naive: datetime, tz: ZoneInfo) -> datetime:
    """A local wall-clock time as a UTC instant. fold=0: a time in the spring-forward gap moves
    forward by the gap (02:00 → 03:00), and a repeated fall-back time takes its first occurrence."""
    return naive.replace(tzinfo=tz, fold=0).astimezone(UTC)


def window_instances(
    hours: Hours,
    tz: ZoneInfo,
    now: datetime,
    *,
    limit: int | None = None,
    horizon_days: int = 21,
) -> list[Window]:
    """Concrete windows whose end is after `now`, in order, up to `horizon_days` ahead. A
    continuous grid gives one window from now with no end."""
    weekly, continuous = weekly_windows(hours)
    if not weekly:
        return []
    if continuous:
        return [Window(start=now, end=None)]
    # Walk whole weeks in wall-clock time, from the Monday before this week, so the Sunday
    # window that wraps to Monday and a week that started last Monday are both covered.
    local_now = now.astimezone(tz).replace(tzinfo=None)
    monday = (local_now - timedelta(days=local_now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    found: list[Window] = []
    for week in range(-1, horizon_days // 7 + 2):
        base = monday + timedelta(weeks=week)
        for window in weekly:
            start_naive = base + timedelta(
                days=DAYS.index(window.start_day), hours=window.start_hour
            )
            end_naive = start_naive + timedelta(hours=window.hours)
            start = _resolve(start_naive, tz)
            end = _resolve(end_naive, tz)
            if end <= start or end <= now:
                continue
            found.append(Window(start=start, end=end))
    found.sort(key=lambda item: item.start)
    return found[:limit] if limit is not None else found


async def load_hours(store: Store) -> dict[str, list[int]]:
    """The grid from the `schedule_hours` table (day 0 = Monday), every day present."""
    rows = await store.fetchall("SELECT day, hour FROM schedule_hours ORDER BY day, hour")
    hours: dict[str, list[int]] = {day: [] for day in DAYS}
    for row in rows:
        hours[DAYS[row["day"]]].append(row["hour"])
    return hours
