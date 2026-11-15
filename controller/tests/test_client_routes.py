"""routers/client.py: the client endpoints and the checklist confirm, against openapi.yaml, on the
stand-in client of tests/client_stubs.py."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from asgi_ws import websocket_connect
from client_stubs import GOOD_PREFS, HAPPY, LOGGED_IN, StubClient, run_install, use_stubs
from contract import assert_response, assert_schema
from spotivault.fake.clock import FakeClock
from spotivault.services import Services


@pytest.fixture
async def stub(
    services: Services, fake_clock: FakeClock, app: FastAPI
) -> AsyncIterator[StubClient]:
    """The app with its lifespan running, on the stand-in client."""
    client, _ = use_stubs(services, fake_clock)
    async with app.router.lifespan_context(app):
        await fake_clock.settle()
        yield client
    assert services.fatal_errors == []


@pytest.fixture
async def http(app: FastAPI, stub: StubClient) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://spotivault.test") as http:
        yield http


async def test_get_status(http: httpx.AsyncClient, stub: StubClient, services: Services) -> None:
    stub.version, stub.running, stub.signals = "1.3.4.258", True, LOGGED_IN
    await services.client.refresh()
    response = await http.get("/api/client/status")
    assert response.status_code == 200
    assert_response(response, "/api/client/status")
    body = response.json()
    assert (body["installed"], body["version"], body["logged_in"]) == (True, "1.3.4.258", True)


async def test_install_is_accepted_once(
    http: httpx.AsyncClient, stub: StubClient, services: Services
) -> None:
    response = await http.post("/api/client/install")
    assert response.status_code == 202
    assert_response(response, "/api/client/install")
    assert response.json()["state"] == "installing"

    again = await http.post("/api/client/install")
    assert again.status_code == 409
    assert_response(again, "/api/client/install")
    assert again.json()["error"]["code"] == "install_in_progress"

    await run_install(services, stub, HAPPY)
    await services.client.refresh()
    status = (await http.get("/api/client/status")).json()
    assert (status["installed"], status["install"]["state"]) == (True, "installed")


async def test_install_and_restart_are_refused_during_a_run(
    http: httpx.AsyncClient, services: Services, stub: StubClient
) -> None:
    await services.client.set_run_active(True)
    for path in ("/api/client/install", "/api/client/restart"):
        response = await http.post(path)
        assert response.status_code == 409
        assert_response(response, path)
        assert response.json()["error"]["code"] == "run_active"
    status = (await http.get("/api/client/status")).json()
    assert status["restartable"] is False
    assert (stub.installs, stub.restarts) == (0, 0)


async def test_restart(http: httpx.AsyncClient, stub: StubClient, fake_clock: FakeClock) -> None:
    response = await http.post("/api/client/restart")
    assert response.status_code == 202
    assert_response(response, "/api/client/restart")
    await fake_clock.settle()
    assert stub.restarts == 1


async def test_checklist_and_confirm(http: httpx.AsyncClient, stub: StubClient) -> None:
    response = await http.get("/api/client/checklist")
    assert response.status_code == 200
    assert_response(response, "/api/client/checklist")
    assert response.json()["ready"] is False

    stub.prefs_values = dict(GOOD_PREFS)
    response = await http.post(
        "/api/setup/checklist/confirm", json={"rows": {"crossfade": True, "gapless": True}}
    )
    assert response.status_code == 200
    assert_response(response, "/api/setup/checklist/confirm")
    body = response.json()
    assert body["ready"] is True
    ticked = {row["id"]: row["confirmed"] for row in body["rows"] if row["check"] == "confirm"}
    assert ticked == {"crossfade": True, "gapless": True, "autoplay": False}


async def test_confirm_refuses_rows_that_arent_confirm_rows(http: httpx.AsyncClient) -> None:
    # The contract's own example ticks equalizer and mono, which web-ui.md makes Auto rows.
    response = await http.post(
        "/api/setup/checklist/confirm",
        json={"rows": {"crossfade": True, "equalizer": True, "mono": True}},
    )
    assert response.status_code == 422
    assert_response(response, "/api/setup/checklist/confirm")
    assert response.json()["error"]["code"] == "validation_failed"
    assert response.json()["error"]["details"] == {"field": "rows.equalizer"}

    unknown = await http.post("/api/setup/checklist/confirm", json={"rows": {"bass": True}})
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "validation_failed"


async def test_install_progress_reaches_the_event_stream(
    app: FastAPI, http: httpx.AsyncClient, stub: StubClient
) -> None:
    async with websocket_connect(app, "/api/events") as ws:
        hello = await ws.receive_json()
        assert_schema("ClientStatus", hello["data"]["client"])
        await http.post("/api/client/install")
        await stub.send(HAPPY[0])
        events = []
        while len(events) < 3:
            event = await ws.receive_json()
            if event["type"].startswith("client."):
                events.append(event)
    assert [e["type"] for e in events] == ["client.install", "client.status", "client.install"]
    assert (events[0]["data"]["state"], events[0]["data"]["phase"]) == ("installing", None)
    assert events[1]["data"]["install"]["state"] == "installing"
    assert (events[2]["data"]["phase"], events[2]["data"]["log_line"]) == (
        "release",
        "Checking Spotify's repository",
    )
