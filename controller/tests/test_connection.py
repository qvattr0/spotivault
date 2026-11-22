"""connection.py: the Web API connection, step 5's checks, the expiry watch and the held runs.

Runs on the fake ports (the fake Web API follows the stored token). `request_refresh` is replaced
by a recorder: the catalog module is still a stub while spotify-connect is built alongside it.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI

from spotivault.api.models import Connection
from spotivault.connection import DEVICE_MISSING, PKCE_TTL_S
from spotivault.errors import ApiError
from spotivault.fake import world_of
from spotivault.fake.clock import FakeClock
from spotivault.ports import ConnectionExpired, NotConnected, TokenExchangeFailed
from spotivault.services import Services
from spotivault.webapi.auth_store import EXPIRING_WITHIN, add_months
from spotivault.webapi.endpoints import REDIRECT_URI

CLIENT_ID = "0123456789abcdef0123456789abcdef"
OTHER_ID = "fedcba9876543210fedcba9876543210"


@pytest.fixture
def refreshes(services: Services, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The triggers `request_refresh` was asked for. It always says it queued one."""
    asked: list[str] = []

    def ask(trigger: str) -> bool:
        asked.append(trigger)
        return True

    monkeypatch.setattr(services.catalog, "request_refresh", ask)
    return asked


@pytest.fixture
def published(services: Services, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Every event published, with its data, in order (the real bus still publishes)."""
    events: list[tuple[str, Any]] = []
    original: Callable[[str, Any], Any] = services.bus.publish

    def record(type: str, data: Any) -> Any:
        events.append((type, data))
        return original(type, data)

    monkeypatch.setattr(services.bus, "publish", record)
    return events


def _state_of(url: str) -> str:
    return parse_qs(urlsplit(url).query)["state"][0]


def _redirect(url: str, **params: str) -> str:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return f"{REDIRECT_URI}?{query}"


async def _start(services: Services) -> str:
    """Starts an attempt; returns the state the callback address must carry."""
    started = await services.connection.start_auth()
    return _state_of(str(started.authorize_url))


async def _connect(services: Services, refreshes: list[str]) -> Connection:
    """Stores a Client ID and completes an authorization (the fake port grants any code)."""
    await services.connection.set_client_id(CLIENT_ID)
    state = await _start(services)
    return await services.connection.finish_auth(
        _redirect(REDIRECT_URI, code="ok-code", state=state)
    )


# --- The connection and its states -------------------------------------------------------------


async def test_a_fresh_container_is_not_configured(
    running_app: FastAPI, services: Services
) -> None:
    connection = await services.connection.connection()
    assert connection.state == "not_configured"
    assert connection.client_id_masked is None
    assert connection.scopes == []
    assert await services.connection.held_reason() == "not_connected"


async def test_a_client_id_alone_is_disconnected(running_app: FastAPI, services: Services) -> None:
    connection = await services.connection.set_client_id(CLIENT_ID)
    assert connection.state == "disconnected"
    assert connection.client_id_masked == "0123…cdef"
    assert await services.connection.held_reason() == "not_connected"


async def test_connecting_fills_in_the_account_and_the_dates(
    running_app: FastAPI, services: Services, refreshes: list[str]
) -> None:
    connection = await _connect(services, refreshes)
    assert connection.state == "ok"
    assert connection.display_name == world_of(services.ports).catalog.user.display_name
    assert connection.user_id == world_of(services.ports).catalog.user.id
    assert connection.authorized_at == services.clock.now()
    assert connection.expires_at is not None
    assert connection.expires_at == add_months(services.clock.now(), 6)
    assert set(connection.scopes) >= {"user-library-read", "user-modify-playback-state"}
    assert await services.connection.held_reason() is None
    assert refreshes == ["setup"]


async def test_the_state_follows_the_expiry_dates(
    running_app: FastAPI, services: Services, refreshes: list[str], fake_clock: FakeClock
) -> None:
    connection = await _connect(services, refreshes)
    assert connection.expires_at is not None
    expiring_at = connection.expires_at - EXPIRING_WITHIN
    fake_clock.set_now(expiring_at - timedelta(seconds=1))
    assert (await services.connection.connection()).state == "ok"
    fake_clock.set_now(expiring_at)
    assert (await services.connection.connection()).state == "expiring"
    fake_clock.set_now(connection.expires_at)
    assert (await services.connection.connection()).state == "expired"
    assert await services.connection.held_reason() == "connection_expired"


async def test_invalid_grant_expires_the_connection_and_is_held(
    running_app: FastAPI, services: Services, refreshes: list[str], published: list[Any]
) -> None:
    await _connect(services, refreshes)
    world_of(services.ports).webapi.expired = True  # Spotify now answers invalid_grant
    with pytest.raises(ConnectionExpired):
        await services.ports.webapi.me()
    assert (await services.connection.connection()).state == "expired"
    assert await services.connection.held_reason() == "connection_expired"
    expired_events = [data for kind, data in published if kind == "connection"]
    assert expired_events[-1].state == "expired"


async def test_disconnect_keeps_the_client_id(
    running_app: FastAPI, services: Services, refreshes: list[str]
) -> None:
    await _connect(services, refreshes)
    connection = await services.connection.disconnect()
    assert connection.state == "disconnected"
    assert connection.client_id_masked == "0123…cdef"
    assert connection.display_name is None
    assert connection.expires_at is None
    assert await services.connection.held_reason() == "not_connected"
    with pytest.raises(NotConnected):
        await services.ports.webapi.me()


async def test_a_different_client_id_disconnects(
    running_app: FastAPI, services: Services, refreshes: list[str]
) -> None:
    await _connect(services, refreshes)
    connection = await services.connection.set_client_id(OTHER_ID)
    assert connection.state == "disconnected"
    assert connection.client_id_masked == "fedc…3210"
    same = await services.connection.set_client_id(OTHER_ID)
    assert same.state == "disconnected"


async def test_the_client_id_cannot_change_during_a_run(
    running_app: FastAPI, services: Services, refreshes: list[str]
) -> None:
    await _connect(services, refreshes)
    await services.store.execute(
        "INSERT INTO runs (kind, trigger, state, started_at) "
        "VALUES ('run', 'run_now', 'running', '2026-11-15T10:00:00.000Z')"
    )
    with pytest.raises(ApiError) as refused:
        await services.connection.set_client_id(OTHER_ID)
    assert refused.value.code == "run_active"
    with pytest.raises(ApiError) as gone:
        await services.connection.disconnect()
    assert gone.value.code == "run_active"
    assert (await services.connection.connection()).state == "ok"


# --- Authorize, paste, finish ------------------------------------------------------------------


async def test_authorize_needs_a_client_id(running_app: FastAPI, services: Services) -> None:
    with pytest.raises(ApiError) as refused:
        await services.connection.start_auth()
    assert (refused.value.status, refused.value.code) == (409, "no_client_id")


async def test_start_stores_one_attempt_and_the_url_has_no_verifier(
    running_app: FastAPI, services: Services
) -> None:
    await services.connection.set_client_id(CLIENT_ID)
    first = await services.connection.start_auth()
    second = await services.connection.start_auth()  # replaces the first
    rows = await services.store.fetchall("SELECT * FROM pkce_pending")
    assert len(rows) == 1
    row = rows[0]
    url = str(second.authorize_url)
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == [CLIENT_ID]
    assert query["state"] == [row["state"]]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert row["code_verifier"] not in url
    assert str(first.authorize_url) != url
    assert second.expires_at == services.clock.now() + timedelta(seconds=PKCE_TTL_S)
    assert second.redirect_uri == REDIRECT_URI


async def test_finish_connects_and_marks_step_five_done(
    running_app: FastAPI,
    services: Services,
    refreshes: list[str],
    published: list[Any],
) -> None:
    world = world_of(services.ports)
    world.client.installed()
    world.client.log_in()
    world.client.start()
    connection = await _connect(services, refreshes)
    assert connection.state == "ok"
    setup = await services.setup.snapshot()
    webapi_step = next(step for step in setup.steps if step.id == "webapi")
    assert webapi_step.state == "done"
    assert refreshes == ["setup"]
    assert [kind for kind, _ in published].count("connection") >= 2
    assert await services.store.fetchall("SELECT * FROM pkce_pending") == []


async def test_finish_without_our_device_marks_step_five_failed(
    running_app: FastAPI, services: Services, refreshes: list[str]
) -> None:
    # The client isn't installed, so the container isn't a device.
    connection = await _connect(services, refreshes)
    assert connection.state == "ok"
    setup = await services.setup.snapshot()
    webapi_step = next(step for step in setup.steps if step.id == "webapi")
    assert webapi_step.state == "failed"
    assert webapi_step.message == DEVICE_MISSING


async def test_devices_lists_ours_and_marks_step_five(
    running_app: FastAPI, services: Services, refreshes: list[str]
) -> None:
    await _connect(services, refreshes)
    before = await services.connection.devices()
    assert before.ours is None
    assert before.device_name == services.config.device_name
    world = world_of(services.ports)
    world.client.installed()
    world.client.log_in()
    world.client.start()
    after = await services.connection.devices()
    assert after.ours is not None
    assert after.ours.name == services.config.device_name
    assert after.ours.id is not None
    assert len(after.devices) >= 1
    setup = await services.setup.snapshot()
    webapi_step = next(step for step in setup.steps if step.id == "webapi")
    assert webapi_step.state == "done"


async def test_the_state_parameter_must_match(
    running_app: FastAPI, services: Services, refreshes: list[str]
) -> None:
    await services.connection.set_client_id(CLIENT_ID)
    first = await _start(services)
    second = await _start(services)  # replaces the first attempt
    assert first != second
    with pytest.raises(ApiError) as mismatch:
        await services.connection.finish_auth(_redirect(REDIRECT_URI, code="ok", state=first))
    assert mismatch.value.code == "state_mismatch"
    with pytest.raises(ApiError) as missing:
        await services.connection.finish_auth(_redirect(REDIRECT_URI, code="ok"))
    assert missing.value.code == "state_mismatch"
    # A wrong state leaves the pending attempt alone: the right address still works.
    connection = await services.connection.finish_auth(
        _redirect(REDIRECT_URI, code="ok", state=second)
    )
    assert connection.state == "ok"


async def test_a_declined_authorization_is_refused(
    running_app: FastAPI, services: Services, refreshes: list[str]
) -> None:
    await services.connection.set_client_id(CLIENT_ID)
    state = await _start(services)
    with pytest.raises(ApiError) as declined:
        await services.connection.finish_auth(
            _redirect(REDIRECT_URI, error="access_denied", state=state)
        )
    assert (declined.value.status, declined.value.code) == (422, "access_denied")
    assert refreshes == []


@pytest.mark.parametrize(
    "address",
    [
        "http://127.0.0.1:8889/callback?code=x&state=y",
        "http://localhost:8888/callback?code=x&state=y",
        "https://127.0.0.1:8888/callback?code=x&state=y",
        "http://127.0.0.1:8888/other?code=x&state=y",
        "http://127.0.0.1:8888/callback",
        "http://u:p@127.0.0.1:8888/callback?code=x&state=y",
        "not an address",
    ],
)
async def test_an_address_that_is_not_the_callback_is_refused(
    running_app: FastAPI, services: Services, address: str
) -> None:
    await services.connection.set_client_id(CLIENT_ID)
    await _start(services)
    with pytest.raises(ApiError) as refused:
        await services.connection.finish_auth(address)
    assert (refused.value.status, refused.value.code) == (422, "invalid_redirect")


async def test_the_verifier_is_single_use(
    running_app: FastAPI, services: Services, refreshes: list[str]
) -> None:
    await services.connection.set_client_id(CLIENT_ID)
    state = await _start(services)
    address = _redirect(REDIRECT_URI, code="ok-code", state=state)
    await services.connection.finish_auth(address)
    with pytest.raises(ApiError) as again:
        await services.connection.finish_auth(address)
    assert (again.value.status, again.value.code) == (422, "no_pending_auth")
    assert refreshes == ["setup"]


async def test_an_expired_attempt_is_refused_and_dropped(
    running_app: FastAPI, services: Services, fake_clock: FakeClock
) -> None:
    await services.connection.set_client_id(CLIENT_ID)
    state = await _start(services)
    await fake_clock.advance(PKCE_TTL_S + 1)
    with pytest.raises(ApiError) as expired:
        await services.connection.finish_auth(_redirect(REDIRECT_URI, code="ok", state=state))
    assert expired.value.code == "no_pending_auth"
    assert await services.store.fetchall("SELECT * FROM pkce_pending") == []


async def test_finish_without_an_attempt_is_refused(
    running_app: FastAPI, services: Services
) -> None:
    await services.connection.set_client_id(CLIENT_ID)
    with pytest.raises(ApiError) as none:
        await services.connection.finish_auth(_redirect(REDIRECT_URI, code="ok", state="s"))
    assert none.value.code == "no_pending_auth"


async def test_a_refused_code_stores_nothing_and_consumes_the_attempt(
    running_app: FastAPI, services: Services, refreshes: list[str]
) -> None:
    await services.connection.set_client_id(CLIENT_ID)
    state = await _start(services)
    with pytest.raises(TokenExchangeFailed):
        await services.connection.finish_auth(_redirect(REDIRECT_URI, code="bad-code", state=state))
    assert (await services.connection.connection()).state == "disconnected"
    assert await services.store.fetchall("SELECT * FROM pkce_pending") == []
    assert refreshes == []


async def test_a_changed_client_id_drops_the_attempt(
    running_app: FastAPI, services: Services, refreshes: list[str]
) -> None:
    await services.connection.set_client_id(CLIENT_ID)
    state = await _start(services)
    await services.connection.set_client_id(OTHER_ID)
    with pytest.raises(ApiError) as gone:
        await services.connection.finish_auth(_redirect(REDIRECT_URI, code="ok", state=state))
    assert gone.value.code == "no_pending_auth"
    assert (await services.connection.connection()).state == "disconnected"


# --- Secrets -----------------------------------------------------------------------------------


async def test_no_secret_reaches_a_log_line_an_event_or_an_answer(
    running_app: FastAPI,
    services: Services,
    refreshes: list[str],
    published: list[Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    world = world_of(services.ports)
    world.client.installed()
    world.client.log_in()
    world.client.start()
    await services.connection.set_client_id(CLIENT_ID)
    state = await _start(services)
    row = await services.store.fetchone("SELECT code_verifier FROM pkce_pending")
    assert row is not None
    verifier = str(row["code_verifier"])
    await services.connection.finish_auth(_redirect(REDIRECT_URI, code="ok-code", state=state))
    stored = await services.auth.load()
    secrets = [verifier, "ok-code", str(stored.access_token), str(stored.refresh_token)]
    # The ones the fake Web API hands out are "fake-access-token-…", so check those too.
    secrets += [f"fake-{kind}-token-{n}" for kind in ("access", "refresh") for n in range(1, 4)]
    text = caplog.text + "".join(
        f"{kind} {data.model_dump_json()}"
        for kind, data in published
        if hasattr(data, "model_dump_json")
    )
    for secret in secrets:
        assert secret not in text


# --- The watch and the held runs ---------------------------------------------------------------


async def test_the_watch_publishes_expiring_and_expired_when_they_come(
    services: Services,
    refreshes: list[str],
    published: list[Any],
    fake_clock: FakeClock,
) -> None:
    # The watch sleeps on the fake clock in at most hour-long steps. Moving the wall clock to two
    # hours before each boundary, then advancing past it, keeps the test to a few steps (advancing
    # the whole six months would wake every poll on the way).
    # Only the store and the watch run here, not the lifespan: the client's status poll would
    # otherwise wake on every 3 s of the advance.
    await services.store.open()
    watch = asyncio.create_task(services.connection.watch())
    try:
        connection = await _connect(services, refreshes)
        assert connection.expires_at is not None
        published.clear()
        expiring_at = connection.expires_at - EXPIRING_WITHIN
        fake_clock.set_now(expiring_at - timedelta(hours=2))
        await fake_clock.advance(2 * 3600 + 60)
        assert [data.state for kind, data in published if kind == "connection"] == ["expiring"]
        fake_clock.set_now(connection.expires_at - timedelta(hours=2))
        await fake_clock.advance(2 * 3600 + 60)
        assert [data.state for kind, data in published if kind == "connection"] == [
            "expiring",
            "expired",
        ]
    finally:
        watch.cancel()
        await asyncio.gather(watch, return_exceptions=True)
        await services.store.close()


async def test_a_refused_client_id_change_publishes_nothing_new(
    running_app: FastAPI, services: Services, published: list[Any]
) -> None:
    await services.connection.set_client_id(CLIENT_ID)
    published.clear()
    await services.connection.set_client_id(CLIENT_ID)  # the same id: no change
    assert [kind for kind, _ in published] == []


async def test_the_hello_connection_answers_even_without_a_database(services: Services) -> None:
    # The store isn't open here: the hello still gets a connection, "not configured".
    connection = await services.connection.snapshot()
    assert connection.state == "not_configured"
    assert connection.scopes == []
