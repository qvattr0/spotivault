"""web/guard.py: the Host check on every request and the Origin check on requests that change
something, through the app (in-process, as the tests' `client` fixture calls it)."""

import logging

import httpx
import pytest
from fastapi import FastAPI

from asgi_ws import WebSocketRejected, websocket_connect
from contract import assert_schema
from spotivault.web.guard import host_allowed

EVIL = "https://evil.example"
REBIND = "rebind.attacker.example:8080"  # an attacker's name, pointed at the NAS's address


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("192.168.1.20:8080", True),
        ("192.168.1.20", True),
        ("[fd00::20]:8080", True),
        ("127.0.0.1:8080", True),
        ("localhost:8080", True),
        ("dev.localhost:5173", True),
        ("nas:8080", True),  # a name with no dot: the home network's own
        ("DXP4800PLUS-1A2B:8080", True),
        ("nas.local:8080", True),  # mDNS
        ("nas.lan", True),
        ("nas.internal", True),
        ("nas.home.arpa:8080", True),
        ("nas.local.:8080", True),  # a trailing dot is the same name
        ("spotivault.example.com", False),  # a public name: only through SPOTIVAULT_ALLOWED_HOSTS
        (REBIND, False),
        ("nas.local.evil.example", False),
        ("localhost.evil.example", False),
        ("", False),
        (":8080", False),
        ("[::1", False),
    ],
)
def test_host_rule(host: str, allowed: bool) -> None:
    assert host_allowed(host) is allowed


def test_allowed_hosts_add_names() -> None:
    assert host_allowed("Music.Example.com:443", ("music.example.com",))
    assert not host_allowed("other.example.com", ("music.example.com",))


# --- The Origin check ----------------------------------------------------------------------------


async def test_another_sites_form_cant_change_anything(client: httpx.AsyncClient) -> None:
    # A form a page on another site submits by itself: no JSON body, so FastAPI's content-type
    # check doesn't apply. It would reset the wizard.
    response = await client.post(
        "/api/setup/restart",
        headers={"Origin": EVIL, "Content-Type": "application/x-www-form-urlencoded"},
        content=b"",
    )
    assert response.status_code == 403
    assert_schema("Error", response.json())
    assert response.json()["error"]["code"] == "forbidden"

    response = await client.post(
        "/api/client/restart", headers={"Origin": EVIL, "Content-Type": "text/plain"}
    )
    assert response.status_code == 403
    for method in ("PUT", "PATCH", "DELETE"):
        response = await client.request(method, "/api/settings", headers={"Origin": "null"})
        assert response.status_code == 403, method


async def test_the_controllers_own_pages_and_scripts_can(client: httpx.AsyncClient) -> None:
    own = await client.post("/api/setup/restart", headers={"Origin": "http://spotivault.test"})
    assert own.status_code == 200
    script = await client.post("/api/setup/restart")  # curl: no Origin
    assert script.status_code == 200


async def test_reading_is_not_an_origin_matter(client: httpx.AsyncClient) -> None:
    # A page from another site can't read the answer (no CORS headers), and GET changes nothing.
    response = await client.get("/api/health", headers={"Origin": EVIL})
    assert response.status_code == 200


# --- The Host check ------------------------------------------------------------------------------


async def test_a_rebound_name_is_refused(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    # The page's Origin matches its Host, so only the Host check stops it.
    headers = {"Host": REBIND, "Origin": f"http://{REBIND}"}
    for _ in range(2):
        response = await client.get("/api/client/status", headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"
        assert "SPOTIVAULT_ALLOWED_HOSTS" in response.json()["error"]["message"]
    refusals = [r for r in caplog.records if r.levelno == logging.WARNING and REBIND in r.message]
    assert len(refusals) == 1  # logged once
    assert (await client.get("/", headers={"Host": REBIND})).status_code == 403  # the SPA too


async def test_a_rebound_name_cant_open_the_websockets(running_app: FastAPI) -> None:
    for path in ("/api/events", "/vnc"):
        with pytest.raises(WebSocketRejected) as rejected:
            async with websocket_connect(
                running_app, path, host=REBIND, headers=[("origin", f"http://{REBIND}")]
            ):
                pass
        assert rejected.value.code == 1008, path


async def test_allowed_hosts_count_as_the_controllers_own_origin(
    client: httpx.AsyncClient,
) -> None:
    # A reverse proxy that rewrites the Host: the page comes from a name in
    # SPOTIVAULT_ALLOWED_HOSTS (the tests' env sets spotivault.test).
    headers = {"Host": "127.0.0.1:8080", "Origin": "https://spotivault.test"}
    assert (await client.post("/api/setup/restart", headers=headers)).status_code == 200
