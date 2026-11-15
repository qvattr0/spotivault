"""backlog.py's pure estimate against contracts/vectors/backlog.json, and the finish-date rules the
vectors don't reach (a slow schedule looks past the 21-day horizon)."""

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from contract import CONTRACTS
from spotivault.api.models import Backlog
from spotivault.backlog import BacklogItem, BacklogTrack, estimate

VECTORS = json.loads((CONTRACTS / "vectors" / "backlog.json").read_text(encoding="utf-8"))


def parse(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def d13_up_to_date(d13: dict[str, Any] | None) -> bool:
    """The vectors' d13 object as D13 reads it: up to date when the last clean pass's snapshot is
    the playlist's current one and every observed track is still in the index."""
    if not d13:
        return False
    last = d13.get("last_full_pass_snapshot")
    return (
        last is not None
        and last == d13.get("snapshot_id")
        and d13.get("observed_all_in_index") is True
    )


def items_from(raw_items: list[dict[str, Any]]) -> list[BacklogItem]:
    items: list[BacklogItem] = []
    for raw in raw_items:
        tracks = None
        if raw["tracks"] is not None:
            tracks = [
                BacklogTrack(
                    id=track["id"],
                    duration_ms=track["duration_ms"],
                    playable=track.get("playable", True),
                    is_local=track.get("is_local", False),
                )
                for track in raw["tracks"]
            ]
        items.append(
            BacklogItem(
                id=raw["id"],
                kind=raw["kind"],
                tracked=raw["tracked"],
                item_access=raw["item_access"],
                unavailable=raw["unavailable"],
                tracks=tracks,
                d13_up_to_date=d13_up_to_date(raw.get("d13")),
            )
        )
    return items


def run_case(inp: dict[str, Any]) -> Backlog:
    return estimate(
        items_from(inp["items"]),
        inp["recorded_track_ids"],
        inp["hours"],
        ZoneInfo(inp["tz"]),
        parse(inp["now"]),
    )


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["id"])
def test_backlog_vectors(case: dict[str, Any]) -> None:
    result = run_case(case["input"])
    expected = case["expected"]
    assert result.tracks_total == expected["tracks_total"]
    assert result.tracks_recorded == expected["tracks_recorded"]
    assert result.seconds_total == expected["seconds_total"]
    assert result.seconds_recorded == expected["seconds_recorded"]
    assert result.seconds_left == expected["seconds_left"]
    assert result.items_to_record == expected["items_to_record"]
    assert result.unknown_items == expected["unknown_items"]
    # Compared as the contract writes them: the offset of the schedule's zone, and UTC for as_of.
    finish = None if result.finish_at is None else result.finish_at.isoformat(timespec="seconds")
    assert finish == expected["finish_at"]
    as_of = result.as_of.isoformat(timespec="seconds").replace("+00:00", "Z")
    assert as_of == expected["as_of"]


def one_playlist(tracks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "plist00000000000000001",
        "kind": "owned",
        "tracked": True,
        "item_access": True,
        "unavailable": False,
        "tracks": tracks,
    }


def test_a_slow_schedule_still_gives_a_finish_date() -> None:
    # One hour a week (Sunday 01:00-02:00 local). 5 h of music and one item to record is
    # 18,000 s + 35 s: the walk must reach the sixth Sunday, 27 Dec, past the 21-day horizon.
    five_hours = {"id": "t1", "duration_ms": 5 * 3_600_000, "playable": True, "is_local": False}
    backlog = estimate(
        items_from([one_playlist([five_hours])]),
        [],
        {"sun": [1]},
        ZoneInfo("Europe/Berlin"),
        parse("2026-11-15T10:00:00Z"),
    )
    assert backlog.seconds_left == 18_035
    assert backlog.finish_at is not None
    assert backlog.finish_at.isoformat(timespec="seconds") == "2026-12-27T01:00:35+01:00"


def test_manual_only_has_no_finish_date_however_much_is_left() -> None:
    track = {"id": "t1", "duration_ms": 9 * 3_600_000, "playable": True, "is_local": False}
    backlog = estimate(
        items_from([one_playlist([track])]),
        [],
        {day: [] for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
        ZoneInfo("UTC"),
        parse("2026-11-15T10:00:00Z"),
    )
    assert backlog.seconds_left == 32_435
    assert backlog.finish_at is None


def test_a_track_recorded_under_another_item_still_counts_once() -> None:
    track = {"id": "t1", "duration_ms": 1_000, "playable": True, "is_local": False}
    second = {**one_playlist([track]), "id": "plist00000000000000002"}
    backlog = estimate(
        items_from([one_playlist([track]), second]),
        ["t1"],
        {"mon": [1]},
        ZoneInfo("UTC"),
        parse("2026-11-15T10:00:00Z"),
    )
    assert (backlog.tracks_total, backlog.tracks_recorded) == (1, 1)
    assert backlog.seconds_left == 0
    assert backlog.finish_at is None
