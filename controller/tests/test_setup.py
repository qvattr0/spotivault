"""The setup wizard's state: GET /api/setup, POST /api/setup/tos and /restart, and the service's
hooks for other modules (owner: settings-storage-setup)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from contract import assert_response, assert_schema, openapi
from spotivault.api.models import Checklist, ClientStatus, Setup
from spotivault.errors import ApiError
from spotivault.fake.clock import FakeClock
from spotivault.ports import VolumeInfo
from spotivault.services import Services

GB = 1_000_000_000
EXAMPLES = openapi()["components"]["examples"]
MIDWAY = EXAMPLES["SetupMidway"]["value"]
CHECKLIST = EXAMPLES["ChecklistM1"]["value"]
CLIENT = EXAMPLES["ClientLoggedIn"]["value"]
ACTIVE_RUN = (
    "INSERT INTO runs (kind, trigger, state, started_at) "
    "VALUES ('run', 'run_now', 'running', '2026-11-15T00:00:00.000Z')"
)


class World:
    """The facts behind the checked steps, set by each test. It stands in for the client module
    (`services.client`: status() for steps 2 and 3, checklist() for step 4, add_listener()) and
    for /music (step 6)."""

    def __init__(self, services: Services, monkeypatch: pytest.MonkeyPatch) -> None:
        self.services = services
        self.installed: str | None = None
        self.install_error: str | None = None  # the last install failed with this message
        self.logged_in = False
        self.ready = False
        self.checklist_error: Exception | None = None
        self.listeners: list[Callable[[], Awaitable[None]]] = []
        self.music: dict[str, Any] = {"mounted": True, "writable": True, "free_bytes": 500 * GB}
        self.storage_error: Exception | None = None
        monkeypatch.setattr(services, "client", self)
        monkeypatch.setattr(services.ports.storage, "volume", self._volume)

    def all_good(self) -> None:
        self.installed = "1.3.4.258"
        self.logged_in = True
        self.ready = True

    async def status(self) -> ClientStatus:
        install = {**CLIENT["install"], "version": self.installed}
        if self.installed is None:
            install.update(state="not_started", started_at=None, finished_at=None, log_tail=[])
        if self.install_error is not None:
            install["state"] = "failed"
            install["error"] = {"code": "network", "message": self.install_error}
        return ClientStatus.model_validate(
            {
                **CLIENT,
                "installed": self.installed is not None,
                "version": self.installed,
                "logged_in": self.logged_in,
                "install": install,
            }
        )

    async def checklist(self) -> Checklist:
        if self.checklist_error is not None:
            raise self.checklist_error
        return Checklist.model_validate({**CHECKLIST, "ready": self.ready})

    def add_listener(self, fn: Callable[[], Awaitable[None]]) -> None:
        self.listeners.append(fn)

    async def notify(self) -> None:
        """What the client module does after its status or checklist changed."""
        for fn in self.listeners:
            await fn()

    async def _volume(self, path: Path) -> VolumeInfo:
        if self.storage_error is not None:
            raise self.storage_error
        values: dict[str, Any] = {"mounted": True, "writable": True, "free_bytes": 500 * GB}
        if path == self.services.config.music_dir:
            values = self.music
        return VolumeInfo(path=path, exists=True, total_bytes=1000 * GB, **values)


@pytest.fixture
def world(services: Services, monkeypatch: pytest.MonkeyPatch) -> World:
    """Request it before `client`, so it's in place when the app starts."""
    return World(services, monkeypatch)


class Published(list[dict[str, Any]]):
    """Every setup.state event's data, in order; `arrived` is set when one comes."""

    def __init__(self) -> None:
        super().__init__()
        self.arrived = asyncio.Event()

    async def wait_until(self, done: Callable[[dict[str, Any]], bool]) -> None:
        """Until the latest event matches `done`. Wrap it in a timeout."""
        while not (self and done(self[-1])):
            self.arrived.clear()
            await self.arrived.wait()


@pytest.fixture
def published(services: Services, monkeypatch: pytest.MonkeyPatch) -> Published:
    events = Published()
    publish = services.bus.publish

    def record(type: str, data: Any) -> Any:
        event = publish(type, data)
        if type == "setup.state":
            events.append(event.data)
            events.arrived.set()
        return event

    monkeypatch.setattr(services.bus, "publish", record)
    return events


def states(setup: dict[str, Any] | Setup) -> dict[str, str]:
    if isinstance(setup, Setup):
        setup = setup.model_dump(mode="json")
    return {step["id"]: step["state"] for step in setup["steps"]}


async def get_setup(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get("/api/setup")
    assert response.status_code == 200
    assert_response(response, "/api/setup")
    return response.json()


async def finish_setup(world: World, client: httpx.AsyncClient, services: Services) -> Setup:
    world.all_good()
    await client.post("/api/setup/tos", json={"understood": True})
    await services.setup.mark_done("webapi")
    return await services.setup.complete()


# --- Reading the state ---------------------------------------------------------------------------


async def test_a_fresh_controller(world: World, client: httpx.AsyncClient) -> None:
    body = await get_setup(client)
    assert states(body) == {
        "tos": "active",
        "client": "todo",
        "login": "todo",
        "client_settings": "todo",
        "webapi": "todo",
        "output": "done",  # /music is fine from the start, so step 6 is ticked off already
        "playlists": "todo",
        "albums": "todo",
        "done": "todo",
    }
    assert body["first_unfinished"] == "tos"
    assert body["completed"] is False
    assert body["tos_acknowledged_at"] is None


async def test_the_contract_example_midway(
    world: World, client: httpx.AsyncClient, fake_clock: FakeClock
) -> None:
    fake_clock.set_now(datetime(2026, 11, 15, 9, 12, 44, tzinfo=UTC))
    world.storage_error = OSError("the volume check can't run")  # step 6 keeps its state
    assert (await client.post("/api/setup/tos", json={"understood": True})).status_code == 200
    world.installed = "1.3.4.258"
    world.logged_in = True
    body = await get_setup(client)
    for step in body["steps"]:
        assert step.pop("message") is None
    assert body == MIDWAY


async def test_step_2_failed_install_then_installed(
    world: World, client: httpx.AsyncClient
) -> None:
    world.install_error = "Spotify's repository didn't answer."
    body = await get_setup(client)
    assert body["steps"][1] == {
        "id": "client",
        "state": "failed",
        "message": "Spotify's repository didn't answer.",
    }
    world.install_error = None
    world.installed = "1.3.4.258"
    assert states(await get_setup(client))["client"] == "done"


async def test_steps_2_to_4_turn_done_from_the_live_checks(
    world: World, client: httpx.AsyncClient
) -> None:
    await client.post("/api/setup/tos", json={"understood": True})
    assert (await get_setup(client))["first_unfinished"] == "client"
    world.installed = "1.3.4.258"
    assert (await get_setup(client))["first_unfinished"] == "login"
    world.logged_in = True
    assert (await get_setup(client))["first_unfinished"] == "client_settings"
    world.ready = True
    body = await get_setup(client)
    assert body["first_unfinished"] == "webapi"
    assert states(body)["webapi"] == "active"


async def test_a_check_that_cant_run_keeps_the_step_and_is_logged_once(
    world: World, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    world.checklist_error = OSError("the prefs file can't be read")
    await get_setup(client)
    body = await get_setup(client)
    assert states(body)["client_settings"] == "todo"
    warnings = [r for r in caplog.records if "can't read the client checklist" in r.getMessage()]
    assert len(warnings) == 1


async def test_step_6_follows_the_storage_check(
    world: World, client: httpx.AsyncClient, published: Published
) -> None:
    world.music = {"mounted": True, "writable": False, "free_bytes": 500 * GB}
    storage = await client.get("/api/storage")
    assert storage.json()["music"]["error"] == "not_writable"
    output = published[-1]["steps"][5]
    assert output["state"] == "failed"
    assert "can't write to" in output["message"]
    world.music = {"mounted": True, "writable": True, "free_bytes": 1 * GB}
    await client.get("/api/storage")
    assert "has 1.0 GB free" in published[-1]["steps"][5]["message"]
    world.music = {"mounted": True, "writable": True, "free_bytes": 500 * GB}
    await client.get("/api/storage")
    assert published[-1]["steps"][5] == {"id": "output", "state": "done", "message": None}


async def test_step_7_is_the_saved_choice(
    world: World, client: httpx.AsyncClient, published: Published
) -> None:
    await client.put("/api/settings", json={"write_m3u": False})
    assert states(await get_setup(client))["playlists"] == "todo"
    await client.put("/api/settings", json={"auto_track_owned": False})
    assert states(published[-1])["playlists"] == "done"
    assert states(await get_setup(client))["playlists"] == "done"


# --- Step 1 --------------------------------------------------------------------------------------


async def test_the_terms_keep_their_first_timestamp(
    world: World, client: httpx.AsyncClient, fake_clock: FakeClock
) -> None:
    first = await client.post("/api/setup/tos", json={"understood": True})
    assert first.status_code == 200
    assert_response(first, "/api/setup/tos")
    assert first.json()["tos_acknowledged_at"] == "2026-11-15T00:00:00Z"
    assert states(first.json())["tos"] == "done"
    await fake_clock.advance(3600)
    again = await client.post("/api/setup/tos", json={"understood": True})
    assert again.json()["tos_acknowledged_at"] == "2026-11-15T00:00:00Z"


@pytest.mark.parametrize("body", [{"understood": False}, {}, {"understood": True, "x": 1}])
async def test_the_terms_need_understood_true(
    world: World, client: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    response = await client.post("/api/setup/tos", json=body)
    assert response.status_code == 422
    assert_response(response, "/api/setup/tos")
    assert response.json()["error"]["code"] == "validation_failed"
    assert (await get_setup(client))["tos_acknowledged_at"] is None


# --- Steps marked by other modules, and completing -----------------------------------------------


async def test_marked_steps(world: World, client: httpx.AsyncClient, services: Services) -> None:
    setup = await services.setup.mark_failed("webapi", "The container's client isn't listed.")
    assert setup.steps[4].model_dump() == {
        "id": "webapi",
        "state": "failed",
        "message": "The container's client isn't listed.",
    }
    assert states(await services.setup.mark_done("webapi"))["webapi"] == "done"
    assert states(await services.setup.mark_failed("webapi", "late"))["webapi"] == "done"
    assert states(await services.setup.mark_done("albums"))["albums"] == "done"
    with pytest.raises(ValueError):
        await services.setup.mark_done("login")
    with pytest.raises(ValueError):
        await services.setup.mark_done("done")


async def test_complete_needs_steps_1_to_6(
    world: World, client: httpx.AsyncClient, services: Services
) -> None:
    world.installed = "1.3.4.258"
    with pytest.raises(ApiError) as refused:
        await services.setup.complete()
    assert refused.value.status == 409
    assert refused.value.code == "setup_incomplete"
    assert refused.value.details == {"steps": ["tos", "login", "client_settings", "webapi"]}
    assert await services.setup.is_complete() is False


async def test_complete_through_the_api(
    world: World, client: httpx.AsyncClient, services: Services, published: Published
) -> None:
    response = await client.post("/api/setup/complete")
    assert response.status_code == 409
    assert_response(response, "/api/setup/complete")
    assert response.json()["error"]["code"] == "setup_incomplete"
    assert response.json()["error"]["details"]["steps"][0] == "tos"

    world.all_good()
    await client.post("/api/setup/tos", json={"understood": True})
    await services.setup.mark_done("webapi")
    response = await client.post("/api/setup/complete")
    assert response.status_code == 200
    assert_response(response, "/api/setup/complete")
    body = response.json()
    assert body["completed"] is True
    assert body["first_unfinished"] is None
    assert published[-1] == body

    again = await client.post("/api/setup/complete")
    assert again.status_code == 200
    assert again.json() == body


async def test_complete(
    world: World,
    client: httpx.AsyncClient,
    services: Services,
    published: Published,
) -> None:
    setup = await finish_setup(world, client, services)
    assert set(states(setup).values()) == {"done"}
    assert setup.completed is True
    assert setup.first_unfinished is None
    assert published[-1] == setup.model_dump(mode="json")
    assert await services.setup.is_complete() is True
    assert_schema("Setup", await get_setup(client))


async def test_done_is_sticky(world: World, client: httpx.AsyncClient, services: Services) -> None:
    world.logged_in = True
    assert states(await get_setup(client))["login"] == "done"
    world.logged_in = False
    assert states(await get_setup(client))["login"] == "done"
    await finish_setup(world, client, services)
    world.installed = None
    world.music = {"mounted": False, "writable": False, "free_bytes": None}
    body = await get_setup(client)
    assert body["completed"] is True
    assert set(states(body).values()) == {"done"}


# --- Run setup again -----------------------------------------------------------------------------


async def test_run_setup_again(
    world: World,
    client: httpx.AsyncClient,
    services: Services,
    published: Published,
) -> None:
    await finish_setup(world, client, services)
    response = await client.post("/api/setup/restart")
    assert response.status_code == 200
    assert_response(response, "/api/setup/restart")
    body = response.json()
    assert body["first_unfinished"] == "client"
    assert body["completed"] is False
    assert body["tos_acknowledged_at"] == "2026-11-15T00:00:00Z"
    assert states(body) == {
        "tos": "done",
        "client": "active",
        "login": "todo",
        "client_settings": "todo",
        "webapi": "todo",
        "output": "todo",
        "playlists": "todo",
        "albums": "todo",
        "done": "todo",
    }
    assert published[-1] == body
    assert await services.setup.is_complete() is False
    # The live checks turn the checked steps done again; the others wait for their actions.
    again = await get_setup(client)
    assert again["first_unfinished"] == "webapi"
    done = [step for step, state in states(again).items() if state == "done"]
    assert done == ["tos", "client", "login", "client_settings", "output"]
    # Nothing else was deleted.
    assert (await client.get("/api/settings")).status_code == 200


async def test_run_setup_again_is_refused_during_a_run(
    world: World, client: httpx.AsyncClient, services: Services
) -> None:
    await services.store.execute(ACTIVE_RUN)
    response = await client.post("/api/setup/restart")
    assert response.status_code == 409
    assert_response(response, "/api/setup/restart")
    assert response.json()["error"]["code"] == "run_active"


# --- Events, the client's notifications and the hello -------------------------------------------


async def test_setup_state_is_published_once_per_change(
    world: World, client: httpx.AsyncClient, published: Published
) -> None:
    first = await get_setup(client)
    await get_setup(client)
    assert published == [first]
    world.installed = "1.3.4.258"
    second = await get_setup(client)
    await get_setup(client)
    assert published == [first, second]
    for data in published:
        assert_schema("Setup", data)


async def test_a_client_change_refreshes_the_steps(
    world: World, client: httpx.AsyncClient, published: Published
) -> None:
    await get_setup(client)
    assert len(world.listeners) == 1, "setup listens to the client module from start-up"
    world.logged_in = True
    await world.notify()
    await asyncio.wait_for(published.wait_until(lambda s: states(s)["login"] == "done"), 2)


async def test_the_client_can_notify_during_a_refresh(
    world: World, client: httpx.AsyncClient
) -> None:
    """The client module notifies its listeners from inside checklist(), which refresh() calls:
    that mustn't wait on refresh()'s own lock."""
    checklist = world.checklist

    async def notifying_checklist() -> Checklist:
        await world.notify()
        return await checklist()

    world.checklist = notifying_checklist  # type: ignore[method-assign]
    world.ready = True
    body = await asyncio.wait_for(get_setup(client), 2)
    assert states(body)["client_settings"] == "done"


async def test_the_hello_shows_the_stored_state_without_checks(
    world: World, client: httpx.AsyncClient, services: Services, published: Published
) -> None:
    world.all_good()
    hello = await services.setup.snapshot()
    assert states(hello)["client"] == "todo"
    assert published == []
    await get_setup(client)
    assert states(await services.setup.snapshot())["client"] == "done"


async def test_the_hello_never_raises(services: Services, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    setup = await services.setup.snapshot()  # the store isn't open
    assert setup.first_unfinished == "tos"
    assert_schema("Setup", setup.model_dump(mode="json"))
