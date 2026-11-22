"""GET /api/health and the SPA (owner: the web agent)."""

import asyncio
import os
from pathlib import Path
from urllib.parse import unquote_to_bytes

import httpx
import pytest
from fastapi import FastAPI

from contract import assert_response
from spotivault.api.routers import health
from spotivault.app import create_app
from spotivault.config import load_config
from spotivault.fake.clock import FakeClock
from spotivault.services import Services, build_services
from spotivault.web import spa


async def forget_installs(services: Services) -> None:
    """Clears the client_install table. In fake mode the client manager installs the client on
    the first start, and health would rightly say `installing`."""
    await services.store.execute("DELETE FROM client_install")


# --- Health ---------------------------------------------------------------------------------------


async def test_health(client: httpx.AsyncClient, services: Services) -> None:
    await forget_installs(services)
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert_response(response, "/api/health")
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {
        "db": "ok",
        "display": "ok",
        "pulseaudio": "ok",
        "client": "not_installed",
    }
    assert body["boot_id"] == services.bus.boot_id
    assert body["version"] == services.bus.version
    assert response.headers["cache-control"] == "no-store"


async def _false() -> bool:
    return False


async def test_health_is_starting_then_degraded_when_a_check_fails(
    client: httpx.AsyncClient, services: Services, fake_clock: FakeClock
) -> None:
    services.ports.desktop.audio_ok = _false  # type: ignore[method-assign]
    body = (await client.get("/api/health")).json()
    assert (body["status"], body["checks"]["pulseaudio"]) == ("starting", "fail")

    await fake_clock.advance(health.STARTING_S + 1)
    response = await client.get("/api/health")
    assert response.status_code == 200  # the container stays healthy, so the UI stays reachable
    assert_response(response, "/api/health")
    body = response.json()
    assert (body["status"], body["checks"]["pulseaudio"]) == ("degraded", "fail")
    assert body["uptime_s"] >= health.STARTING_S


async def test_health_logs_status_changes_once(
    client: httpx.AsyncClient,
    services: Services,
    fake_clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await fake_clock.advance(health.STARTING_S + 1)
    services.ports.desktop.display_ok = _false  # type: ignore[method-assign]
    with caplog.at_level("INFO", logger=health.__name__):
        for _ in range(3):
            await client.get("/api/health")
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert warnings == ["health: degraded (display not answering)"]


async def test_a_check_that_hangs_or_raises_counts_as_failed(
    client: httpx.AsyncClient, services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "CHECK_TIMEOUT_S", 0.05)

    async def hangs() -> bool:
        await asyncio.Event().wait()
        return True

    async def raises() -> bool:
        raise RuntimeError("boom")

    services.ports.desktop.display_ok = hangs  # type: ignore[method-assign]
    services.ports.desktop.audio_ok = raises  # type: ignore[method-assign]
    services.ports.client.is_running = hangs  # type: ignore[method-assign]
    await forget_installs(services)
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert_response(response, "/api/health")
    checks = response.json()["checks"]
    assert (checks["display"], checks["pulseaudio"], checks["client"]) == (
        "fail",
        "fail",
        "stopped",
    )


async def test_health_client_states(client: httpx.AsyncClient, services: Services) -> None:
    installed: str | None = None
    running = False

    async def installed_version() -> str | None:
        return installed

    async def is_running() -> bool:
        return running

    services.ports.client.installed_version = installed_version  # type: ignore[method-assign]
    services.ports.client.is_running = is_running  # type: ignore[method-assign]

    async def client_check() -> str:
        response = await client.get("/api/health")
        assert_response(response, "/api/health")
        return response.json()["checks"]["client"]

    await forget_installs(services)
    assert await client_check() == "not_installed"
    installed = "1.3.4.258"
    assert await client_check() == "stopped"
    running = True
    assert await client_check() == "running"

    # An install in progress (the client manager's row in client_install) comes first.
    now = services.clock.now().isoformat()
    await services.store.execute(
        "INSERT INTO client_install (started_at, state, phase) "
        "VALUES (?, 'installing', 'download')",
        (now,),
    )
    assert await client_check() == "installing"
    await services.store.execute(
        "UPDATE client_install SET state = 'installed', finished_at = ?", (now,)
    )
    assert await client_check() == "running"


@pytest.fixture
def app_without_db(tmp_path: Path, env: dict[str, str]) -> FastAPI:
    """A controller whose database can't be created: a file sits where the db folder goes."""
    blocked = tmp_path / "blocked-config"
    blocked.mkdir()
    (blocked / "db").write_text("not a folder")
    config = load_config({**env, "SPOTIVAULT_CONFIG_DIR": str(blocked)})
    return create_app(build_services(config, clock=FakeClock()))


async def test_health_answers_503_without_a_database(app_without_db: FastAPI) -> None:
    app = app_without_db
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
            response = await http.get("/api/health")
            assert response.status_code == 503
            assert_response(response, "/api/health")
            assert response.json()["error"]["code"] == "internal"
            assert response.headers["cache-control"] == "no-store"
            # Other endpoints still answer with an envelope while the controller is degraded.
            assert (await http.get("/api/nothing")).status_code == 404
    assert app.state.services.store.error is not None


# --- The SPA --------------------------------------------------------------------------------------


async def test_spa_placeholder_without_a_ui(client: httpx.AsyncClient) -> None:
    for route in ("/", "/library"):
        response = await client.get(route)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "web UI isn't built" in response.text
        assert 'href="/vnc.html"' in response.text
        assert response.headers["x-content-type-options"] == "nosniff"


@pytest.fixture
def built_ui(web_root: Path) -> Path:
    """A web root as the image has it: the built UI, Vite's hashed assets and noVNC's core."""
    (web_root / "index.html").write_text("<!doctype html><title>app</title>")
    (web_root / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    assets = web_root / "assets"
    assets.mkdir()
    (assets / "index-BXk1c-9Q.js").write_text("console.log('hi')")
    (assets / "index-D_4yGpA8.css").write_text("body{}")
    (assets / "figtree-latin-400-normal-AbCdEf12.woff2").write_bytes(b"wOF2")
    core = web_root / "novnc" / "core"
    core.mkdir(parents=True)
    (core / "rfb.js").write_text("export default class RFB {}")
    return web_root


async def test_spa_serves_files_with_their_types(built_ui: Path, client: httpx.AsyncClient) -> None:
    expected = {
        "/assets/index-BXk1c-9Q.js": "text/javascript; charset=utf-8",
        "/assets/index-D_4yGpA8.css": "text/css; charset=utf-8",
        "/assets/figtree-latin-400-normal-AbCdEf12.woff2": "font/woff2",
        "/favicon.svg": "image/svg+xml",
        "/novnc/core/rfb.js": "text/javascript; charset=utf-8",
        "/index.html": "text/html; charset=utf-8",
    }
    for path, media_type in expected.items():
        response = await client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"] == media_type, path
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert (await client.get("/assets/index-BXk1c-9Q.js")).text == "console.log('hi')"


async def test_spa_routes_to_index(built_ui: Path, client: httpx.AsyncClient) -> None:
    for route in ("/", "/library", "/library/3cEYpjA9oz9GiPac4AsH4n", "/settings/files", "/novnc"):
        response = await client.get(route)
        assert response.status_code == 200, route
        assert "<title>app</title>" in response.text, route
        assert response.headers["cache-control"] == "no-cache"


async def test_spa_missing_files_are_404_not_index(
    built_ui: Path, client: httpx.AsyncClient
) -> None:
    for path in ("/assets/gone-12345678.js", "/favicon.ico", "/novnc/core/nope.js"):
        response = await client.get(path)
        assert response.status_code == 404, path
        assert "<title>app</title>" not in response.text


async def test_spa_caching(built_ui: Path, client: httpx.AsyncClient) -> None:
    hashed = await client.get("/assets/index-BXk1c-9Q.js")
    assert hashed.headers["cache-control"] == "public, max-age=31536000, immutable"
    for path in ("/", "/index.html", "/favicon.svg", "/novnc/core/rfb.js", "/vnc.html"):
        response = await client.get(path)
        assert response.headers["cache-control"] == "no-cache", path
        etag = response.headers["etag"]
        again = await client.get(path, headers={"If-None-Match": etag})
        assert again.status_code == 304, path
        assert again.content == b""
        assert again.headers["etag"] == etag
        assert again.headers["cache-control"] == "no-cache"
        other = await client.get(path, headers={"If-None-Match": '"something-else"'})
        assert other.status_code == 200


def test_etag_matching() -> None:
    assert spa.etag_matches('"a"', '"a"')
    assert spa.etag_matches('W/"a"', '"a"')
    assert spa.etag_matches('"x", "a"', '"a"')
    assert spa.etag_matches("*", '"a"')
    assert not spa.etag_matches(None, '"a"')
    assert not spa.etag_matches('"b"', '"a"')


async def test_vnc_page_is_served_without_a_ui(client: httpx.AsyncClient) -> None:
    response = await client.get("/vnc.html")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "import RFB from './novnc/core/rfb.js'" in response.text
    assert "'/vnc'" in response.text


async def test_the_web_roots_vnc_page_wins(web_root: Path, client: httpx.AsyncClient) -> None:
    (web_root / "vnc.html").write_text("<title>own</title>")
    assert (await client.get("/vnc.html")).text == "<title>own</title>"


async def test_unknown_api_paths_are_not_the_app(built_ui: Path, client: httpx.AsyncClient) -> None:
    response = await client.get("/api/library/x/y/z")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- Nothing outside the web root -----------------------------------------------------------------


@pytest.fixture
def secrets_beside(built_ui: Path) -> Path:
    """A secret next to the web root, a hidden file in it, and a symlink from it to the outside."""
    secret = built_ui.parent / "secret.txt"
    secret.write_text("token")
    (built_ui / ".env").write_text("token")
    os.symlink(secret, built_ui / "link.txt")
    return secret


def test_lookup_stays_in_the_root(built_ui: Path, secrets_beside: Path) -> None:
    def find(path: str) -> Path | None:
        parts = spa.safe_parts(path)
        if parts is None:
            return None
        file = spa.lookup(built_ui, parts)
        return file.path if file else None

    for path in ("../secret.txt", "assets/../../secret.txt", ".env", "link.txt", "a\x00b.js"):
        assert find(path) is None, path
    assert find("assets/index-BXk1c-9Q.js") == (built_ui / "assets/index-BXk1c-9Q.js").resolve()


async def _raw_get(app: FastAPI, raw_path: bytes) -> tuple[int, bytes]:
    """A GET with the path exactly as given, as uvicorn would pass it on (httpx tidies paths)."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": unquote_to_bytes(raw_path).decode("latin-1"),
        "raw_path": raw_path,
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"spotivault.test")],
        "client": ("127.0.0.1", 50000),
        "server": ("spotivault.test", 80),
        "state": {},
    }
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await app(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body


async def test_spa_refuses_paths_out_of_the_root(
    built_ui: Path, secrets_beside: Path, running_app: FastAPI
) -> None:
    for raw in (
        b"/../secret.txt",
        b"/assets/../../secret.txt",
        b"/%2e%2e/secret.txt",
        b"/assets/..%2f..%2fsecret.txt",
        b"/.env",
        b"/link.txt",
    ):
        status, body = await _raw_get(running_app, raw)
        assert status == 404, raw
        assert b"token" not in body, raw
