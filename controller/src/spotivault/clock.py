"""The real clock, and the time formats the controller writes.

Code asks `services.clock` for the time instead of calling `datetime.now()` or `time.monotonic()`
itself, so tests can swap in `spotivault.fake.clock.FakeClock` and move time by hand.
"""

import asyncio
import time
from datetime import UTC, datetime


class SystemClock:
    """The `ports.Clock` the controller runs on: wall time, a monotonic timer and asyncio.sleep."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))


def iso_ms(moment: datetime) -> str:
    """RFC 3339 in UTC with milliseconds: '2026-11-15T00:42:10.512Z'.

    The format of every time in the database and in WS events (contracts/schema.sql, events.md).
    A naive datetime is refused, because it's ambiguous.
    """
    if moment.tzinfo is None:
        raise ValueError("iso_ms needs an aware datetime")
    utc = moment.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def parse_iso(text: str) -> datetime:
    """Parses an RFC 3339 time, such as one written by `iso_ms`, into an aware datetime."""
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"time without an offset: {text!r}")
    return moment
