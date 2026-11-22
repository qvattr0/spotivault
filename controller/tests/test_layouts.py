"""The file layout's rules and Spytify mapping, run against contracts/vectors/layouts.json.

Every case is checked twice: by the functions in spotivault/settings.py, and through
PUT /api/settings, whose 422 `invalid_layout` must carry the case's reason (and placeholder).
"""

import json
from typing import Any

import httpx
import pytest

from contract import CONTRACTS, assert_response
from spotivault.api.models import Layout
from spotivault.settings import check_layout, layout_to_spytify

# Parsed at collection time: reading files inside a test coroutine would block its loop.
VECTORS: dict[str, Any] = json.loads(
    (CONTRACTS / "vectors" / "layouts.json").read_text(encoding="utf-8")
)
CASES = {case["id"]: case for case in VECTORS["cases"]}
VALID = sorted(cid for cid, case in CASES.items() if case["expected"]["valid"])
INVALID = sorted(cid for cid, case in CASES.items() if not case["expected"]["valid"])


def test_the_vectors_cover_every_reason() -> None:
    reasons = {CASES[cid]["expected"]["reason"] for cid in INVALID}
    assert reasons == {
        "unknown_placeholder",
        "stray_brace",
        "backslash",
        "control_character",
        "bad_folder",
        "empty_file_name",
        "no_placeholder",
    }
    assert len(CASES) == len(VECTORS["cases"]), "case ids are unique"


@pytest.mark.parametrize("case_id", VALID)
def test_a_valid_layout_maps_to_spytify(case_id: str) -> None:
    case = CASES[case_id]
    assert check_layout(case["layout"]["pattern"]) is None
    layout = Layout.model_validate(case["layout"])
    assert layout_to_spytify(layout) == case["expected"]["spytify_settings"]


@pytest.mark.parametrize("case_id", INVALID)
def test_an_invalid_layout_is_refused_with_its_reason(case_id: str) -> None:
    case = CASES[case_id]
    problem = check_layout(case["layout"]["pattern"])
    assert problem is not None
    assert problem.reason == case["expected"]["reason"]
    assert problem.placeholder == case["expected"].get("placeholder")
    assert problem.message


@pytest.mark.parametrize("case_id", VALID)
async def test_the_api_saves_a_valid_layout(client: httpx.AsyncClient, case_id: str) -> None:
    layout = CASES[case_id]["layout"]
    response = await client.put("/api/settings", json={"layout": layout})
    assert response.status_code == 200
    assert response.json()["layout"] == layout


@pytest.mark.parametrize("case_id", INVALID)
async def test_the_api_refuses_an_invalid_layout(client: httpx.AsyncClient, case_id: str) -> None:
    case = CASES[case_id]
    response = await client.put("/api/settings", json={"layout": case["layout"]})
    assert response.status_code == 422
    assert_response(response, "/api/settings")
    error = response.json()["error"]
    assert error["code"] == "invalid_layout"
    expected = {"reason": case["expected"]["reason"]}
    if "placeholder" in case["expected"]:
        expected["placeholder"] = case["expected"]["placeholder"]
    assert error["details"] == expected
    # Nothing was saved.
    settings = (await client.get("/api/settings")).json()
    assert settings["layout"]["pattern"] == "{album_artist}/{album}/{track} - {title}"
