"""errors.py: every error answer is the contract's Error envelope."""

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ValidationError

from contract import assert_schema
from spotivault.errors import (
    ApiError,
    error_body,
    install_error_handlers,
    not_built,
    not_found,
    run_active,
)
from spotivault.ports import (
    ConnectionExpired,
    NoAccess,
    NotConnected,
    RateLimited,
    SpotifyUnavailable,
)
from spotivault.store import StoreUnavailable


class Body(BaseModel):
    count: int


def make_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/api/raise/{what}")
    async def raise_it(what: str) -> dict:
        errors: dict[str, Exception] = {
            "api": ApiError(409, "already_added", "Already in the Library.", {"id": "x"}),
            "not_found": not_found(),
            "run_active": run_active(),
            "not_built": not_built("getBacklog"),
            "store": StoreUnavailable("closed"),
            "not_connected": NotConnected("no token"),
            "expired": ConnectionExpired("invalid_grant", status=400),
            "rate_limited": RateLimited("slow down", retry_after_s=30),
            "unavailable": SpotifyUnavailable("5xx", status=503),
            "no_access": NoAccess("403", status=403),
        }
        raise errors[what]

    @app.post("/api/body")
    async def body(payload: Body) -> dict:
        return {}

    return app


@pytest.fixture
async def http() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client


@pytest.mark.parametrize(
    ("what", "status", "code"),
    [
        ("api", 409, "already_added"),
        ("not_found", 404, "not_found"),
        ("run_active", 409, "run_active"),
        ("not_built", 501, "internal"),
        ("store", 503, "internal"),
        ("not_connected", 409, "not_connected"),
        ("expired", 409, "connection_expired"),
        ("rate_limited", 503, "rate_limited"),
        ("unavailable", 503, "spotify_unavailable"),
        ("no_access", 503, "spotify_unavailable"),
    ],
)
async def test_errors_become_envelopes(
    http: httpx.AsyncClient, what: str, status: int, code: str
) -> None:
    response = await http.get(f"/api/raise/{what}")
    assert response.status_code == status
    body = response.json()
    assert_schema("Error", body)
    assert body["error"]["code"] == code


async def test_details_are_kept(http: httpx.AsyncClient) -> None:
    assert (await http.get("/api/raise/api")).json()["error"]["details"] == {"id": "x"}
    assert (await http.get("/api/raise/rate_limited")).json()["error"]["details"] == {
        "retry_after_s": 30
    }
    built = (await http.get("/api/raise/not_built")).json()["error"]["details"]
    assert built == {"reason": "not_built", "operation": "getBacklog"}


async def test_request_validation_names_the_field(http: httpx.AsyncClient) -> None:
    response = await http.post("/api/body", json={"count": "many"})
    assert response.status_code == 422
    body = response.json()
    assert_schema("Error", body)
    assert body["error"]["code"] == "validation_failed"
    assert body["error"]["details"] == {"field": "count"}


async def test_unknown_paths_and_methods(http: httpx.AsyncClient) -> None:
    for response in (await http.get("/api/nothing-here"), await http.delete("/api/body")):
        assert response.status_code in (404, 405)
        assert_schema("Error", response.json())
        assert response.json()["error"]["code"] == "not_found"


def test_a_code_outside_the_contract_is_refused() -> None:
    with pytest.raises(ValidationError):
        error_body("teapot", "I'm a teapot.")
