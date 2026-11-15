"""fake/client.py: the simulated client's install, process, login and prefs."""

import asyncio
from contextlib import aclosing

import pytest

from fake_helpers import make_world
from portcheck import assert_implements
from spotivault import ports
from spotivault.config import Config
from spotivault.fake import FakeWorld
from spotivault.fake.client import (
    FAILURES,
    FAKE_VERSION,
    FRESH_PREFS,
    GOOD_PREFS,
    FakeClientControl,
)
from spotivault.fake.clock import FakeClock
from spotivault.ports import InstallInProgress, InstallProgress


@pytest.fixture
def world(config: Config, fake_clock: FakeClock) -> FakeWorld:
    return make_world(config, fake_clock, scenario="fresh")


async def run_install(
    world: FakeWorld, clock: FakeClock, **kwargs: object
) -> tuple[list[InstallProgress], float]:
    """Runs an install to its end, moving the fake clock; returns its lines and duration."""
    lines: list[InstallProgress] = []

    async def consume() -> None:
        async with aclosing(world.client.install(**kwargs)) as progress:  # type: ignore[arg-type]
            async for line in progress:
                lines.append(line)

    task = asyncio.ensure_future(consume())
    took = await clock.advance_until(task.done, within=120)
    await task
    return lines, took


def test_it_implements_the_port() -> None:
    assert_implements(FakeClientControl, ports.ClientControl)


async def test_an_install_prints_spotify_installs_lines_in_about_18_s(
    world: FakeWorld, fake_clock: FakeClock
) -> None:
    lines, took = await run_install(world, fake_clock)
    stages = [line.stage for line in lines]
    assert stages[0] == "release" and stages[-1] == "done"
    assert stages[1:-5] == ["download"] * (len(stages) - 6)
    assert stages[-5:-1] == ["verify", "unpack", "libraries", "switch"]
    percents = [line.percent for line in lines if line.stage == "download"]
    assert percents[0] == 0 and percents[-1] == 100 and percents == sorted(percents)
    assert all(line.total == 179_306_496 for line in lines if line.stage == "download")
    assert 17 <= took <= 19  # Q13: 17.6 s on Docker Desktop
    done = lines[-1]
    assert (done.version, done.previous, done.changed) == (FAKE_VERSION, "", True)
    assert done.raw == {
        "stage": "done",
        "message": f"Installed Spotify {FAKE_VERSION}",
        "version": FAKE_VERSION,
        "previous": "",
        "changed": True,
    }
    assert await world.client.installed_version() == FAKE_VERSION


async def test_the_client_starts_after_the_install_logged_out(
    world: FakeWorld, fake_clock: FakeClock
) -> None:
    await run_install(world, fake_clock)
    assert not await world.client.is_running()
    await fake_clock.advance(world.client.start_delay_s)
    assert await world.client.is_running()
    signals = await world.client.login_signals()
    assert (signals.user_folder, signals.window_title) == (False, "Spotify")
    assert await world.mpris.owner_present()  # a logged-out client is on the bus too (Q2)
    assert await world.client.prefs() is None


async def test_the_install_compresses(world: FakeWorld, fake_clock: FakeClock) -> None:
    world.client.install_time_scale = 0.1
    _, took = await run_install(world, fake_clock)
    assert took < 2


@pytest.mark.parametrize("where", sorted(FAILURES))
async def test_an_install_fails_where_told(
    where: str, world: FakeWorld, fake_clock: FakeClock
) -> None:
    world.client.fail_install_at = where
    lines, _ = await run_install(world, fake_clock)
    error = lines[-1]
    step, message = FAILURES[where]
    assert (error.stage, error.step, error.message) == ("error", step, message)
    assert error.raw["step"] == step
    assert await world.client.installed_version() is None


async def test_installing_the_installed_version_changes_nothing(
    world: FakeWorld, fake_clock: FakeClock
) -> None:
    world.client.installed()
    lines, took = await run_install(world, fake_clock)
    assert [line.stage for line in lines] == ["release", "done"]
    assert lines[-1].changed is False and took < 1
    lines, _ = await run_install(world, fake_clock, force=True)
    assert lines[-1].changed is True


async def test_an_older_version_and_an_unknown_one(world: FakeWorld, fake_clock: FakeClock) -> None:
    world.client.installed()
    lines, _ = await run_install(world, fake_clock, version="1.2.63.394")
    assert (lines[-1].version, lines[-1].previous) == ("1.2.63.394", FAKE_VERSION)
    lines, _ = await run_install(world, fake_clock, version="9.9.9")
    assert (lines[-1].stage, lines[-1].step) == ("error", "packages")


async def test_only_one_install_at_a_time(world: FakeWorld, fake_clock: FakeClock) -> None:
    first = world.client.install()
    await anext(first)
    with pytest.raises(InstallInProgress):
        await anext(world.client.install())
    await first.aclose()
    second = world.client.install()  # the lock is free again
    assert (await anext(second)).stage == "release"
    await second.aclose()


async def test_login_signals_and_prefs(world: FakeWorld, fake_clock: FakeClock) -> None:
    world.client.installed()
    world.client.start()
    world.client.log_in(prefs=FRESH_PREFS)
    signals = await world.client.login_signals()
    assert (signals.user_folder, signals.window_title) == (True, "Spotify Premium")
    assert await world.client.prefs() == FRESH_PREFS
    world.client.set_pref("audio.equalizer_v2", "true")
    assert (await world.client.prefs() or {})["audio.equalizer_v2"] == "true"
    world.client.set_pref("audio.equalizer_v2", None)  # off again: the key goes
    world.client.apply_good_prefs()
    assert await world.client.prefs() == GOOD_PREFS
    world.client.prefs_unreadable = True
    assert await world.client.prefs() is None
    world.client.log_out()
    signals = await world.client.login_signals()
    assert (signals.user_folder, signals.window_title) == (True, "Spotify")  # the folder stays


async def test_a_restart_returns_once_the_client_is_gone_and_it_comes_back_logged_in(
    config: Config, fake_clock: FakeClock
) -> None:
    world = make_world(config, fake_clock)  # demo: installed and logged in
    await world.client.restart()
    assert not await world.client.is_running() and world.client.restarts == 1
    await fake_clock.advance(world.client.restart_delay_s)
    assert await world.client.is_running()
    assert (await world.client.login_signals()).window_title == "Spotify Premium"


async def test_s6_restarts_a_crashed_client_but_not_a_stopped_one(
    config: Config, fake_clock: FakeClock
) -> None:
    world = make_world(config, fake_clock)
    world.client.crash()
    await fake_clock.advance(world.client.restart_delay_s)
    assert await world.client.is_running()
    world.client.stop()
    await fake_clock.advance(60)
    assert not await world.client.is_running()
    world.client.running = True
    assert await world.client.is_running()


async def test_auto_login_for_walking_the_wizard(config: Config, fake_clock: FakeClock) -> None:
    world = make_world(config, fake_clock, scenario="wizard")
    await run_install(world, fake_clock)
    await fake_clock.advance(world.client.start_delay_s)
    assert (await world.client.login_signals()).window_title == "Spotify"
    await fake_clock.advance(20)
    assert (await world.client.login_signals()).window_title == "Spotify Premium"
    assert await world.client.prefs() == FRESH_PREFS
    await fake_clock.advance(30)
    assert await world.client.prefs() == GOOD_PREFS


async def test_signals_can_be_fixed_by_hand(world: FakeWorld) -> None:
    world.client.signals = ports.LoginSignals(user_folder=True, window_title="Spotify Free")
    assert (await world.client.login_signals()).window_title == "Spotify Free"
    world.client.signals = None
    assert (await world.client.login_signals()).window_title is None
