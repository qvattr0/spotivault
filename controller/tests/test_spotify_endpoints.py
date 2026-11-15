"""The spotify endpoints (openapi.yaml tag `spotify`) over HTTP, each answer checked against the
contract, on the fake ports. The service's own rules are in test_connection.py."""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from contract import assert_response
from spotify_mock import SpotifyMock
from spotivault.fake import world_of
from spotivault.ports import SpotifyUnavailable
from spotivault.services import Services
from spotivault.webapi.client import SpotifyWebApi

CLIENT_ID = "0123456789abcdef0123456789abcdef"
REDIRECT = "http://127.0.0.1:8888/callback"


async def test_devices_answers_503_when_spotify_does_not_answer(
    client: httpx.AsyncClient, services: Services
) -> None:
    await client.post("/api/spotify/app", json={"client_id": CLIENT_ID})
    state = await _start(client)
    await _finish(client, f"{REDIRECT}?code=ok-code&state={state}")
    world_of(services.ports).webapi.failures.append(
        SpotifyUnavailable("Spotify didn't answer", status=503)
    )
    response = await client.get("/api/spotify/devices")
    assert response.status_code == 503
    assert_response(response, "/api/spotify/devices")
    assert response.json()["error"]["code"] == "spotify_unavailable"


@pytest.fixture(autouse=True)
def no_refresh(services: Services, monkeypatch: pytest.MonkeyPatch) -> None:
    """Connecting asks for a catalog refresh; the catalog module is built alongside this one, so
    the request is stubbed here (the refresh itself is tested with the catalog)."""
    monkeypatch.setattr(services.catalog, "request_refresh", lambda trigger: True)


async def _start(client: httpx.AsyncClient) -> str:
    """POST /auth/start; returns the state the callback address must carry."""
    response = await client.post("/api/spotify/auth/start")
    assert response.status_code == 200
    assert_response(response, "/api/spotify/auth/start")
    return parse_qs(urlsplit(response.json()["authorize_url"]).query)["state"][0]


async def _finish(client: httpx.AsyncClient, redirect_url: str) -> httpx.Response:
    response = await client.post("/api/spotify/auth/finish", json={"redirect_url": redirect_url})
    assert_response(response, "/api/spotify/auth/finish")
    return response


async def test_the_connection_of_a_fresh_container(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/spotify/connection")
    assert response.status_code == 200
    assert_response(response, "/api/spotify/connection")
    assert response.json()["state"] == "not_configured"


async def test_the_client_id_is_checked_and_stored(client: httpx.AsyncClient) -> None:
    bad = await client.post("/api/spotify/app", json={"client_id": "not-hex"})
    assert bad.status_code == 422
    assert_response(bad, "/api/spotify/app")
    assert bad.json()["error"]["code"] == "validation_failed"

    good = await client.post("/api/spotify/app", json={"client_id": CLIENT_ID})
    assert good.status_code == 200
    assert_response(good, "/api/spotify/app")
    body = good.json()
    assert body["state"] == "disconnected"
    assert body["client_id_masked"] == "0123…cdef"


async def test_authorize_needs_a_client_id_then_answers_the_url(
    client: httpx.AsyncClient,
) -> None:
    refused = await client.post("/api/spotify/auth/start")
    assert refused.status_code == 409
    assert_response(refused, "/api/spotify/auth/start")
    assert refused.json()["error"]["code"] == "no_client_id"

    await client.post("/api/spotify/app", json={"client_id": CLIENT_ID})
    response = await client.post("/api/spotify/auth/start")
    assert_response(response, "/api/spotify/auth/start")
    body = response.json()
    assert body["redirect_uri"] == REDIRECT
    assert body["authorize_url"].startswith("https://accounts.spotify.com/authorize?")
    assert "code_verifier" not in response.text
    assert "verifier" not in response.text


async def test_finish_answers_each_refusal_with_its_code(client: httpx.AsyncClient) -> None:
    not_callback = await _finish(client, "http://example.com/callback?code=x&state=y")
    assert not_callback.status_code == 422
    assert not_callback.json()["error"]["code"] == "invalid_redirect"

    await client.post("/api/spotify/app", json={"client_id": CLIENT_ID})
    state = await _start(client)
    declined = await _finish(client, f"{REDIRECT}?error=access_denied&state={state}")
    assert declined.status_code == 422
    assert declined.json()["error"]["code"] == "access_denied"

    state = await _start(client)
    mismatch = await _finish(client, f"{REDIRECT}?code=ok&state=older")
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "state_mismatch"

    refused = await _finish(client, f"{REDIRECT}?code=bad-code&state={state}")
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "token_exchange_failed"


async def test_finish_connects_and_the_second_paste_finds_nothing(
    client: httpx.AsyncClient, services: Services
) -> None:
    await client.post("/api/spotify/app", json={"client_id": CLIENT_ID})
    state = await _start(client)
    response = await _finish(client, f"{REDIRECT}?code=ok-code&state={state}")
    assert response.status_code == 200
    assert_response(response, "/api/spotify/auth/finish")
    body = response.json()
    assert body["state"] == "ok"
    assert body["display_name"] == world_of(services.ports).catalog.user.display_name
    assert body["expires_at"] is not None

    again = await _finish(client, f"{REDIRECT}?code=ok-code&state={state}")
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "no_pending_auth"


async def test_devices_and_disconnect(client: httpx.AsyncClient, services: Services) -> None:
    not_yet = await client.get("/api/spotify/devices")
    assert not_yet.status_code == 409
    assert_response(not_yet, "/api/spotify/devices")
    assert not_yet.json()["error"]["code"] == "not_connected"

    await client.post("/api/spotify/app", json={"client_id": CLIENT_ID})
    state = await _start(client)
    await _finish(client, f"{REDIRECT}?code=ok-code&state={state}")

    listed = await client.get("/api/spotify/devices")
    assert listed.status_code == 200
    assert_response(listed, "/api/spotify/devices")
    assert listed.json()["ours"] is None  # the client isn't installed in this test
    assert listed.json()["device_name"] == services.config.device_name

    world = world_of(services.ports)
    world.client.installed()
    world.client.log_in()
    world.client.start()
    listed = await client.get("/api/spotify/devices")
    assert listed.json()["ours"]["name"] == services.config.device_name

    await services.store.execute(
        "INSERT INTO runs (kind, trigger, state, started_at) "
        "VALUES ('run', 'run_now', 'running', '2026-11-15T10:00:00.000Z')"
    )
    during_run = await client.delete("/api/spotify/connection")
    assert during_run.status_code == 409
    assert_response(during_run, "/api/spotify/connection")
    assert during_run.json()["error"]["code"] == "run_active"

    await services.store.execute(
        "UPDATE runs SET state = 'ended', outcome = 'stopped', "
        "ended_at = '2026-11-15T10:05:00.000Z'"
    )
    gone = await client.delete("/api/spotify/connection")
    assert gone.status_code == 200
    assert_response(gone, "/api/spotify/connection")
    assert gone.json()["state"] == "disconnected"


async def test_connect_through_the_real_port_on_the_mock(
    client: httpx.AsyncClient,
    services: Services,
    spotify_mock: SpotifyMock,
    mock_webapi: SpotifyWebApi,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole PKCE flow against the mock Spotify: the mock checks the verifier at the exchange
    and the connection shows the mock's account. Waits for webapi-core's real port."""
    await client.post("/api/spotify/app", json={"client_id": spotify_mock.client_id})
    started = await client.post("/api/spotify/auth/start")
    query = parse_qs(urlsplit(started.json()["authorize_url"]).query)
    code = spotify_mock.authorize(code_challenge=query["code_challenge"][0])  # approving on Spotify
    response = await _finish(client, f"{REDIRECT}?code={code}&state={query['state'][0]}")
    assert response.status_code == 200
    assert response.json()["display_name"] == spotify_mock.catalog.user.display_name
    assert spotify_mock.unexpected == []
    assert spotify_mock.endpoints() == ["POST /api/token", "GET /me", "GET /me/player/devices"]
