"""services.py: the lifecycle, and no lost task errors (design.md § Stack)."""

import asyncio

from fastapi import FastAPI

from spotivault.clock import SystemClock
from spotivault.config import load_config
from spotivault.fake import world_of
from spotivault.fake.clock import ScaledClock
from spotivault.services import Services, build_services


async def test_a_failing_background_task_is_logged_and_stops_the_controller(
    services: Services, app: FastAPI
) -> None:
    stopped: list[BaseException] = []
    services.on_fatal = stopped.append

    async def broken() -> None:
        raise RuntimeError("boom")

    services.add_background("broken", broken)
    async with app.router.lifespan_context(app):
        for _ in range(10):
            await asyncio.sleep(0)
        assert [str(e) for e in stopped] == ["boom"]
        assert services.fatal_errors == stopped
        # The rest keeps serving until the server acts on on_fatal.
        assert services.store.is_open
    services.fatal_errors.clear()


async def test_background_tasks_are_cancelled_at_shutdown(services: Services, app: FastAPI) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def forever() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    services.add_background("forever", forever)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(started.wait(), 1)
    assert cancelled.is_set()
    assert services.fatal_errors == []


def test_ports_are_fake_in_fake_mode(services: Services) -> None:
    assert type(services.ports.mpris).__module__.startswith("spotivault.fake")
    assert type(services.ports.webapi).__module__.startswith("spotivault.fake")
    assert services.clock is services.ports.clock
    assert world_of(services.ports).scenario == "fresh"  # on the tests' FakeClock


def test_fake_scenario_and_speed_come_from_the_environment(env: dict[str, str]) -> None:
    services = build_services(load_config(env))
    assert world_of(services.ports).scenario == "demo"  # the dev server's default
    assert isinstance(services.clock, SystemClock)

    env |= {"SPOTIVAULT_FAKE_SCENARIO": "wizard", "SPOTIVAULT_FAKE_SPEED": "20"}
    services = build_services(load_config(env))
    assert world_of(services.ports).scenario == "wizard"
    assert isinstance(services.clock, ScaledClock)
    assert services.clock.factor == 20
