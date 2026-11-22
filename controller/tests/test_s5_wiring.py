"""S5's foundation as services.py wires it: the modules exist, the fake Web API follows the
controller's stored token, the demo scenario starts connected, and tests can put the real port
on the mock Spotify."""

import pytest
from fastapi import FastAPI

from asgi_ws import websocket_connect
from spotify_mock import SpotifyMock, connect
from spotivault.app import create_app
from spotivault.config import Config
from spotivault.fake import build_fake_ports, world_of
from spotivault.fake.clock import FakeClock
from spotivault.fake.seed import DEMO_CLIENT_ID
from spotivault.ports import ConnectionExpired, NotConnected, SpotifyUser, TokenGrant
from spotivault.services import Services, build_services
from spotivault.webapi.client import SpotifyWebApi

CLIENT_ID = "0123456789abcdef0123456789abcdef"
GRANT = TokenGrant(access_token="t" * 10, refresh_token="r" * 10, expires_in_s=3600, scopes=())


def test_the_s5_modules_are_built(services: Services) -> None:
    for name in (
        "auth",
        "webapi_usage",
        "matching",
        "covers",
        "connection",
        "catalog",
        "library",
        "albums",
        "backlog",
    ):
        assert getattr(services, name) is not None, name
    assert world_of(services.ports).webapi.auth is services.auth
    assert type(services.ports.cdn).__name__ == "FakeImageCdn"


async def test_the_fake_web_api_follows_the_stored_token(
    running_app: FastAPI, services: Services
) -> None:
    world = world_of(services.ports)
    with pytest.raises(NotConnected):
        await services.ports.webapi.me()
    await services.auth.set_client_id(CLIENT_ID)
    await services.auth.save_grant(CLIENT_ID, GRANT)
    assert (await services.ports.webapi.me()).id == world.catalog.user.id

    seen: list[str] = []

    async def listen(change: str) -> None:
        seen.append(change)

    services.auth.add_listener(listen)
    world.webapi.expired = True  # Spotify now answers invalid_grant
    with pytest.raises(ConnectionExpired):
        await services.ports.webapi.me()
    assert seen == ["expired"]
    assert (await services.auth.load()).state(services.clock.now()) == "expired"
    with pytest.raises(ConnectionExpired):
        await services.ports.webapi.devices()

    grant = await world.webapi.exchange_code(
        client_id=CLIENT_ID, code="ok", code_verifier="v", redirect_uri="x"
    )
    await services.auth.save_grant(CLIENT_ID, grant)  # reconnecting
    assert (await services.ports.webapi.me()).id == world.catalog.user.id
    await services.auth.disconnect()
    with pytest.raises(NotConnected):
        await services.ports.webapi.me()


async def test_the_demo_starts_connected(config: Config, fake_clock: FakeClock) -> None:
    services = build_services(config, clock=fake_clock)
    services.ports = build_fake_ports(config, fake_clock, scenario="demo")
    app = create_app(services)
    async with app.router.lifespan_context(app):
        row = await services.auth.load()
        assert row.client_id == DEMO_CLIENT_ID and row.has_token
        assert row.state(fake_clock.now()) == "ok"
        assert row.display_name == world_of(services.ports).catalog.user.display_name
        playlists = await services.ports.webapi.my_playlists()
        assert playlists.total == 18
        await services.auth.disconnect()  # a restart keeps what the UI did
    again = build_services(config, clock=fake_clock)
    again.ports = build_fake_ports(config, fake_clock, scenario="demo")
    app = create_app(again)
    async with app.router.lifespan_context(app):
        assert not (await again.auth.load()).has_token


async def test_the_hello_works_on_a_fresh_container(running_app: FastAPI) -> None:
    async with websocket_connect(running_app, "/api/events") as ws:
        hello = await ws.receive_json()
    assert hello["type"] == "hello"
    assert hello["data"]["connection"]["state"] == "not_configured"


async def test_the_real_port_can_be_put_on_the_mock(
    running_app: FastAPI,
    services: Services,
    spotify_mock: SpotifyMock,
    mock_webapi: SpotifyWebApi,
) -> None:
    assert services.ports.webapi is mock_webapi
    access, refresh = await connect(services, spotify_mock)
    row = await services.auth.load()
    assert row.client_id == spotify_mock.client_id
    assert (row.access_token, row.refresh_token) == (access, refresh)
    assert row.display_name == spotify_mock.catalog.user.display_name


async def test_the_real_port_reads_me_from_the_mock(
    running_app: FastAPI,
    services: Services,
    spotify_mock: SpotifyMock,
    mock_webapi: SpotifyWebApi,
) -> None:
    await connect(services, spotify_mock)
    user = await mock_webapi.me()
    assert user == SpotifyUser(id="user2", display_name="User One")
    assert spotify_mock.endpoints() == ["GET /me"]
    assert spotify_mock.unexpected == []
