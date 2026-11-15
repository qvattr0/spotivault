"""Shared fixtures for every controller test.

- `config_dir`, `music_dir`, `web_root`: empty temporary folders standing in for /config, /music
  and the built UI. `env` and `config` point the controller at them, in fake mode.
- `fake_clock`: a FakeClock (time moves only with `await fake_clock.advance(s)`).
- `services`, `app`: the controller built on fake ports and the fake clock, not started.
- `running_app`: the app with its lifespan entered (store open, background tasks running).
- `client`: an httpx.AsyncClient that calls the running app in-process (ASGITransport).
- For WebSockets, see tests/asgi_ws.py; for checking bodies against openapi.yaml, tests/contract.py.

Every test's event loop runs in asyncio debug mode, and a callback that runs longer than 100 ms
fails the test (design.md § Stack): something blocked the loop. Mark a test that blocks on
purpose with `@pytest.mark.allow_slow_callbacks`.

Tests never touch the network, real Spotify, or the running containers.
"""

import gc
import logging
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from spotivault.app import create_app
from spotivault.config import Config, load_config
from spotivault.fake.clock import FakeClock
from spotivault.services import Services, build_services

SLOW_CALLBACKS = pytest.StashKey["SlowCallbackLog"]()


def pytest_configure(config: pytest.Config) -> None:
    # pyproject.toml sets asyncio_debug = true; this keeps debug mode on even if it's run with
    # another ini file. pytest-asyncio reads the option when it creates each test's loop.
    config.option.asyncio_debug = True


def pytest_collection_finish(session: pytest.Session) -> None:
    # Everything collection built (modules, the parsed contract, the vectors) lives for the whole
    # run. Freezing it keeps the garbage collector's full passes short: under load, a pass over it
    # took 50-70 ms, enough to push a trivial callback past the 100 ms limit below.
    gc.collect()
    gc.freeze()


# --- Blocked-loop detection --------------------------------------------------------------------


class SlowCallbackLog(logging.Handler):
    """Collects asyncio debug mode's "Executing <handle> took 0.150 seconds" warnings, which it
    logs for any callback slower than loop.slow_callback_duration (0.1 s, the default)."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []
        self.reported = 0

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if message.startswith("Executing ") and " took " in message:
            self.messages.append(message)


def _blocked_loop_failure(messages: list[str]) -> str:
    return "the event loop was blocked for over 100 ms (design.md § Stack):\n  " + "\n  ".join(
        messages
    )


@pytest.fixture(autouse=True)
def fail_on_slow_callbacks(request: pytest.FixtureRequest) -> Iterator[SlowCallbackLog]:
    """Watches the asyncio logger for the whole test. The call phase is checked by the hook below,
    so a slow callback fails the test itself; one during teardown fails it here."""
    watch = SlowCallbackLog()
    logger = logging.getLogger("asyncio")
    logger.addHandler(watch)
    request.node.stash[SLOW_CALLBACKS] = watch
    try:
        yield watch
    finally:
        logger.removeHandler(watch)
    late = watch.messages[watch.reported :]
    if late and request.node.get_closest_marker("allow_slow_callbacks") is None:
        pytest.fail(_blocked_loop_failure(late), pytrace=False)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Iterator[None]:
    result = yield
    watch = item.stash.get(SLOW_CALLBACKS, None)
    if (
        watch is not None
        and watch.messages
        and item.get_closest_marker("allow_slow_callbacks") is None
    ):
        watch.reported = len(watch.messages)
        pytest.fail(_blocked_loop_failure(watch.messages), pytrace=False)
    return result


# --- Folders and config ------------------------------------------------------------------------


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    path = tmp_path / "config"
    path.mkdir()
    return path


@pytest.fixture
def music_dir(tmp_path: Path) -> Path:
    path = tmp_path / "music"
    path.mkdir()
    return path


@pytest.fixture
def web_root(tmp_path: Path) -> Path:
    path = tmp_path / "web"
    path.mkdir()
    return path


@pytest.fixture
def env(config_dir: Path, music_dir: Path, web_root: Path, tmp_path: Path) -> dict[str, str]:
    """The environment the controller sees in tests. Change it before `config` is built."""
    return {
        "TZ": "UTC",
        "UMASK": "000",
        "DEVICE_NAME": "spotivault-test",
        "SPOTIVAULT_FAKE": "1",
        "SPOTIVAULT_CONFIG_DIR": str(config_dir),
        "SPOTIVAULT_MUSIC_DIR": str(music_dir),
        "SPOTIVAULT_WEB_ROOT": str(web_root),
        "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
        # The test clients' Host. A dotted name outside the home-network ones, so web/guard.py
        # serves it only through this setting.
        "SPOTIVAULT_ALLOWED_HOSTS": "spotivault.test",
    }


@pytest.fixture
def config(env: dict[str, str]) -> Config:
    return load_config(env)


# --- The controller ----------------------------------------------------------------------------


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def services(config: Config, fake_clock: FakeClock) -> Services:
    """The controller's parts on fake ports and the fake clock. Built outside the event loop:
    building the app's models and routes takes longer than a callback may."""
    return build_services(config, clock=fake_clock)


@pytest.fixture
def app(services: Services) -> FastAPI:
    return create_app(services)


@pytest.fixture
async def running_app(app: FastAPI, services: Services) -> AsyncIterator[FastAPI]:
    """The app with its lifespan running. A background task that failed fails the test."""
    async with app.router.lifespan_context(app):
        yield app
    if services.fatal_errors:
        pytest.fail(f"a background task failed: {services.fatal_errors!r}")


@pytest.fixture
async def client(running_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Calls the running app in-process: `await client.get("/api/health")`."""
    transport = httpx.ASGITransport(app=running_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://spotivault.test") as http:
        yield http
