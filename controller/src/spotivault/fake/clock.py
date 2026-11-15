"""A Clock that only moves when a test (or the fake world) says so, and timers on any clock.

    clock = FakeClock()
    task = asyncio.create_task(something_that_sleeps(clock))
    await clock.advance(30)   # wakes every sleeper and timer due by then, in deadline order

The simulators in `spotivault.fake` drive themselves with timers (`schedule`): a track ending, the
recorder's idle exit, an install stage. On a FakeClock those run inside `advance()`, at their own
deadline, so a test sees exactly what happens when. On the system clock (`python -m spotivault
--fake`) they run on the event loop in real time.

Owner: the fake agent (controller/ARCHITECTURE.md § Ownership). tests/conftest.py's `fake_clock`
fixture uses FakeClock, so keep `advance`, `settle`, `sleepers` and `set_now` working.
"""

import asyncio
import heapq
import itertools
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from spotivault.ports import Clock

START = datetime(2026, 11, 15, 0, 0, 0, tzinfo=UTC)


class Timer(Protocol):
    """A scheduled callback that hasn't run yet. `asyncio.TimerHandle` is one too."""

    def cancel(self) -> None: ...


class FakeTimer:
    """A callback waiting in a FakeClock. Cancelling it after it ran does nothing."""

    def __init__(self, deadline: float, callback: Callable[[], None]) -> None:
        self.deadline = deadline
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


# One entry of the FakeClock's queue: (deadline, order, what to wake). The order keeps entries
# with the same deadline first-in, first-out.
type _Entry = tuple[float, int, asyncio.Future[None] | FakeTimer]


class FakeClock:
    """`ports.Clock` with time under the test's control."""

    def __init__(self, start: datetime = START) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock needs an aware start time")
        self._now = start.astimezone(UTC)
        self._monotonic = 1000.0
        self._queue: list[_Entry] = []
        self._order = itertools.count()

    # --- ports.Clock -----------------------------------------------------------------------------

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._queue, (self._monotonic + seconds, next(self._order), future))
        await future

    # --- Timers --------------------------------------------------------------------------------

    def call_later(self, delay: float, callback: Callable[[], None]) -> FakeTimer:
        """Runs `callback` once `delay` seconds have passed on this clock, inside `advance()`.
        A delay of 0 or less runs it at the next `advance()`, even `advance(0)`."""
        timer = FakeTimer(self._monotonic + max(0.0, delay), callback)
        heapq.heappush(self._queue, (timer.deadline, next(self._order), timer))
        return timer

    # --- Moving time ---------------------------------------------------------------------------

    @property
    def sleepers(self) -> int:
        """How many tasks are sleeping on this clock right now."""
        return sum(
            1 for _, _, item in self._queue if isinstance(item, asyncio.Future) and not item.done()
        )

    @property
    def timers(self) -> int:
        """How many timers are waiting to run."""
        return sum(1 for _, _, item in self._queue if isinstance(item, FakeTimer) and _live(item))

    def next_deadline(self) -> float | None:
        """The monotonic time of the next sleeper or timer due, or None when nothing waits."""
        live = [deadline for deadline, _, item in self._queue if _live(item)]
        return min(live) if live else None

    async def advance(self, seconds: float) -> None:
        """Moves time forward by `seconds`. Each sleeper and timer due by then runs at its own
        deadline, in order, and everything it wakes runs until it next waits before time moves
        on. A timer's exception propagates out of here, so the test sees it."""
        if seconds < 0:
            raise ValueError("time doesn't go back")
        target = self._monotonic + seconds
        while self._queue and self._queue[0][0] <= target:
            deadline, _, item = heapq.heappop(self._queue)
            if not _live(item):
                continue
            self._move_to(deadline)
            if isinstance(item, FakeTimer):
                item.cancelled = True  # it has run: cancelling it now does nothing
                item.callback()
            else:
                item.set_result(None)
            await self.settle()
        self._move_to(target)
        await self.settle()

    async def advance_until(
        self, condition: Callable[[], bool], *, within: float, step: float | None = None
    ) -> float:
        """Moves time forward until `condition()` is true, jumping from one deadline to the next
        (at most `step` seconds at a time, if given). Returns the seconds that passed. Raises
        TimeoutError if it's still false after `within` seconds."""
        start = self._monotonic
        limit = start + within
        await self.settle()
        while not condition():
            if self._monotonic >= limit:
                raise TimeoutError(f"still not true after {within} s of fake time")
            target = limit
            due = self.next_deadline()
            if due is not None:
                target = min(target, max(due, self._monotonic))
            if step is not None:
                target = min(target, self._monotonic + step)
            await self.advance(target - self._monotonic)
        return self._monotonic - start

    async def settle(self) -> None:
        """Lets every task that's ready run until it waits again."""
        for _ in range(20):
            await asyncio.sleep(0)

    def set_now(self, moment: datetime) -> None:
        """Jumps the wall clock (not the monotonic one), say to just before a schedule window."""
        if moment.tzinfo is None:
            raise ValueError("set_now needs an aware datetime")
        self._now = moment.astimezone(UTC)

    def _move_to(self, monotonic: float) -> None:
        if monotonic > self._monotonic:
            self._now += timedelta(seconds=monotonic - self._monotonic)
            self._monotonic = monotonic


def _live(item: asyncio.Future[None] | FakeTimer) -> bool:
    if isinstance(item, FakeTimer):
        return not item.cancelled
    return not item.done()


class ScaledClock:
    """`ports.Clock` that runs `factor` times faster than real time from the moment it's made,
    for watching whole runs in the dev server without waiting for every track. Its wall time
    drifts ahead of the real one; `schedule` scales its timers too."""

    def __init__(self, factor: float) -> None:
        if factor <= 0:
            raise ValueError("the factor must be above 0")
        self.factor = factor
        self._wall_start = datetime.now(UTC)
        self._real_start = time.monotonic()

    def now(self) -> datetime:
        return self._wall_start + timedelta(seconds=self._elapsed())

    def monotonic(self) -> float:
        return self._real_start + self._elapsed()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds) / self.factor)

    def _elapsed(self) -> float:
        return (time.monotonic() - self._real_start) * self.factor


def schedule(clock: Clock, delay: float, callback: Callable[[], None]) -> Timer:
    """Runs `callback` after `delay` seconds of `clock` time, on the event loop.

    On a FakeClock it runs inside `advance()`; on any other clock, through the running loop's
    `call_later`, so it must be called from inside the loop. The simulators use this instead of
    background tasks: a timer needs no owner and leaves nothing running when a test ends.
    """
    if isinstance(clock, FakeClock):
        return clock.call_later(delay, callback)
    if isinstance(clock, ScaledClock):
        delay /= clock.factor
    return asyncio.get_running_loop().call_later(max(0.0, delay), callback)
