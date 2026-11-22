"""The Library's Refresh button: POST /api/library/refresh (catalog/refresh.py `request_manual`)
and the `catalog.refresh` events every refresh sends (events.md § Catalog refresh).

On the fake Web API with the fixtures library (see test_catalog_refresh.py), after a first
catalog refresh.
"""

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from contract import assert_response, assert_schema
from spotivault.catalog.refresh import THROTTLE_S
from spotivault.clock import iso_ms
from spotivault.fake.clock import FakeClock
from spotivault.fake.world import FakeWorld
from spotivault.ports import RateLimited, SpotifyUnavailable, WebApiError
from spotivault.services import Services
from test_catalog_refresh import (
    add_run,
    connect_fake,
    world,  # noqa: F401  (a fixture)
)

PATH = "/api/library/refresh"


@pytest.fixture
async def library(running_app: FastAPI, services: Services, world: FakeWorld) -> FakeWorld:  # noqa: F811
    """A connected container after its first catalog refresh."""
    await connect_fake(services, world)
    result = await services.catalog.refresh(trigger="setup")
    assert result.outcome == "ok"
    world.webapi.calls.clear()
    return world


@pytest.fixture
def events(services: Services, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """The `catalog.refresh` and `library.item` events published from now on, in order."""
    seen: list[tuple[str, Any]] = []
    publish = services.bus.publish

    def record(type: str, data: Any) -> Any:
        event = publish(type, data)
        if type in ("catalog.refresh", "library.item"):
            seen.append((type, event.data))
        return event

    monkeypatch.setattr(services.bus, "publish", record)
    return seen


def refresh_events(events: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    return [data for type, data in events if type == "catalog.refresh"]


async def press(client: httpx.AsyncClient, status: int = 202) -> Any:
    response = await client.post(PATH)
    assert response.status_code == status, response.text
    assert_response(response, PATH)
    return response.json()


async def triggers(services: Services) -> list[str]:
    rows = await services.store.fetchall("SELECT trigger FROM catalog_refreshes ORDER BY id")
    return [row["trigger"] for row in rows]


def hold_listing(fake: FakeWorld) -> tuple[asyncio.Event, asyncio.Event]:
    """The fake Web API's next playlist listing waits until `release` is set; `reached` is set
    once a refresh is inside it."""
    reached, release = asyncio.Event(), asyncio.Event()
    original: Callable[..., Any] = fake.webapi.my_playlists

    async def held(*args: Any, **kwargs: Any) -> Any:
        reached.set()
        await release.wait()
        return await original(*args, **kwargs)

    fake.webapi.my_playlists = held  # type: ignore[method-assign]
    return reached, release


# --- The endpoint -------------------------------------------------------------------------------


async def test_a_press_starts_a_manual_refresh(
    client: httpx.AsyncClient,
    services: Services,
    library: FakeWorld,
    events: list[tuple[str, Any]],
) -> None:
    assert await press(client) == {"state": "started", "refresh_id": None}
    await services.catalog.wait_idle()

    assert await triggers(services) == ["setup", "manual"]
    assert "GET /me/playlists" in library.webapi.endpoints()
    started, ended = refresh_events(events)
    refresh_id = await services.store.fetchval("SELECT MAX(id) FROM catalog_refreshes")
    assert started == {
        "refresh_id": refresh_id,
        "trigger": "manual",
        "state": "started",
        "outcome": None,
        "items_changed": None,
        "items_added": None,
        "suggestions_added": None,
        "reason": None,
    }
    assert ended == {
        "refresh_id": refresh_id,
        "trigger": "manual",
        "state": "ended",
        "outcome": "ok",
        "items_changed": 0,
        "items_added": 0,
        "suggestions_added": 0,
        "reason": None,
    }


async def test_a_manual_refresh_isnt_held_back_by_the_15_minutes(
    client: httpx.AsyncClient, services: Services, library: FakeWorld, fake_clock: FakeClock
) -> None:
    # The setup refresh just ran: a page open is throttled, the button isn't.
    assert services.catalog.request_refresh("page_open") is False
    assert await press(client) == {"state": "started", "refresh_id": None}
    await services.catalog.wait_idle()
    assert await press(client) == {"state": "started", "refresh_id": None}
    await services.catalog.wait_idle()
    assert await triggers(services) == ["setup", "manual", "manual"]

    # And it counts as the last refresh for the page opens' 15 minutes.
    fake_clock.set_now(fake_clock.now() + timedelta(seconds=THROTTLE_S - 1))
    assert services.catalog.request_refresh("page_open") is False


async def test_a_second_press_joins_the_refresh_already_asked_for(
    client: httpx.AsyncClient, services: Services, library: FakeWorld
) -> None:
    # The second press lands before the first one's refresh ends (it may have started).
    answers = await asyncio.gather(press(client), press(client))
    await services.catalog.wait_idle()
    assert await triggers(services) == ["setup", "manual"]
    manual_id = await services.store.fetchval("SELECT MAX(id) FROM catalog_refreshes")
    started, joined = sorted(answers, key=lambda answer: answer["state"] != "started")
    assert started == {"state": "started", "refresh_id": None}
    assert joined["state"] == "running" and joined["refresh_id"] in (None, manual_id)


async def test_a_press_while_a_refresh_runs_joins_it(
    client: httpx.AsyncClient,
    services: Services,
    library: FakeWorld,
    events: list[tuple[str, Any]],
) -> None:
    reached, release = hold_listing(library)
    assert services.catalog.request_refresh("item_added") is True
    await reached.wait()
    running_id = await services.store.fetchval("SELECT MAX(id) FROM catalog_refreshes")

    assert await press(client) == {"state": "running", "refresh_id": running_id}
    assert await press(client) == {"state": "running", "refresh_id": running_id}
    release.set()
    await services.catalog.wait_idle()

    assert await triggers(services) == ["setup", "item_added"]  # no second refresh
    ended = refresh_events(events)[-1]
    assert (ended["refresh_id"], ended["state"], ended["outcome"]) == (running_id, "ended", "ok")


async def test_a_press_while_watch_has_taken_the_manual_refresh_joins_it(
    client: httpx.AsyncClient,
    services: Services,
    library: FakeWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `watch` has taken the queued `manual` refresh, but its row isn't written yet: no id to give.
    catalog = services.catalog
    reached, release = asyncio.Event(), asyncio.Event()
    insert_row = catalog._insert_row

    async def held(*args: Any, **kwargs: Any) -> Any:
        reached.set()
        await release.wait()
        return await insert_row(*args, **kwargs)

    monkeypatch.setattr(catalog, "_insert_row", held)
    assert await press(client) == {"state": "started", "refresh_id": None}
    await reached.wait()
    assert await press(client) == {"state": "running", "refresh_id": None}
    release.set()
    await catalog.wait_idle()
    assert await triggers(services) == ["setup", "manual"]  # one refresh for both presses


async def test_queued_triggers_with_manual_run_as_a_manual_refresh(
    services: Services, library: FakeWorld, events: list[tuple[str, Any]]
) -> None:
    # A press joins a queued `item_added`; the button then waits for an `ended` named `manual`.
    services.catalog._queue("item_added")
    services.catalog._queue("manual")
    await services.catalog.wait_idle()
    assert await triggers(services) == ["setup", "manual"]
    assert [e["trigger"] for e in refresh_events(events)] == ["manual", "manual"]


async def test_refused_during_a_run(
    client: httpx.AsyncClient, services: Services, library: FakeWorld
) -> None:
    await add_run(services)
    data = await press(client, 409)
    assert data["error"]["code"] == "run_active"
    await services.catalog.wait_idle()
    assert await triggers(services) == ["setup"]
    assert library.webapi.calls == []


async def test_refused_without_a_connection(
    client: httpx.AsyncClient, services: Services, library: FakeWorld
) -> None:
    await services.auth.mark_invalid_grant()  # Spotify answered invalid_grant
    assert (await press(client, 409))["error"]["code"] == "connection_expired"
    await services.auth.disconnect()
    assert (await press(client, 409))["error"]["code"] == "not_connected"
    await services.catalog.wait_idle()
    assert await triggers(services) == ["setup"]
    assert library.webapi.calls == []


async def test_a_connection_past_its_expiry_date_still_refreshes(
    client: httpx.AsyncClient, services: Services, library: FakeWorld
) -> None:
    # As every refresh: the 6-month date holds scheduled runs, but only invalid_grant refuses.
    past = iso_ms(services.clock.now() - timedelta(days=1))
    await services.store.execute("UPDATE spotify_auth SET expires_at = ? WHERE id = 1", (past,))
    assert (await services.connection.connection()).state == "expired"
    assert (await press(client))["state"] == "started"
    await services.catalog.wait_idle()
    assert await triggers(services) == ["setup", "manual"]


# --- What the events say ------------------------------------------------------------------------


async def test_the_ended_event_counts_new_playlists_and_suggestions(
    client: httpx.AsyncClient,
    services: Services,
    library: FakeWorld,
    events: list[tuple[str, Any]],
) -> None:
    made = library.catalog.add_playlist("Road Trip", tracks=3)  # you made it in Spotify
    followed = library.catalog.add_playlist("Friday Finds", tracks=5, access="followed")

    await press(client)
    await services.catalog.wait_idle()

    ended = refresh_events(events)[-1]
    assert (ended["outcome"], ended["items_added"], ended["suggestions_added"]) == ("ok", 1, 1)
    assert ended["items_changed"] >= 1
    # The new item's library.item comes before `ended`, so the list has it when the toast shows.
    new_item = events.index(next(e for e in events if e[1].get("id") == made.playlist.id))
    assert new_item < events.index(("catalog.refresh", ended))
    assert_schema("LibraryItem", dict(events[new_item][1]))
    suggestions = await services.library.suggestions(None)
    assert followed.playlist.id in [s.id for s in suggestions]

    # Nothing new the next time.
    await press(client)
    await services.catalog.wait_idle()
    ended = refresh_events(events)[-1]
    assert (ended["items_added"], ended["suggestions_added"]) == (0, 0)


async def test_a_refresh_a_run_drops_says_skipped(
    services: Services, library: FakeWorld, events: list[tuple[str, Any]]
) -> None:
    answer = await services.catalog.request_manual()
    assert answer.state == "started"
    await add_run(services)  # starts before the queued refresh's turn
    await services.catalog.wait_idle()

    assert await triggers(services) == ["setup"]
    assert refresh_events(events) == [
        {
            "refresh_id": None,
            "trigger": "manual",
            "state": "ended",
            "outcome": "skipped",
            "items_changed": 0,
            "items_added": 0,
            "suggestions_added": 0,
            "reason": "run_active",
        }
    ]


async def test_a_refresh_that_fails_still_sends_ended(
    services: Services,
    library: FakeWorld,
    events: list[tuple[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("a bug")

    monkeypatch.setattr(library.webapi, "my_playlists", broken)
    await services.catalog.request_manual()
    await services.catalog.wait_idle()

    started, ended = refresh_events(events)
    assert started["state"] == "started"
    assert (ended["refresh_id"], ended["state"], ended["outcome"], ended["reason"]) == (
        started["refresh_id"],
        "ended",
        "failed",
        "internal",
    )
    assert services.fatal_errors == []


async def test_spotify_ending_the_connection_mid_refresh_says_so(
    client: httpx.AsyncClient,
    services: Services,
    library: FakeWorld,
    events: list[tuple[str, Any]],
) -> None:
    library.webapi.expired = True  # Spotify answers invalid_grant
    await press(client)
    await services.catalog.wait_idle()

    ended = refresh_events(events)[-1]
    assert (ended["outcome"], ended["reason"]) == ("failed", "connection_expired")
    # Not "try again later": the next press is refused for the same reason.
    assert (await press(client, 409))["error"]["code"] == "connection_expired"


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (RateLimited("429", retry_after_s=30), "rate_limited"),
        (SpotifyUnavailable("503 after the retries"), "spotify_unavailable"),
        (WebApiError("400: bad request", status=400), "spotify_unavailable"),  # as errors.py
    ],
)
async def test_a_listing_spotify_refuses_says_why(
    services: Services,
    library: FakeWorld,
    events: list[tuple[str, Any]],
    failure: WebApiError,
    reason: str,
) -> None:
    library.webapi.failures.append(failure)  # the listing's first request
    await services.catalog.request_manual()
    await services.catalog.wait_idle()
    ended = refresh_events(events)[-1]
    assert (ended["outcome"], ended["reason"]) == ("failed", reason)


async def test_every_trigger_sends_its_events(
    services: Services, library: FakeWorld, events: list[tuple[str, Any]]
) -> None:
    run_id = await add_run(services)
    result = await services.catalog.refresh(trigger="run", run_id=run_id)
    assert [(e["trigger"], e["state"], e["outcome"]) for e in refresh_events(events)] == [
        ("run", "started", None),
        ("run", "ended", "ok"),
    ]
    assert refresh_events(events)[-1]["refresh_id"] == result.refresh_id


async def test_a_refresh_without_a_connection_says_skipped(
    services: Services, library: FakeWorld, events: list[tuple[str, Any]]
) -> None:
    await services.auth.mark_invalid_grant()
    assert (await services.catalog.refresh(trigger="setup")).outcome == "skipped"
    await services.auth.disconnect()
    assert (await services.catalog.refresh(trigger="setup")).outcome == "skipped"
    assert [
        (e["refresh_id"], e["state"], e["outcome"], e["reason"]) for e in refresh_events(events)
    ] == [
        (None, "ended", "skipped", "connection_expired"),
        (None, "ended", "skipped", "not_connected"),
    ]
