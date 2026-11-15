"""catalog/library.py and api/routers/library.py: the Library's endpoints against the contract,
item states, track states, the + modal, and the `library.item` events.

They run on the fake Web API with the fixtures library (see test_catalog_refresh.py), after a
first catalog refresh.
"""

import asyncio
import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from contract import assert_response, assert_schema
from spotivault.catalog.refresh import LIKED_ID
from spotivault.clock import iso_ms
from spotivault.config import Config
from spotivault.errors import ApiError
from spotivault.fake.clock import FakeClock
from spotivault.fake.world import FakeWorld
from spotivault.ports import NoAccess
from spotivault.services import Services
from test_catalog_refresh import (
    FOLLOWED,
    LINKED,
    PLAYLIST,
    PLAYLIST_3,
    PLAYLIST_4,
    PLAYLIST_7,
    add_run,
    connect_fake,
    fail_always,
    item_row,
    world,  # noqa: F401  (a fixture)
)

UNKNOWN = "Z" * 22


@pytest.fixture
async def library(running_app: FastAPI, services: Services, world: FakeWorld) -> FakeWorld:  # noqa: F811
    """A connected container after its first catalog refresh."""
    await connect_fake(services, world)
    result = await services.catalog.refresh(trigger="setup")
    assert result.outcome == "ok"
    world.webapi.calls.clear()
    return world


async def body(response: httpx.Response, path: str, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    assert_response(response, path)
    return response.json() if response.content else None


async def error_code(response: httpx.Response, path: str, status: int) -> str:
    data = await body(response, path, status)
    return data["error"]["code"]


# --- History and the index, written by hand -----------------------------------------------------


class History:
    """Rows S6 will write: runs, run items, takes and files."""

    def __init__(self, services: Services) -> None:
        self.services = services
        self.takes = 0

    async def run(self, *, state: str = "ended") -> int:
        return await add_run(self.services, state=state)

    async def run_item(
        self,
        run_id: int,
        item_id: str,
        state: str,
        *,
        recorded: int = 0,
        planned: int | None = None,
        started: bool = True,
    ) -> int:
        now = iso_ms(self.services.clock.now())
        result = await self.services.store.execute(
            "INSERT INTO run_items (run_id, item_id, queue_pos, state, recorded, planned, "
            "up_to_date_by, started_at) VALUES (?, ?, 0, ?, ?, ?, ?, ?)",
            (
                run_id,
                item_id,
                state,
                recorded,
                planned,
                "nothing_missing" if state == "up_to_date" else None,
                now if started else None,
            ),
        )
        assert result.lastrowid is not None
        return result.lastrowid

    async def take(
        self,
        run_id: int,
        run_item_id: int,
        *,
        track_id: str | None,
        artist: str,
        title: str,
        result: str,
        reason: str | None = None,
        key: str | None = None,
        path: str | None = None,
    ) -> None:
        self.takes += 1
        take_id = f"take-{self.takes}"
        now = iso_ms(self.services.clock.now())
        file_id = None
        if result == "recorded":
            written = await self.services.store.execute(
                "INSERT INTO files (track_id, spytify_key, path, bytes, duration_ms, format, "
                "counted, run_id, take_id, recorded_at) VALUES (?, ?, ?, 4321, 1000, 'aac', 1, "
                "?, ?, ?)",
                (
                    track_id,
                    key or f"{artist}\x1f{title}",
                    path or f"{title}.m4a",
                    run_id,
                    take_id,
                    now,
                ),
            )
            file_id = written.lastrowid
        await self.services.store.execute(
            "INSERT INTO track_results (run_item_id, take_id, track_id, artist, title, planned, "
            "result, reason, file_id, started_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (run_item_id, take_id, track_id, artist, title, result, reason, file_id, now),
        )


def write_index(config: Config, recorded: dict[str, str]) -> None:
    """Spytify's index with these keys → files (relative to the music folder), files made."""
    lines = []
    for key, relative in recorded.items():
        path = config.music_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")
        lines.append(json.dumps({"Key": key, "Path": str(path)}))
    config.spytify_index.parent.mkdir(parents=True, exist_ok=True)
    config.spytify_index.write_text("\n".join(lines) + "\n")


async def keys_of(services: Services, item_id: str) -> list[str | None]:
    rows = await services.store.fetchall(
        "SELECT t.spytify_key FROM item_tracks it LEFT JOIN tracks t ON t.id = it.track_id "
        "WHERE it.item_id = ? ORDER BY it.position",
        (item_id,),
    )
    return [row["spytify_key"] for row in rows]


async def set_backup(services: Services, item_id: str, at: str) -> None:
    await services.store.execute("UPDATE items SET last_backup_at = ? WHERE id = ?", (at, item_id))


# --- Every endpoint against the contract --------------------------------------------------------


async def test_every_library_endpoint_against_the_contract(
    client: httpx.AsyncClient, services: Services, library: FakeWorld
) -> None:
    summary = await body(await client.get("/api/library/summary"), "/api/library/summary")
    assert summary == {
        "owned_count": 17,
        "owned_tracked": 17,
        "liked_tracked": True,
        "added_count": 0,
        "tracked_count": 18,
        "auto_track_owned": True,
    }
    for filter_ in ("all", "tracked", "not_tracked", "owned", "added"):
        for sort in ("recently_backed_up", "name", "recently_added", "track_count"):
            response = await client.get("/api/library", params={"filter": filter_, "sort": sort})
            await body(response, "/api/library")
    listed = await body(await client.get("/api/library"), "/api/library")
    assert len(listed["items"]) == 18

    suggestions = await body(
        await client.get("/api/library/suggestions"), "/api/library/suggestions"
    )
    assert [s["id"] for s in suggestions["items"]] == [FOLLOWED]

    preview = await body(
        await client.post("/api/library/resolve", json={"url": f"spotify:playlist:{LINKED}"}),
        "/api/library/resolve",
    )
    assert (preview["kind"], preview["total"], preview["already_added"]) == ("linked", None, False)

    added = await body(
        await client.post("/api/library", json={"url": f"spotify:playlist:{FOLLOWED}"}),
        "/api/library",
        201,
    )
    assert (added["kind"], added["tracked"], added["removable"]) == ("followed", True, True)

    patched = await body(
        await client.patch(f"/api/library/{PLAYLIST_4}", json={"tracked": False}),
        "/api/library/{id}",
    )
    assert (patched["tracked"], patched["status"]) == (False, "not_tracked")

    for item_id in (PLAYLIST_3, LIKED_ID, FOLLOWED):
        tracks = await body(
            await client.get(f"/api/library/{item_id}/tracks"), "/api/library/{id}/tracks"
        )
        assert tracks["item_id"] == item_id

    response = await client.delete(f"/api/library/{FOLLOWED}")
    assert response.status_code == 204 and response.content == b""


async def test_errors_against_the_contract(client: httpx.AsyncClient, library: FakeWorld) -> None:
    for method, path, template, payload in (
        ("PATCH", f"/api/library/{UNKNOWN}", "/api/library/{id}", {"tracked": True}),
        ("DELETE", f"/api/library/{UNKNOWN}", "/api/library/{id}", None),
        ("GET", f"/api/library/{UNKNOWN}/tracks", "/api/library/{id}/tracks", None),
    ):
        response = await client.request(method, path, json=payload)
        assert await error_code(response, template, 404) == "not_found"

    for item_id in (PLAYLIST_4, LIKED_ID):
        response = await client.delete(f"/api/library/{item_id}")
        assert await error_code(response, "/api/library/{id}", 409) == "not_removable"

    response = await client.post("/api/library", json={"url": "https://example.com/x"})
    assert await error_code(response, "/api/library", 422) == "invalid_url"
    response = await client.post("/api/library/resolve", json={"url": "spotify:album:" + "a" * 22})
    assert await error_code(response, "/api/library/resolve", 422) == "invalid_url"
    response = await client.get("/api/library", params={"filter": "everything"})
    assert response.status_code == 422


# --- Summary and the list -----------------------------------------------------------------------


async def test_the_summary_counts(services: Services, library: FakeWorld) -> None:
    await services.library.add(f"spotify:playlist:{FOLLOWED}")
    await services.library.add(f"spotify:playlist:{LINKED}")
    await services.library.set_tracked(PLAYLIST_4, False)
    await services.library.set_tracked(LIKED_ID, False)
    await services.settings.set_value("auto_track_owned", True)

    summary = await services.library.summary()

    assert (summary.owned_count, summary.owned_tracked, summary.liked_tracked) == (17, 16, False)
    assert (summary.added_count, summary.tracked_count) == (2, 18)
    assert summary.auto_track_owned is True


async def test_filters_search_and_liked_songs_first(services: Services, library: FakeWorld) -> None:
    await services.library.add(f"spotify:playlist:{FOLLOWED}")
    await services.library.add(f"spotify:playlist:{LINKED}")
    await services.library.set_tracked(PLAYLIST_4, False)

    def ids(items: list[Any]) -> list[str]:
        return [item.id for item in items]

    owned = await services.library.list_items(filter="owned")
    assert owned[0].id == LIKED_ID and len(owned) == 18
    added = await services.library.list_items(filter="added", sort="name")
    assert ids(added) == [LINKED, FOLLOWED]  # "Linked Mix" before "Playlist 1"
    assert ids(await services.library.list_items(filter="not_tracked")) == [PLAYLIST_4]
    assert len(await services.library.list_items(filter="tracked")) == 19

    found = await services.library.list_items(q="  PLAYLIST 1", sort="name")
    assert [item.name for item in found] == [f"Playlist {n}" for n in (1, 10, 11, 12, 13, 14)] + [
        f"Playlist {n}" for n in (15, 16, 17, 18)
    ]
    assert ids(await services.library.list_items(q="liked")) == [LIKED_ID]
    assert await services.library.list_items(q="nothing like this") == []
    assert ids(await services.library.list_items(filter="added", q="liked")) == []


async def test_sorts(services: Services, library: FakeWorld, fake_clock: FakeClock) -> None:
    await set_backup(services, PLAYLIST_4, "2026-11-14T03:00:00.000Z")
    await set_backup(services, PLAYLIST_7, "2026-11-15T03:00:00.000Z")
    await set_backup(services, LIKED_ID, "2026-11-13T03:00:00.000Z")
    await fake_clock.advance(10)
    await services.library.add(f"spotify:playlist:{LINKED}")

    by_backup = await services.library.list_items()
    assert [item.id for item in by_backup[:3]] == [LIKED_ID, PLAYLIST_7, PLAYLIST_4]
    assert by_backup[3].last_backup_at is None
    assert [item.name for item in by_backup[3:6]] == ["Linked Mix", "Playlist 10", "Playlist 11"]

    by_name = await services.library.list_items(sort="name")
    assert [item.name for item in by_name[:4]] == [
        "Liked Songs",
        "Linked Mix",
        "Playlist 10",
        "Playlist 11",
    ]

    by_added = await services.library.list_items(sort="recently_added")
    assert [item.id for item in by_added[:2]] == [LIKED_ID, LINKED]

    by_count = await services.library.list_items(sort="track_count")
    counts = [item.total for item in by_count[1:]]
    assert counts[:2] == [400, 368] and counts[-1] is None  # the linked one: unknown, last
    assert by_count[0].id == LIKED_ID


# --- Tracking and removing ----------------------------------------------------------------------


async def test_tracking_an_item_asks_for_a_refresh(services: Services, library: FakeWorld) -> None:
    await services.settings.set_value("auto_track_owned", False)  # nothing tracked now
    item = await services.library.set_tracked(PLAYLIST_4, True)
    assert (item.tracked, item.status) == (True, "never_backed_up")
    await services.catalog.wait_idle()
    rows = await services.store.fetchall("SELECT trigger FROM catalog_refreshes ORDER BY id")
    assert [r["trigger"] for r in rows] == ["setup", "item_added"]

    liked = await services.library.set_tracked(LIKED_ID, True)  # step 7's checkbox
    assert liked.tracked is True and liked.kind == "liked"
    untracked = await services.library.set_tracked(LIKED_ID, False)
    assert (untracked.tracked, untracked.status) == (False, "not_tracked")


async def test_removing_an_added_item_keeps_its_history_and_it_can_come_back(
    services: Services, library: FakeWorld, fake_clock: FakeClock
) -> None:
    await services.library.add(f"spotify:playlist:{FOLLOWED}")
    history = History(services)
    run_id = await history.run()
    run_item = await history.run_item(run_id, FOLLOWED, "done")
    await history.take(run_id, run_item, track_id=None, artist="A", title="One", result="recorded")
    await services.library.remove(FOLLOWED)

    assert await services.library.item(FOLLOWED) is None
    row = await item_row(services, FOLLOWED)
    assert row["removed_at"] is not None and row["tracked"] == 0
    assert FOLLOWED in [s.id for s in await services.library.suggestions()]

    await fake_clock.advance(5)
    item = await services.library.add(f"https://open.spotify.com/playlist/{FOLLOWED}")
    assert (item.tracked, item.recorded, item.status) == (True, 1, "never_backed_up")
    row = await item_row(services, FOLLOWED)
    assert row["removed_at"] is None and row["added_by"] == "user"


# --- The + modal --------------------------------------------------------------------------------


async def test_suggestions_are_followed_playlists_not_in_the_library(
    services: Services, library: FakeWorld
) -> None:
    [suggestion] = await services.library.suggestions()
    assert suggestion.id == FOLLOWED
    assert (suggestion.kind, suggestion.total, suggestion.item_access) == ("followed", 35, False)
    assert suggestion.already_added is False
    assert suggestion.owner == "User One"
    assert suggestion.cover is not None and suggestion.cover.startswith("https://")
    assert library.webapi.calls == []  # no request

    assert [s.id for s in await services.library.suggestions("user one")] == [FOLLOWED]
    assert [s.id for s in await services.library.suggestions("PLAYLIST 1")] == [FOLLOWED]
    assert await services.library.suggestions("Playlist 2") == []

    await services.library.add(f"spotify:playlist:{FOLLOWED}")
    assert await services.library.suggestions() == []


async def test_a_suggestions_cover_is_offered_for_12_hours(
    services: Services, library: FakeWorld, fake_clock: FakeClock
) -> None:
    fake_clock.set_now(fake_clock.now() + timedelta(hours=12, seconds=1))
    [suggestion] = await services.library.suggestions()
    assert suggestion.cover is None


async def test_resolve(services: Services, library: FakeWorld) -> None:
    followed = await services.library.resolve(f"spotify:playlist:{FOLLOWED}")
    assert (followed.kind, followed.total, followed.item_access) == ("followed", 35, False)
    assert followed.name == "Playlist 1" and followed.already_added is False
    linked = await services.library.resolve(f"https://open.spotify.com/playlist/{LINKED}?si=1")
    assert (linked.kind, linked.total, linked.item_access) == ("linked", None, False)
    assert (linked.name, linked.owner) == ("Linked Mix", "Someone Else")
    assert linked.cover is not None
    own = await services.library.resolve(f"spotify:playlist:{PLAYLIST_4}")
    assert own.already_added is True and own.item_access is True
    assert library.webapi.endpoints() == [PLAYLIST] * 3
    assert await item_row(services, LINKED) is None  # nothing added


@pytest.mark.parametrize(
    ("url", "code", "asks"),
    [
        ("open.spotify.com/playlist/x", "invalid_url", False),
        ("https://open.spotify.com/playlist/37i9dQZF1DXLnUtMmNIBbc", "spotify_owned", False),
        (f"spotify:playlist:{UNKNOWN}", "not_found", True),
    ],
)
async def test_links_that_cant_be_used(
    services: Services, library: FakeWorld, url: str, code: str, asks: bool
) -> None:
    for call in (services.library.resolve, services.library.add):
        with pytest.raises(ApiError) as caught:
            await call(url)
        assert (caught.value.status, caught.value.code) == (422, code)
    assert library.webapi.endpoints() == ([PLAYLIST] * 2 if asks else [])


async def test_a_private_playlist(
    client: httpx.AsyncClient, services: Services, library: FakeWorld
) -> None:
    fail_always(library, "playlist", NoAccess("Forbidden", status=403), LINKED)
    response = await client.post("/api/library/resolve", json={"url": f"spotify:playlist:{LINKED}"})
    assert await error_code(response, "/api/library/resolve", 422) == "private"


async def test_without_a_connection_the_modal_says_so(
    client: httpx.AsyncClient, services: Services, library: FakeWorld
) -> None:
    await services.auth.disconnect()
    response = await client.post("/api/library/resolve", json={"url": f"spotify:playlist:{LINKED}"})
    assert await error_code(response, "/api/library/resolve", 409) == "not_connected"
    response = await client.post("/api/library", json={"url": f"spotify:playlist:{LINKED}"})
    assert await error_code(response, "/api/library", 409) == "not_connected"


async def test_adding_what_is_already_there_asks_spotify_nothing(
    client: httpx.AsyncClient, services: Services, library: FakeWorld
) -> None:
    for item_id in (PLAYLIST_4, PLAYLIST_3):
        response = await client.post("/api/library", json={"url": f"spotify:playlist:{item_id}"})
        assert await error_code(response, "/api/library", 409) == "already_added"
    await services.library.add(f"spotify:playlist:{LINKED}")
    library.webapi.calls.clear()
    response = await client.post("/api/library", json={"url": f"spotify:playlist:{LINKED}"})
    assert await error_code(response, "/api/library", 409) == "already_added"
    assert library.webapi.calls == []
    preview = await services.library.resolve(f"spotify:playlist:{LINKED}")
    assert preview.already_added is True


async def test_an_added_item_comes_in_tracked_with_its_cover(
    services: Services, library: FakeWorld
) -> None:
    item = await services.library.add(f"spotify:playlist:{LINKED}")
    assert (item.tracked, item.status, item.owner, item.recorded) == (
        True,
        "never_backed_up",
        "Someone Else",
        0,
    )
    assert item.cover is not None and item.cover.startswith(f"/api/library/{LINKED}/cover")
    assert item.cover_source == "spotify"
    row = await item_row(services, LINKED)
    assert (row["added_by"], row["item_access"], row["total"]) == ("user", 0, None)
    assert row["snapshot_id"] == library.catalog.playlists[LINKED].playlist.snapshot_id


# --- Track lists --------------------------------------------------------------------------------


async def test_track_states(services: Services, library: FakeWorld, config: Config) -> None:
    entries = library.catalog.playlists[PLAYLIST_3].entries
    keys = await keys_of(services, PLAYLIST_3)
    track = [entry.track for entry in entries]
    # 0: recorded, with History's file; 1: recorded by Spytify only (the index's path);
    # 2: skipped as a duplicate in the last run; 3: failed in the last run; 5: new;
    # 4, 8, 11: a local file, an episode and an empty entry; the rest: missing.
    write_index(
        config,
        {keys[0]: "A/One/01 - First.m4a", keys[1]: "B/Two/02 - Second.m4a", keys[2]: "C/x.m4a"},
    )
    services.matching.invalidate()
    history = History(services)
    run_id = await history.run()
    run_item = await history.run_item(run_id, PLAYLIST_3, "partial")
    await history.take(
        run_id,
        run_item,
        track_id=track[0].id,
        artist=track[0].artists[0],
        title=track[0].name,
        result="recorded",
        key=keys[0],
        path="A/One/01 - First.m4a",
    )
    for position, result, reason in ((2, "skipped", "duplicate"), (3, "failed", "too_short")):
        await history.take(
            run_id,
            run_item,
            track_id=track[position].id,
            artist="x",
            title="y",
            result=result,
            reason=reason,
        )
    await set_backup(services, PLAYLIST_3, "2026-11-01T03:00:00.000Z")
    await services.store.execute(
        "UPDATE item_tracks SET added_at = '2026-11-10T00:00:00Z' WHERE item_id = ? "
        "AND position = 5",
        (PLAYLIST_3,),
    )

    tracks = await services.library.tracks(PLAYLIST_3)

    assert_schema("TrackList", tracks.model_dump(mode="json"))
    assert (tracks.item_access, tracks.total) == (True, 13)
    assert tracks.duration_ms == sum(
        e.track.duration_ms for i, e in enumerate(entries) if i not in (4, 8, 11) and e.track
    )
    states = [t.state for t in tracks.tracks]
    assert states[:6] == [
        "recorded",
        "recorded",
        "skipped_duplicate",
        "failed",
        "unplayable",
        "new",
    ]
    assert [states[i] for i in (8, 11)] == ["unplayable", "unplayable"]
    assert set(states[6:8] + states[9:11] + states[12:]) == {"missing"}
    assert [t.position for t in tracks.tracks] == list(range(1, 17))
    first, second, duplicate, failed, local = tracks.tracks[:5]
    assert (first.size_bytes, first.path) == (4321, "A/One/01 - First.m4a")
    assert first.recorded_at is not None
    assert (second.size_bytes, second.path, second.recorded_at) == (
        None,
        "B/Two/02 - Second.m4a",
        None,
    )
    assert duplicate.path == "C/x.m4a"
    assert (failed.reason, failed.path) == ("too_short", None)
    assert (local.title, local.track_id, local.artists) == ("Local file", None, [])
    assert tracks.tracks[11].title == "Empty entry"
    assert tracks.tracks[8].title == "Episode 12: Tape Machines"
    assert (first.title, first.artists) == (track[0].name, list(track[0].artists))

    item = await services.library.item(PLAYLIST_3)
    assert item is not None
    assert (item.total, item.recorded, item.status) == (13, 3, "partial")


async def test_a_playlist_without_item_access_lists_what_history_recorded(
    services: Services, library: FakeWorld
) -> None:
    await services.library.add(f"spotify:playlist:{FOLLOWED}")
    history = History(services)
    run_id = await history.run()
    run_item = await history.run_item(run_id, FOLLOWED, "done")
    for title in ("Zebra", "Apple", "Zebra"):  # the second Zebra is the same track again
        await history.take(
            run_id, run_item, track_id=None, artist="Band", title=title, result="recorded"
        )
    await history.take(
        run_id,
        run_item,
        track_id=None,
        artist="Band",
        title="Gone",
        result="failed",
        reason="silent",
    )
    await set_backup(services, FOLLOWED, iso_ms(services.clock.now()))

    tracks = await services.library.tracks(FOLLOWED)

    assert_schema("TrackList", tracks.model_dump(mode="json"))
    assert (tracks.item_access, tracks.total, tracks.duration_ms) == (False, 35, None)
    assert [(t.title, t.position, t.state) for t in tracks.tracks] == [
        ("Zebra", None, "recorded"),
        ("Apple", None, "recorded"),
    ]
    assert tracks.tracks[0].artists == ["Band"] and tracks.tracks[0].size_bytes == 4321
    item = await services.library.item(FOLLOWED)
    assert item is not None
    # No `new` without item access: after a backup it's up to date.
    assert (item.total, item.recorded, item.new, item.status) == (35, 2, None, "up_to_date")


# --- Item states --------------------------------------------------------------------------------


async def test_item_states(services: Services, library: FakeWorld, config: Config) -> None:
    keys = await keys_of(services, PLAYLIST_4)
    write_index(config, {key: f"x/{n}.m4a" for n, key in enumerate(keys) if key})  # all of it
    services.matching.invalidate()
    await set_backup(services, PLAYLIST_4, "2026-11-14T03:00:00.000Z")
    await set_backup(services, PLAYLIST_7, "2026-11-14T03:00:00.000Z")  # all missing, none new
    await set_backup(services, LIKED_ID, "2026-01-01T00:00:00.000Z")  # newer ones are new
    await services.library.set_tracked(PLAYLIST_3, False)
    await services.store.execute(
        "UPDATE items SET unavailable_at = '2026-11-14T00:00:00Z', unavailable_reason = "
        "'deleted' WHERE id = ?",
        ("aqdBzl0sHtRDsAWj1IXaVH",),  # Playlist 9
    )
    history = History(services)
    run_id = await history.run(state="running")
    await history.run_item(run_id, "Cli87inw2Mt0hYNsktt8sU", "playing", recorded=3, planned=10)
    await history.run_item(run_id, "7IV4GWURLDq0deCgGnfZMv", "up_next", started=False)

    items = {item.id: item for item in await services.library.list_items()}

    p4 = items[PLAYLIST_4]
    assert (p4.status, p4.total, p4.recorded, p4.new) == ("up_to_date", 84, 84, 0)
    assert items[PLAYLIST_7].status == "up_to_date"  # missing, not new: nothing to show
    liked = items[LIKED_ID]
    assert liked.status == "new" and liked.new is not None and 0 < liked.new < 277
    assert items[PLAYLIST_3].status == "not_tracked"
    assert items["aqdBzl0sHtRDsAWj1IXaVH"].status == "unavailable"
    assert items["V3u8lPM46r3Pqf00jaleWH"].status == "never_backed_up"  # Playlist 17
    recording = items["Cli87inw2Mt0hYNsktt8sU"]  # Playlist 5
    assert recording.status == "recording"
    assert recording.progress is not None
    assert recording.progress.model_dump() == {
        "run_id": run_id,
        "state": "playing",
        "recorded": 3,
        "planned": 10,
    }
    queued = items["7IV4GWURLDq0deCgGnfZMv"]  # Playlist 8
    assert queued.status == "queued" and queued.progress is not None
    assert items[PLAYLIST_4].progress is None
    for item in items.values():
        assert_schema("LibraryItem", item.model_dump(mode="json"))


# --- Events -------------------------------------------------------------------------------------


@pytest.fixture
def published(services: Services, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The `library.item` events published, newest last."""
    seen: list[dict[str, Any]] = []
    publish = services.bus.publish

    def record(type: str, data: Any) -> Any:
        event = publish(type, data)
        if type == "library.item":
            seen.append(event.data)
        return event

    monkeypatch.setattr(services.bus, "publish", record)
    return seen


async def test_publish_sends_at_most_one_event_per_item_per_second(
    services: Services, library: FakeWorld, fake_clock: FakeClock, published: list[Any]
) -> None:
    await fake_clock.advance(1)  # past the refresh's own events
    await services.library.publish(PLAYLIST_4)
    assert [e["id"] for e in published] == [PLAYLIST_4]
    await services.library.publish(PLAYLIST_4)
    await services.store.execute("UPDATE items SET tracked = 0 WHERE id = ?", (PLAYLIST_4,))
    await services.library.publish(PLAYLIST_4)
    await services.library.publish(PLAYLIST_7)  # another item isn't held back
    assert [e["id"] for e in published] == [PLAYLIST_4, PLAYLIST_7]

    await fake_clock.advance(0.5)
    assert len(published) == 2
    await fake_clock.advance(0.5)
    for _ in range(50):  # the merged event reads the item on the database thread
        if len(published) == 3:
            break
        await fake_clock.settle()
        await asyncio.sleep(0.01)
    assert [e["id"] for e in published] == [PLAYLIST_4, PLAYLIST_7, PLAYLIST_4]
    assert published[-1]["tracked"] is False  # the item as it is when sent
    assert_schema("LibraryItem", published[-1])

    await services.library.publish("Z" * 22)  # no such item: nothing, no error
    assert len(published) == 3


async def test_tracking_publishes_the_item(
    services: Services, library: FakeWorld, fake_clock: FakeClock, published: list[Any]
) -> None:
    await fake_clock.advance(1)  # past the refresh's own events
    await services.library.set_tracked(PLAYLIST_4, False)
    assert [(e["id"], e["tracked"]) for e in published] == [(PLAYLIST_4, False)]
    await services.library.set_tracked(PLAYLIST_7, True)  # unchanged: no event
    assert len(published) == 1
