"""Spytify's track key (matching.py, frozen) against contracts/vectors/track-keys.json."""

import json

import pytest

from contract import CONTRACTS
from spotivault.matching import go_lower, go_trim, track_key, web_track_key
from spotivault.ports import Track

VECTORS = json.loads((CONTRACTS / "vectors" / "track-keys.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["id"])
def test_track_key_vectors(case: dict) -> None:
    assert track_key(case["artist"], case["title"]) == case["expected"]
    if case.get("spytify_index_key") is not None:
        assert case["expected"] == case["spytify_index_key"]


@pytest.mark.parametrize("case", VECTORS["web_cases"], ids=lambda case: case["id"])
def test_web_track_key_vectors(case: dict) -> None:
    track = Track(
        id=None,
        uri="spotify:track:x",
        name=case["name"],
        artists=tuple(case["artists"]),
        album_id=None,
        album_name=None,
        track_number=None,
        disc_number=None,
        duration_ms=0,
        is_local=False,
        is_playable=True,
        is_episode=False,
    )
    assert web_track_key(track) == case["expected"]


def test_the_go_differences() -> None:
    assert go_lower("İSTANBUL") == "istanbul"  # Python's lower() gives 'i̇stanbul'
    assert go_lower("ΟΔΟΣ") == "οδοσ"  # no final sigma
    assert go_trim("\x1ftitle\x1f") == "\x1ftitle\x1f"  # U+001F isn't Go space
    assert go_trim("　\xa0title \n") == "title"
