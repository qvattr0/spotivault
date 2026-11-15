"""services.py: the lifecycle, and no lost task errors (design.md § Stack)."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
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


async def test_the_http_ports_close_after_the_background_tasks_have_stopped(
    services: Services, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    started = asyncio.Event()

    async def refreshing() -> None:  # a catalog refresh still going at shutdown
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)  # still finishing, after it was cancelled
            order.append("task stopped")

    async def hook() -> None:
        order.append("shutdown hook")

    def closing(name: str) -> Callable[[], Awaitable[None]]:
        async def aclose() -> None:
            order.append(f"{name} closed")

        return aclose

    monkeypatch.setattr(services.ports.webapi, "aclose", closing("webapi"))
    monkeypatch.setattr(services.ports.cdn, "aclose", closing("cdn"))
    services.add_background("refreshing", refreshing)
    services.add_shutdown("hook", hook)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(started.wait(), 1)
    assert order == ["shutdown hook", "task stopped", "webapi closed", "cdn closed"]
    assert not services.store.is_open


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
