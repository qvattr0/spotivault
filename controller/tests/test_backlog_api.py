"""GET /api/backlog against the contract, the hello's `backlog` key, and the `backlog` event: the
service reads the database and the index, keeps the last estimate, and publishes it on change."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from asgi_ws import websocket_connect
from contract import assert_response, assert_schema
from spotivault.matching import track_key
from spotivault.services import Services

ITEM = "a9poFNKiHX6sRmXWJ3e0mn"
TRACK_A = "tr00000000000000000011"
TRACK_B = "tr00000000000000000012"
NOW = "2026-11-15T00:00:00.000Z"


def parse_instant(text: str) -> datetime:
    """An RFC 3339 time as an instant, whatever its offset spelling."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def seed_library(conn: Any) -> None:
    """One tracked owned playlist of two tracks (3 min each), fetched, and nothing recorded yet."""
    for track_id, title in ((TRACK_A, "First"), (TRACK_B, "Second")):
        conn.execute(
            "INSERT INTO tracks (id, uri, name, artists, duration_ms, spytify_key, fetched_at) "
            "VALUES (?, ?, ?, ?, 180000, ?, ?)",
            (
                track_id,
                f"spotify:track:{track_id}",
                title,
                json.dumps(["Band"]),
                track_key("Band", title),
                NOW,
            ),
        )
    conn.execute(
        "INSERT INTO items (id, kind, uri, name, added_by, added_at, tracked, item_access, "
        "catalog_fetched_at) VALUES (?, 'owned', ?, 'Mix', 'user', ?, 1, 1, ?)",
        (ITEM, f"spotify:playlist:{ITEM}", NOW, NOW),
    )
    for position, track_id in enumerate((TRACK_A, TRACK_B)):
        conn.execute(
            "INSERT INTO item_tracks (item_id, position, track_id, playable, added_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (ITEM, position, track_id, NOW),
        )


def record_track_a(music_dir: Path) -> None:
    """Spytify's index says the first track is recorded: its key, and a file that exists."""
    recorded = music_dir / "first.flac"
    recorded.write_bytes(b"audio")
    index = music_dir / ".spytify" / "recorded.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        json.dumps({"Key": track_key("Band", "First"), "Path": str(recorded)}) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def refreshes(services: Services, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records the catalog refreshes the backlog asks for, instead of running the catalog."""
    asked: list[str] = []

    def request_refresh(trigger: str) -> bool:
        asked.append(trigger)
        return True

    monkeypatch.setattr(services.catalog, "request_refresh", request_refresh)
    return asked


async def test_nothing_is_estimated_before_start(services: Services) -> None:
    assert await services.backlog.snapshot() is None


async def test_the_hello_carries_the_estimate(running_app: FastAPI) -> None:
    async with websocket_connect(running_app, "/api/events") as ws:
        hello = await ws.receive_json()
    backlog = hello["data"]["backlog"]
    assert backlog is not None  # the start-up estimate, of an empty library
    assert backlog["tracks_total"] == 0
    assert backlog["finish_at"] is None
    assert_schema("Backlog", backlog)


async def test_get_backlog_answers_the_contract(
    client: httpx.AsyncClient, services: Services, refreshes: list[str]
) -> None:
    response = await client.get("/api/backlog")
    assert response.status_code == 200
    assert_response(response, "/api/backlog")
    assert parse_instant(response.json()["as_of"]) == parse_instant("2026-11-15T00:00:00Z")
    assert refreshes == ["page_open"]


async def test_the_estimate_follows_the_library_and_the_index(
    running_app: FastAPI,
    services: Services,
    music_dir: Path,
    refreshes: list[str],
    client: httpx.AsyncClient,
) -> None:
    await services.store.transaction(seed_library)
    await services.store.execute(
        "INSERT INTO schedule_hours (day, hour) VALUES (6, 1)"  # Sunday 01:00, the container's TZ
    )
    record_track_a(music_dir)
    services.matching.invalidate()

    # GET answers the last estimate; a refresh (here, the test's) is what makes a new one.
    await services.backlog.update()
    response = await client.get("/api/backlog")
    body = response.json()
    assert_response(response, "/api/backlog")
    assert body["tracks_total"] == 2
    assert body["tracks_recorded"] == 1
    assert body["seconds_total"] == 360
    assert body["seconds_recorded"] == 180
    assert body["seconds_left"] == 180 + 35  # the second track, and the item's overhead
    assert body["items_to_record"] == 1
    assert body["unknown_items"] == 0
    assert body["items_measuring"] == 0
    # The tests' TZ is UTC: Sunday 01:00 is the window that starts 1 h after the fake clock's
    # start (00:00 UTC, 15 Nov), so the 215 s left finish 3 min 35 s into it.
    assert parse_instant(body["finish_at"]) == parse_instant("2026-11-15T01:03:35Z")


async def test_the_event_only_follows_a_change_in_the_figures(
    running_app: FastAPI,
    services: Services,
    music_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[str] = []
    real_publish = services.bus.publish

    def record(type: str, data: Any) -> Any:
        published.append(type)
        return real_publish(type, data)

    monkeypatch.setattr(services.bus, "publish", record)
    await services.backlog.update()
    assert published == []  # nothing changed since the start-up estimate

    await services.store.transaction(seed_library)
    await services.backlog.update()
    assert published == ["backlog"]

    services.matching.invalidate()
    record_track_a(music_dir)
    await services.backlog.update()
    assert published == ["backlog", "backlog"]  # the recorded track changed the figures

    await services.backlog.update()
    assert published == ["backlog", "backlog"]


async def test_the_hello_and_the_answer_agree(
    running_app: FastAPI, services: Services, client: httpx.AsyncClient, refreshes: list[str]
) -> None:
    await services.store.transaction(seed_library)
    await services.backlog.update()
    async with websocket_connect(running_app, "/api/events") as ws:
        hello = await ws.receive_json()
    answer = await client.get("/api/backlog")
    assert hello["data"]["backlog"] == answer.json()


async def test_a_playlist_not_fetched_yet_is_measuring(
    running_app: FastAPI, services: Services, client: httpx.AsyncClient, refreshes: list[str]
) -> None:
    """An owned playlist the catalog hasn't read yet (catalog_fetched_at NULL) is measuring, not
    unknown: the Full backup card and step 9 show "Measuring" for it. Once it's fetched, it's
    counted by its tracks."""
    await services.store.transaction(seed_library)
    await services.store.execute("UPDATE items SET catalog_fetched_at = NULL WHERE id = ?", (ITEM,))
    await services.backlog.update()
    response = await client.get("/api/backlog")
    assert_response(response, "/api/backlog")
    body = response.json()
    assert body["items_measuring"] == 1
    assert body["unknown_items"] == 0
    assert (body["tracks_total"], body["seconds_left"], body["items_to_record"]) == (0, 0, 0)

    await services.store.execute(
        "UPDATE items SET catalog_fetched_at = ? WHERE id = ?", (NOW, ITEM)
    )
    await services.backlog.update()
    body = (await client.get("/api/backlog")).json()
    assert body["items_measuring"] == 0
    assert body["tracks_total"] == 2
