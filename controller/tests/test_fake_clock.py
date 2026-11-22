"""fake/clock.py: time moves only when told; sleepers and timers run in deadline order."""

import asyncio
from datetime import timedelta

import pytest

from portcheck import assert_implements
from spotivault import ports
from spotivault.clock import SystemClock
from spotivault.fake.clock import START, FakeClock, ScaledClock, schedule


async def test_advance_wakes_sleepers_in_order() -> None:
    clock = FakeClock()
    woke: list[tuple[str, float]] = []

    async def sleeper(name: str, seconds: float) -> None:
        await clock.sleep(seconds)
        woke.append((name, clock.monotonic() - 1000.0))

    tasks = [asyncio.create_task(sleeper("b", 10)), asyncio.create_task(sleeper("a", 5))]
    await clock.settle()
    assert clock.sleepers == 2
    await clock.advance(4)
    assert woke == []
    await clock.advance(6)
    assert woke == [("a", 5.0), ("b", 10.0)]
    assert clock.now() == START + timedelta(seconds=10)
    await asyncio.gather(*tasks)


async def test_a_cancelled_sleeper_is_skipped() -> None:
    clock = FakeClock()
    task = asyncio.create_task(clock.sleep(5))
    await clock.settle()
    task.cancel()
    await clock.advance(10)
    assert task.cancelled()


async def test_set_now_moves_only_the_wall_clock() -> None:
    clock = FakeClock()
    clock.set_now(START + timedelta(days=1))
    assert clock.now() == START + timedelta(days=1)
    assert clock.monotonic() == 1000.0


async def test_timers_and_sleepers_run_in_deadline_order() -> None:
    clock = FakeClock()
    ran: list[tuple[str, float]] = []

    def note(name: str) -> None:
        ran.append((name, clock.monotonic() - 1000.0))

    async def sleeper() -> None:
        await clock.sleep(2)
        note("sleeper")

    clock.call_later(3, lambda: note("timer 3"))
    clock.call_later(1, lambda: note("timer 1"))
    task = asyncio.create_task(sleeper())
    await clock.settle()
    assert clock.timers == 2 and clock.sleepers == 1
    await clock.advance(5)
    assert ran == [("timer 1", 1.0), ("sleeper", 2.0), ("timer 3", 3.0)]
    assert clock.timers == 0
    await task


async def test_a_timer_can_schedule_another_within_the_same_advance() -> None:
    clock = FakeClock()
    ran: list[float] = []

    def first() -> None:
        ran.append(clock.monotonic())
        clock.call_later(1, lambda: ran.append(clock.monotonic()))

    clock.call_later(1, first)
    await clock.advance(3)
    assert ran == [1001.0, 1002.0]


async def test_cancelled_timers_never_run_and_zero_delay_runs_on_advance_0() -> None:
    clock = FakeClock()
    ran: list[str] = []
    timer = clock.call_later(1, lambda: ran.append("cancelled"))
    timer.cancel()
    clock.call_later(0, lambda: ran.append("now"))
    await clock.advance(0)
    assert ran == ["now"]
    await clock.advance(2)
    assert ran == ["now"]
    assert clock.next_deadline() is None


async def test_a_timer_error_reaches_the_test() -> None:
    clock = FakeClock()

    def broken() -> None:
        raise RuntimeError("boom")

    clock.call_later(1, broken)
    with pytest.raises(RuntimeError, match="boom"):
        await clock.advance(2)


async def test_advance_until_jumps_from_deadline_to_deadline() -> None:
    clock = FakeClock()
    done: list[bool] = []
    clock.call_later(600, lambda: done.append(True))
    passed = await clock.advance_until(lambda: bool(done), within=1000)
    assert passed == 600.0
    with pytest.raises(TimeoutError):
        await clock.advance_until(lambda: False, within=10)
    assert clock.monotonic() == 1000.0 + 610.0


async def test_advance_until_with_a_step() -> None:
    clock = FakeClock()
    passed = await clock.advance_until(lambda: clock.monotonic() >= 1002.5, within=10, step=1)
    assert passed == 3.0


async def test_schedule_uses_the_loop_on_the_system_clock() -> None:
    ran = asyncio.Event()
    timer = schedule(SystemClock(), 0.01, ran.set)
    await asyncio.wait_for(ran.wait(), 1)
    timer.cancel()  # harmless once it ran


async def test_schedule_uses_the_fake_clock_on_a_fake_clock() -> None:
    clock = FakeClock()
    ran: list[bool] = []
    schedule(clock, 5, lambda: ran.append(True))
    await clock.advance(4)
    assert ran == []
    await clock.advance(1)
    assert ran == [True]


async def test_a_scaled_clock_runs_faster_and_scales_timers() -> None:
    clock = ScaledClock(100)
    assert_implements(ScaledClock, ports.Clock)
    start, wall = clock.monotonic(), clock.now()
    await clock.sleep(2)  # 20 ms of real time
    assert clock.monotonic() - start >= 2
    assert (clock.now() - wall).total_seconds() >= 2
    ran = asyncio.Event()
    schedule(clock, 3, ran.set)
    await asyncio.wait_for(ran.wait(), 1)
    with pytest.raises(ValueError):
        ScaledClock(0)
