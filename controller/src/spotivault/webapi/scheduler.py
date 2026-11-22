"""The request scheduler: one Web API request at a time (design.md § Requests).

Owner: webapi-core. Only client.py uses it.

**Rules:**
- **One in flight:** a request starts only when no other is in flight.
- **Lanes** (`endpoints.Lane`): `playback` and `auth` requests go before any waiting `catalog`
  request. Playback calls during a run aren't delayed by catalog spacing.
- **Catalog spacing:** a catalog request starts at least CATALOG_SPACING_S after the previous
  catalog request started (250 ms by default, the catalog refresh's pace).
- **Rate limits:** after a 429, `hold_until(monotonic)` holds every lane until then: Spotify's
  limits are per app. A caller that passes `max_hold_s` doesn't wait out a longer hold: whenever
  it looks at the state (when it arrives, when it's woken, after each sleep) and the hold has
  more than `max_hold_s` left, it leaves the line and LongHold is raised. That covers callers
  already waiting when the 429 arrives, not only new ones.
- **Time:** only `clock.monotonic()` and `clock.sleep()`, so tests run it on the FakeClock.
- **Fairness:** waiting requests of one lane go in arrival order.
- **Cancellation:** a caller cancelled while waiting leaves the queue without taking a turn; one
  cancelled during its turn releases it (the turn is an `async with`).

How it's used, per HTTP attempt (retry waits happen outside the turn):

    async with self.scheduler.turn(endpoint.lane, max_hold_s=RATE_LIMIT_MAX_WAIT_S):
        response = await http.send(request)

**How waiting works.** Every caller that wants a turn is a `_Waiter` in `_waiters`, in arrival
order. A waiter looks at the state and gets one of three answers from `_wait_needed`:
- go now: it takes the turn;
- wait N seconds: it's next in line, but the hold or the catalog spacing isn't over. It sleeps on
  the clock and looks again. Nothing can make that time come sooner, so a plain sleep is enough;
- wait for a change: another request is in flight, or another waiter is ahead. It waits on its
  `wake` future, which `_wake_all` sets whenever a turn ends or a waiter leaves.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from spotivault.ports import Clock
from spotivault.webapi.endpoints import Lane

CATALOG_SPACING_S = 0.25


class LongHold(Exception):
    """A 429's hold has more than the caller's `max_hold_s` left: the caller left the line
    without a turn. client.py turns it into RateLimited."""

    def __init__(self, held_s: float) -> None:
        super().__init__(f"every lane is held for {held_s:.0f} s more")
        self.held_s = held_s


@dataclass(eq=False, slots=True)
class _Waiter:
    """One caller waiting for a turn."""

    lane: Lane
    # Set by _wake_all when something changed. A new one is made before each wait.
    wake: asyncio.Future[None] | None = field(default=None)


class RequestScheduler:
    """Gives out turns to send one request. See the module docstring."""

    def __init__(self, clock: Clock, *, catalog_spacing_s: float = CATALOG_SPACING_S) -> None:
        self.clock = clock
        self.catalog_spacing_s = catalog_spacing_s
        self._busy = False  # a request is in flight
        self._waiters: list[_Waiter] = []  # in arrival order
        self._last_catalog_start: float | None = None  # clock.monotonic() of the last one
        self._hold_until = 0.0  # no request starts before this (a 429's Retry-After)

    @asynccontextmanager
    async def turn(self, lane: Lane, *, max_hold_s: float | None = None) -> AsyncIterator[None]:
        """Waits for this lane's turn, holds it for the body (one HTTP attempt), then frees it.
        With `max_hold_s`, raises LongHold instead of waiting out a longer 429 hold."""
        await self._acquire(lane, max_hold_s)
        try:
            yield
        finally:
            self._busy = False
            self._wake_all()

    def hold_until(self, monotonic: float) -> None:
        """No lane starts a request before `monotonic` (clock.monotonic() time): a 429's
        Retry-After. A later hold extends it; an earlier one doesn't shorten it."""
        self._hold_until = max(self._hold_until, monotonic)
        self._wake_all()

    def held_for(self) -> float:
        """Seconds left of the current hold, 0.0 when there's none."""
        return max(0.0, self._hold_until - self.clock.monotonic())

    @property
    def waiting(self) -> int:
        """How many callers are waiting for a turn (for tests)."""
        return len(self._waiters)

    # --- Inside --------------------------------------------------------------------------------

    async def _acquire(self, lane: Lane, max_hold_s: float | None) -> None:
        waiter = _Waiter(lane)
        self._waiters.append(waiter)
        try:
            while True:
                # A long hold may have started while we waited (hold_until wakes every waiter):
                # leave the line at once instead of sleeping through it.
                held = self.held_for()
                if max_hold_s is not None and held > max_hold_s:
                    raise LongHold(held)
                delay = self._wait_needed(waiter)
                if delay is None:
                    # Not our turn yet: wait until a turn ends or a waiter leaves. The future is
                    # made and awaited with no await in between, so no wake-up is missed.
                    waiter.wake = asyncio.get_running_loop().create_future()
                    await waiter.wake
                elif delay > 0:
                    await self.clock.sleep(delay)
                else:
                    break
        except BaseException:
            # Cancelled while waiting, or LongHold: leave the line, and let the next one look
            # again.
            self._waiters.remove(waiter)
            self._wake_all()
            raise
        # Taking the turn: no await between the check above and here, so nobody else can.
        self._waiters.remove(waiter)
        self._busy = True
        if lane == "catalog":
            self._last_catalog_start = self.clock.monotonic()

    def _wait_needed(self, waiter: _Waiter) -> float | None:
        """0.0: go now. A positive number: the seconds until this waiter may go. None: wait for
        a change (a request is in flight, or another waiter is ahead)."""
        if self._busy or self._next_in_line() is not waiter:
            return None
        ready_at = self._hold_until
        if waiter.lane == "catalog" and self._last_catalog_start is not None:
            ready_at = max(ready_at, self._last_catalog_start + self.catalog_spacing_s)
        return max(0.0, ready_at - self.clock.monotonic())

    def _next_in_line(self) -> _Waiter | None:
        """The first playback or auth waiter, else the first catalog one."""
        for waiter in self._waiters:
            if waiter.lane != "catalog":
                return waiter
        return self._waiters[0] if self._waiters else None

    def _wake_all(self) -> None:
        for waiter in self._waiters:
            if waiter.wake is not None and not waiter.wake.done():
                waiter.wake.set_result(None)
