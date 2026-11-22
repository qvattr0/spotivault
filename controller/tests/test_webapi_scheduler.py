"""webapi/scheduler.py: one request at a time, playback first, catalog 250 ms apart, 429 holds.

Pure tests on the FakeClock: each "request" is a task that takes a turn, notes the time, and
holds the turn until the test lets it go.
"""

import asyncio

import pytest

from spotivault.fake.clock import FakeClock
from spotivault.webapi.endpoints import Lane
from spotivault.webapi.scheduler import CATALOG_SPACING_S, LongHold, RequestScheduler


class Requests:
    """Tasks taking turns on one scheduler. `started` lists (name, monotonic) in turn order."""

    def __init__(self, clock: FakeClock, scheduler: RequestScheduler) -> None:
        self.clock = clock
        self.scheduler = scheduler
        self.started: list[tuple[str, float]] = []
        self.release: dict[str, asyncio.Event] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, name: str, lane: Lane, *, hold: bool = False) -> asyncio.Task[None]:
        """A request in `lane`. With `hold`, it keeps its turn until `finish(name)`."""
        self.release[name] = asyncio.Event()
        if not hold:
            self.release[name].set()

        async def request() -> None:
            async with self.scheduler.turn(lane):
                self.started.append((name, self.clock.monotonic()))
                await self.release[name].wait()

        task = asyncio.create_task(request(), name=name)
        self.tasks[name] = task
        return task

    def finish(self, name: str) -> None:
        self.release[name].set()

    def order(self) -> list[str]:
        return [name for name, _ in self.started]

    def at(self, name: str) -> float:
        return dict(self.started)[name]

    async def done(self) -> None:
        await asyncio.gather(*self.tasks.values())


@pytest.fixture
def scheduler(fake_clock: FakeClock) -> RequestScheduler:
    return RequestScheduler(fake_clock)


@pytest.fixture
def requests(fake_clock: FakeClock, scheduler: RequestScheduler) -> Requests:
    return Requests(fake_clock, scheduler)


async def test_one_request_at_a_time(fake_clock: FakeClock, requests: Requests) -> None:
    requests.start("a", "playback", hold=True)
    await fake_clock.settle()
    requests.start("b", "playback")
    await fake_clock.advance(60)
    assert requests.order() == ["a"]  # b waits while a is in flight, however long
    requests.finish("a")
    await fake_clock.settle()
    assert requests.order() == ["a", "b"]
    await requests.done()


async def test_playback_and_auth_go_before_waiting_catalog_requests(
    fake_clock: FakeClock, requests: Requests
) -> None:
    requests.start("first", "catalog", hold=True)
    await fake_clock.settle()
    requests.start("c1", "catalog")
    requests.start("c2", "catalog")
    requests.start("p1", "playback")
    requests.start("auth", "auth")
    requests.start("p2", "playback")
    await fake_clock.settle()
    requests.finish("first")
    await fake_clock.advance_until(lambda: len(requests.started) == 6, within=5)
    assert requests.order() == ["first", "p1", "auth", "p2", "c1", "c2"]
    await requests.done()


async def test_catalog_requests_start_250_ms_apart(
    fake_clock: FakeClock, requests: Requests
) -> None:
    start = fake_clock.monotonic()
    for name in ("c1", "c2", "c3", "c4"):
        requests.start(name, "catalog")
    await fake_clock.settle()
    await fake_clock.advance_until(lambda: len(requests.started) == 4, within=2)
    assert requests.order() == ["c1", "c2", "c3", "c4"]  # in arrival order
    times = [at - start for _, at in requests.started]
    assert times == pytest.approx([0.0, 0.25, 0.5, 0.75])
    await requests.done()


async def test_spacing_counts_from_the_previous_catalog_start(
    fake_clock: FakeClock, requests: Requests
) -> None:
    start = fake_clock.monotonic()
    requests.start("c1", "catalog")
    await fake_clock.settle()
    await fake_clock.advance(1)
    requests.start("c2", "catalog")  # a second later: nothing to wait for
    await fake_clock.settle()
    assert requests.at("c2") - start == pytest.approx(1.0)
    await requests.done()


async def test_playback_is_not_delayed_by_catalog_spacing(
    fake_clock: FakeClock, requests: Requests
) -> None:
    start = fake_clock.monotonic()
    requests.start("c1", "catalog")
    requests.start("c2", "catalog")
    await fake_clock.settle()
    requests.start("p", "playback")
    await fake_clock.settle()
    # c2 is waiting out the 250 ms; the playback request goes straight away.
    assert requests.order() == ["c1", "p"]
    assert requests.at("p") == start
    await fake_clock.advance(CATALOG_SPACING_S)
    assert requests.order() == ["c1", "p", "c2"]
    assert requests.at("c2") - start == pytest.approx(CATALOG_SPACING_S)
    await requests.done()


async def test_a_hold_stops_every_lane_until_it_passes(
    fake_clock: FakeClock, scheduler: RequestScheduler, requests: Requests
) -> None:
    start = fake_clock.monotonic()
    scheduler.hold_until(start + 10)
    assert scheduler.held_for() == pytest.approx(10)
    requests.start("p", "playback")
    requests.start("c", "catalog")
    requests.start("a", "auth")
    await fake_clock.advance(9.9)
    assert requests.order() == []
    await fake_clock.advance(0.1)
    assert requests.order() == ["p", "a", "c"]
    assert requests.at("p") - start == pytest.approx(10)
    assert scheduler.held_for() == 0
    await requests.done()


async def test_a_later_hold_extends_an_earlier_one_does_not_shorten(
    fake_clock: FakeClock, scheduler: RequestScheduler, requests: Requests
) -> None:
    start = fake_clock.monotonic()
    scheduler.hold_until(start + 30)  # the longer Retry-After wins
    scheduler.hold_until(start + 5)
    assert scheduler.held_for() == pytest.approx(30)
    requests.start("p", "playback")
    await fake_clock.advance(29)
    assert requests.order() == []
    scheduler.hold_until(start + 40)  # a hold set while waiting is honoured too
    await fake_clock.advance(2)
    assert requests.order() == []
    await fake_clock.advance(10)
    assert requests.at("p") - start == pytest.approx(40)
    await requests.done()


async def test_waiters_leave_at_once_when_a_hold_longer_than_their_max_starts(
    fake_clock: FakeClock, scheduler: RequestScheduler
) -> None:
    release = asyncio.Event()
    started: list[str] = []

    async def request(name: str, lane: Lane, *, hold: bool = False) -> None:
        async with scheduler.turn(lane, max_hold_s=120):
            started.append(name)
            if hold:
                await release.wait()

    first = asyncio.create_task(request("first", "catalog", hold=True))
    await fake_clock.settle()
    waiting = [
        asyncio.create_task(request("c", "catalog")),
        asyncio.create_task(request("p", "playback")),
    ]
    await fake_clock.settle()
    assert scheduler.waiting == 2

    scheduler.hold_until(fake_clock.monotonic() + 600)  # the first one's 429
    await fake_clock.settle()
    try:
        for task in waiting:
            with pytest.raises(LongHold) as caught:
                await asyncio.wait_for(task, 2)  # real seconds: they must not wait the hold out
            assert caught.value.held_s == pytest.approx(600)
        assert scheduler.waiting == 0 and started == ["first"]
    finally:
        release.set()
        for task in waiting:
            task.cancel()
        await first


async def test_a_hold_within_the_max_is_waited_out(
    fake_clock: FakeClock, scheduler: RequestScheduler
) -> None:
    start = fake_clock.monotonic()
    scheduler.hold_until(start + 120)

    async def request() -> float:
        async with scheduler.turn("playback", max_hold_s=120):
            return fake_clock.monotonic()

    task = asyncio.create_task(request())
    await fake_clock.advance(120)
    assert await task - start == pytest.approx(120)


async def test_a_caller_cancelled_while_waiting_leaves_the_queue(
    fake_clock: FakeClock, scheduler: RequestScheduler, requests: Requests
) -> None:
    requests.start("a", "playback", hold=True)
    await fake_clock.settle()
    waiting = requests.start("b", "playback")
    requests.start("c", "catalog")
    await fake_clock.settle()
    assert scheduler.waiting == 2
    waiting.cancel()
    await fake_clock.settle()
    assert scheduler.waiting == 1
    requests.finish("a")
    await fake_clock.advance(1)
    assert requests.order() == ["a", "c"]
    with pytest.raises(asyncio.CancelledError):
        await waiting
    del requests.tasks["b"]
    await requests.done()


async def test_a_caller_cancelled_while_sleeping_out_the_spacing_leaves_the_queue(
    fake_clock: FakeClock, scheduler: RequestScheduler, requests: Requests
) -> None:
    requests.start("c1", "catalog")
    await fake_clock.settle()
    sleeping = requests.start("c2", "catalog")
    requests.start("c3", "catalog")
    await fake_clock.settle()
    sleeping.cancel()
    await fake_clock.advance(1)
    assert requests.order() == ["c1", "c3"]
    assert scheduler.waiting == 0
    with pytest.raises(asyncio.CancelledError):
        await sleeping
    del requests.tasks["c2"]
    await requests.done()


async def test_a_turn_is_freed_when_its_request_fails_or_is_cancelled(
    fake_clock: FakeClock, scheduler: RequestScheduler, requests: Requests
) -> None:
    with pytest.raises(RuntimeError):
        async with scheduler.turn("playback"):
            raise RuntimeError("the request failed")

    in_flight = requests.start("a", "playback", hold=True)
    await fake_clock.settle()
    requests.start("b", "playback")
    await fake_clock.settle()
    in_flight.cancel()  # cancelled during its turn: the turn is freed
    await fake_clock.settle()
    assert requests.order() == ["a", "b"]
    with pytest.raises(asyncio.CancelledError):
        await in_flight
    del requests.tasks["a"]
    await requests.done()
