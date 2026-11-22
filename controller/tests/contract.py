"""Checking values against contracts/openapi.yaml, the source of truth for the API's shapes.

    from contract import assert_schema, assert_response
    assert_schema("Health", body)                  # a components/schemas entry
    assert_response(response, "/api/health")       # by path template, method and status

Validation is JSON Schema 2020-12 (OpenAPI 3.1), formats included (`date-time` needs
rfc3339-validator, a dev dependency). The contract is parsed when this module is imported, at
collection time: parsing it inside a test would block that test's event loop for over 100 ms.
"""

from pathlib import Path
from typing import Any

import httpx
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
OPENAPI = CONTRACTS / "openapi.yaml"
_BASE = "urn:spotivault:openapi"
HTTP_METHODS = ("get", "put", "post", "patch", "delete")


_SPEC: dict[str, Any] = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
_REGISTRY = Registry().with_resource(
    _BASE, Resource.from_contents(_SPEC, default_specification=DRAFT202012)
)


def openapi() -> dict[str, Any]:
    """The contract, parsed. Don't change it: it's shared by every test."""
    return _SPEC


def validator(pointer: str) -> Draft202012Validator:
    """A validator for the schema at a JSON pointer into the contract, such as
    "#/components/schemas/Health"."""
    return Draft202012Validator(
        {"$ref": _BASE + pointer},
        registry=_REGISTRY,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def assert_schema(name: str, instance: Any) -> None:
    """Fails with every error if `instance` doesn't match components/schemas/<name>."""
    _assert_valid(validator(f"#/components/schemas/{name}"), instance, name)


def operation(path: str, method: str) -> dict[str, Any]:
    return openapi()["paths"][path][method.lower()]


def response_pointer(path: str, method: str, status: int) -> str | None:
    """The JSON pointer of the JSON body schema for this response, or None for no JSON body."""
    responses = operation(path, method)["responses"]
    key = str(status)
    if key not in responses:
        raise AssertionError(f"{method.upper()} {path} has no {status} response in openapi.yaml")
    response = responses[key]
    escaped = path.replace("~", "~0").replace("/", "~1")
    pointer = f"#/paths/{escaped}/{method.lower()}/responses/{key}"
    if "$ref" in response:
        pointer = response["$ref"]
        response = openapi()["components"]["responses"][pointer.rsplit("/", 1)[1]]
    if "application/json" not in response.get("content", {}):
        return None
    return f"{pointer}/content/application~1json/schema"


def assert_response(response: httpx.Response, path: str) -> None:
    """Checks a response against the contract's response for its method and status.

    `path` is the template, such as "/api/library/{id}". A 501 from an endpoint that isn't built
    yet is checked as an Error envelope.
    """
    method = response.request.method
    if response.status_code == 501:
        assert_schema("Error", response.json())
        return
    pointer = response_pointer(path, method, response.status_code)
    if pointer is None:
        return
    _assert_valid(validator(pointer), response.json(), f"{method} {path} {response.status_code}")


def _assert_valid(check: Draft202012Validator, instance: Any, what: str) -> None:
    errors = sorted(check.iter_errors(instance), key=lambda e: list(e.absolute_path))
    if errors:
        lines = [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in errors]
        raise AssertionError(f"doesn't match {what}:\n  " + "\n  ".join(lines))
