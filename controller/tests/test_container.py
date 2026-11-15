"""GET /api/container and the spytifyd version (owner: settings-storage-setup)."""

import dataclasses
import logging
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from contract import assert_response
from spotivault import __version__
from spotivault.app import create_app
from spotivault.config import load_config
from spotivault.container import UNKNOWN, parse_spytifyd_version, spytifyd_version
from spotivault.fake.clock import FakeClock
from spotivault.services import Services, build_services


async def test_container_facts(client: httpx.AsyncClient, services: Services) -> None:
    response = await client.get("/api/container")
    assert response.status_code == 200
    assert_response(response, "/api/container")
    body = response.json()
    assert body["device_name"] == "spotivault-test"
    assert body["tz"] == "UTC"
    assert body["umask"] == "000"
    assert body["ui_password_env_set"] is False
    assert body["versions"]["image"] == "dev"
    assert body["versions"]["controller"] == __version__
    assert body["versions"]["spytify"] == await services.ports.recorder.version()
    assert body["versions"]["client"] == await services.ports.client.installed_version()


async def test_the_music_source_and_client_version_come_from_the_ports(
    client: httpx.AsyncClient, services: Services
) -> None:
    async def source(path: Path) -> str | None:
        return "/Music" if path == services.config.music_dir else None

    async def installed() -> str | None:
        return "1.3.4.258"

    services.ports.storage.mount_source = source  # type: ignore[method-assign]
    services.ports.client.installed_version = installed  # type: ignore[method-assign]
    body = (await client.get("/api/container")).json()
    assert body["music_source"] == "/Music"
    assert body["versions"]["client"] == "1.3.4.258"


@pytest.fixture
def password_app(env: dict[str, str]) -> FastAPI:
    config = load_config({**env, "UI_PASSWORD": "hunter2-secret", "UMASK": "0022"})
    return create_app(build_services(config, clock=FakeClock()))


async def test_ui_password_is_reported_and_warned_about_never_shown(
    password_app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    async with password_app.router.lifespan_context(password_app):
        transport = httpx.ASGITransport(app=password_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
            response = await http.get("/api/container")
    assert_response(response, "/api/container")
    body = response.json()
    assert body["ui_password_env_set"] is True
    assert body["umask"] == "0022"
    assert "UI_PASSWORD is set, but this version doesn't enforce it" in caplog.text
    assert "hunter2-secret" not in caplog.text
    assert "hunter2-secret" not in response.text


@pytest.mark.parametrize(
    ("output", "version"),
    [
        ("spytifyd v2.0.2 (linux/amd64)", "2.0.2"),
        ("spytifyd v2.0.2\n", "2.0.2"),
        ("spytifyd 2.1.0-rc.1 (go1.26.0)", "2.1.0-rc.1"),
        ("spytifyd version 10.20.30", "10.20.30"),
        ("usage: spytifyd [flags]", None),
        ("", None),
    ],
)
def test_parse_spytifyd_version(output: str, version: str | None) -> None:
    assert parse_spytifyd_version(output) == version


@pytest.fixture
def scripts(tmp_path: Path) -> dict[str, Path]:
    """Stand-ins for spytifyd: small shell scripts."""
    bodies = {
        "good": "echo 'spytifyd v2.0.2 (linux/amd64)'",
        "failing": "echo boom; exit 3",
        "slow": "exec sleep 30",
    }
    paths = {}
    for name, body in bodies.items():
        path = tmp_path / f"spytifyd-{name}"
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)
        paths[name] = path
    paths["missing"] = tmp_path / "no-such-spytifyd"
    return paths


async def test_spytifyd_version_runs_the_binary(scripts: dict[str, Path]) -> None:
    assert await spytifyd_version(scripts["good"]) == "2.0.2"
    assert await spytifyd_version(scripts["failing"]) is None
    assert await spytifyd_version(scripts["missing"]) is None
    assert await spytifyd_version(scripts["slow"], timeout_s=0.3) is None


async def test_real_mode_asks_spytifyd_when_the_recorder_cant_tell(
    services: Services, scripts: dict[str, Path], running_app: FastAPI
) -> None:
    async def no_version() -> str | None:
        return None

    services.ports.recorder.version = no_version  # type: ignore[method-assign]
    # Fake mode never runs a binary.
    assert await services.container.spytify_version() is None
    assert (await services.container.info()).versions.spytify == UNKNOWN
    # Real mode runs spytifyd --version (the real recorder is S6's), once.
    services.config = dataclasses.replace(
        services.config, fake=False, spytifyd_path=scripts["good"]
    )
    assert await services.container.spytify_version() == "2.0.2"
    services.config = dataclasses.replace(services.config, spytifyd_path=scripts["missing"])
    assert await services.container.spytify_version() == "2.0.2", "cached"


async def test_a_fact_that_cant_be_read_is_null(
    client: httpx.AsyncClient, services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: object) -> str | None:
        raise OSError("can't read it")

    monkeypatch.setattr(services.ports.client, "installed_version", broken)
    monkeypatch.setattr(services.ports.storage, "mount_source", broken)
    monkeypatch.setattr(services.ports.recorder, "version", broken)
    response = await client.get("/api/container")
    assert response.status_code == 200
    assert_response(response, "/api/container")
    body = response.json()
    assert (body["music_source"], body["versions"]["client"]) == (None, None)
    assert body["versions"]["spytify"] == UNKNOWN
