"""The app against contracts/openapi.yaml: every path and method is served, with the contract's
operationId, parameters and request body, and nothing else is, except the documented extras:

- the WebSockets in `x-websockets` (/api/events and /vnc);
- the SPA's catch-all GET, which serves the UI for every path outside /api.

The last test calls every operation with the contract's own examples and checks the answer's
shape. Unbuilt endpoints answer 501 with an Error envelope; built ones must answer with a status
and body the contract lists.
"""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import BaseRoute

from contract import HTTP_METHODS, assert_response, openapi

# Path parameter values for calling every operation (valid by the contract's patterns).
PATH_VALUES = {
    "/api/library/{id}": {"id": "liked"},
    "/api/library/{id}/tracks": {"id": "liked"},
    "/api/library/{id}/cover": {"id": "3cEYpjA9oz9GiPac4AsH4n"},
    "/api/albums/{id}": {"id": "4glBZ0bZMgkmFyi6TD4h69"},
    "/api/albums/{id}/tracks": {"id": "4glBZ0bZMgkmFyi6TD4h69"},
    "/api/albums/{id}/cover": {"id": "4glBZ0bZMgkmFyi6TD4h69"},
    "/api/runs/current/items/{id}": {"id": "liked"},
    "/api/runs/{id}": {"id": "42"},
    "/api/runs/{id}/items/{item}/tracks": {"id": "42", "item": "liked"},
}


def iter_routes(routes: list[BaseRoute]) -> Iterator[BaseRoute]:
    """Every route, with included routers expanded (FastAPI keeps them as wrappers)."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from iter_routes(inner.routes)
        else:
            yield route


def contract_operations() -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (path, method): op
        for path, item in openapi()["paths"].items()
        for method, op in item.items()
        if method in HTTP_METHODS
    }


def contract_parameters(path: str, method: str) -> set[tuple[str, str]]:
    item = openapi()["paths"][path]
    params = list(item.get("parameters", [])) + list(item[method].get("parameters", []))
    resolved = set()
    for param in params:
        if "$ref" in param:
            param = openapi()["components"]["parameters"][param["$ref"].rsplit("/", 1)[1]]
        resolved.add((param["name"], param["in"]))
    return resolved


@pytest.fixture
def app_spec(app: FastAPI) -> dict[str, Any]:
    return app.openapi()


def test_every_operation_is_served_with_its_operation_id(app_spec: dict[str, Any]) -> None:
    served = {
        (path, method): op["operationId"]
        for path, item in app_spec["paths"].items()
        for method, op in item.items()
        if method in HTTP_METHODS
    }
    expected = {key: op["operationId"] for key, op in contract_operations().items()}
    missing = sorted(set(expected) - set(served))
    extra = sorted(set(served) - set(expected))
    assert not missing, f"in openapi.yaml but not served: {missing}"
    assert not extra, f"served but not in openapi.yaml: {extra}"
    wrong_ids = {
        key: (served[key], expected[key]) for key in expected if served[key] != expected[key]
    }
    assert not wrong_ids, f"operationId differs (served, contract): {wrong_ids}"


def test_parameters_match(app_spec: dict[str, Any]) -> None:
    for (path, method), _op in contract_operations().items():
        served = {
            (p["name"], p["in"]) for p in app_spec["paths"][path][method].get("parameters", [])
        }
        assert served == contract_parameters(path, method), f"{method.upper()} {path}"


def test_request_bodies_match(app_spec: dict[str, Any]) -> None:
    for (path, method), op in contract_operations().items():
        served = app_spec["paths"][path][method].get("requestBody")
        expected = op.get("requestBody")
        assert (served is None) == (expected is None), f"{method.upper()} {path}: request body"
        if expected is not None:
            assert bool(served.get("required")) == bool(expected.get("required")), (
                f"{method.upper()} {path}"
            )


def test_success_statuses_are_in_the_contract(app_spec: dict[str, Any]) -> None:
    for (path, method), op in contract_operations().items():
        served = {
            code for code in app_spec["paths"][path][method]["responses"] if code.startswith("2")
        }
        expected = {code for code in op["responses"] if code.startswith("2")}
        assert served <= expected, (
            f"{method.upper()} {path}: answers {served}, contract has {expected}"
        )


def test_websockets_and_nothing_else(app: FastAPI) -> None:
    routes = list(iter_routes(app.routes))
    websockets = {route.path for route in routes if isinstance(route, APIWebSocketRoute)}
    assert websockets == {ws["path"] for ws in openapi()["x-websockets"]}
    hidden = [
        route for route in routes if isinstance(route, APIRoute) and not route.include_in_schema
    ]
    assert [(route.path, sorted(route.methods)) for route in hidden] == [
        ("/{path:path}", ["GET"])
    ], "the only route outside the contract is the SPA's catch-all"
    others = [r for r in routes if not isinstance(r, APIRoute | APIWebSocketRoute)]
    assert others == [], f"undocumented routes: {others}"


def _example_body(op: dict[str, Any]) -> Any:
    content = op.get("requestBody", {}).get("content", {}).get("application/json")
    if content is None:
        return None
    if "example" in content:
        return content["example"]
    return next(iter(content["examples"].values()))["value"]


async def test_every_operation_answers_in_the_contracts_shapes(client: httpx.AsyncClient) -> None:
    for (path, method), op in contract_operations().items():
        url = path.format(**PATH_VALUES.get(path, {}))
        body = _example_body(op)
        response = await client.request(method.upper(), url, json=body)
        allowed = {int(code) for code in op["responses"]} | {501}
        assert response.status_code in allowed, (
            f"{method.upper()} {url} answered {response.status_code}, not in the contract: "
            f"{response.text[:300]}"
        )
        assert_response(response, path)
