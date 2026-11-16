"""history.py and History's endpoints: the run list and its cursor, a run's page, an item's takes in
one run, the Dashboard's Last run, and the rows `run.finished` carries (S6, history-files-metrics).

The rows are written by hand here: the run engine that writes them is another builder's. The
shapes are the contract's (openapi.yaml, schema.sql) and each answer is checked against it.
"""

import base64
import json
import sqlite3
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from contract import assert_response, assert_schema
from spotivault.api.models import HistoryRow
from spotivault.errors import ApiError
from spotivault.history import decode_cursor, encode_cursor, issue_message
from spotivault.services import Services

# Ids that satisfy the schema: 22 base-62 characters.
PLAYLIST_A = "a" * 22
PLAYLIST_B = "b" * 22
PLAYLIST_C = "c" * 22
PLAYLIST_D = "d" * 22
ALBUM = "e" * 22
PLAYLIST_X = "f" * 22
PLAYLIST_Y = "g" * 22
PLAYLIST_V = "h" * 22
PLAYLIST_Z = "i" * 22
PLAYLIST_W = "j" * 22
NO_ITEM = "k" * 22


def at(day: int, hour: int = 0) -> str:
    """A time in November 2026, in the database's format."""
    return f"2026-11-{day:02d}T{hour:02d}:00:00.000Z"


def track_id(number: int) -> str:
    return f"{number:022d}"


# --- Seeding ------------------------------------------------------------------------------------


def seed_item(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    kind: str = "owned",
    name: str = "Mix",
    removed_at: str | None = None,
    thumb_path: str | None = None,
    image_id: str | None = None,
) -> None:
    artist = total = None
    if kind == "album":
        artist, total = "Artist", 5
    conn.execute(
        "INSERT INTO items (id, kind, uri, name, artist, total, added_by, added_at, tracked, "
        "item_access, removed_at, thumb_path, image_id) "
        "VALUES (?, ?, ?, ?, ?, ?, 'user', ?, 1, 1, ?, ?, ?)",
        (
            item_id,
            kind,
            f"spotify:playlist:{item_id}",
            name,
            artist,
            total,
            at(1),
            removed_at,
            thumb_path,
            image_id,
        ),
    )


def seed_run(
    conn: sqlite3.Connection,
    *,
    kind: str = "run",
    trigger: str = "run_now",
    state: str | None = "ended",
    outcome: str | None = "completed",
    started_at: str,
    ended_at: str | None = None,
    window: tuple[str, str] | None = None,
    reason: str | None = None,
    counters: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0),
) -> int:
    """A `runs` row. Counters and state only exist on kind run, as the schema requires."""
    if kind != "run":
        state, outcome, counters = None, None, (None,) * 5  # type: ignore[assignment]
    window_start, window_end = window if window else (None, None)
    cursor = conn.execute(
        "INSERT INTO runs (kind, trigger, state, outcome, reason, started_at, ended_at, "
        "window_start, window_end, recorded, skipped_duplicate, skipped_other, failed, "
        "bytes_added) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            kind,
            trigger,
            state,
            outcome,
            reason,
            started_at,
            ended_at,
            window_start,
            window_end,
            *counters,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def seed_run_item(
    conn: sqlite3.Connection,
    run_id: int,
    item_id: str,
    *,
    queue_pos: int,
    state: str = "done",
    ran_order: int | None = None,
    failed: int = 0,
    recorded: int = 0,
    skipped: int = 0,
    interrupted_count: int = 0,
    carried_over_in: int = 0,
    carried_over_out: int = 0,
    reason: str | None = None,
    up_to_date_by: str | None = None,
) -> int:
    started = at(1, 1) if ran_order is not None else None
    ended = at(1, 2) if ran_order is not None else None
    if state == "up_to_date":
        up_to_date_by = up_to_date_by or "nothing_missing"
    cursor = conn.execute(
        "INSERT INTO run_items (run_id, item_id, queue_pos, ran_order, state, mode, "
        "up_to_date_by, carried_over_in, carried_over_out, interrupted_count, recorded, skipped, "
        "failed, bytes, started_at, ended_at, reason) "
        "VALUES (?, ?, ?, ?, ?, 'missing_only', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            item_id,
            queue_pos,
            ran_order,
            state,
            up_to_date_by,
            carried_over_in,
            carried_over_out,
            interrupted_count,
            recorded,
            skipped,
            failed,
            1000 * recorded,
            started,
            ended,
            reason,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def seed_track(conn: sqlite3.Connection, number: int, artists: list[str], name: str) -> str:
    tid = track_id(number)
    conn.execute(
        "INSERT INTO tracks (id, uri, name, artists, duration_ms, spytify_key, fetched_at) "
        "VALUES (?, ?, ?, ?, 180000, ?, ?)",
        (tid, f"spotify:track:{tid}", name, json.dumps(artists), name.lower(), at(1)),
    )
    return tid


def seed_file(conn: sqlite3.Connection, run_id: int, path: str, size: int) -> int:
    cursor = conn.execute(
        "INSERT INTO files (spytify_key, path, bytes, duration_ms, format, counted, run_id, "
        "take_id, recorded_at) VALUES (?, ?, ?, 180000, 'aac', 1, ?, ?, ?)",
        (path, path, size, run_id, f"take-{path}", at(1)),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def seed_take(
    conn: sqlite3.Connection,
    run_item_id: int,
    take_id: str,
    *,
    artist: str,
    title: str,
    started: str,
    result: str | None,
    reason: str | None = None,
    position: int | None = None,
    track: str | None = None,
    file_id: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO track_results (run_item_id, take_id, track_id, position, artist, title, "
        "planned, result, reason, file_id, started_at, finished_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
        (
            run_item_id,
            take_id,
            track,
            position,
            artist,
            title,
            result,
            reason,
            file_id,
            started,
            None if result is None else started,
        ),
    )


async def seed(services: Services, fn: Any) -> Any:
    return await services.store.transaction(fn)


# --- Cursor and messages (pure) -------------------------------------------------------------------


def test_a_cursor_round_trips() -> None:
    cursor = encode_cursor("2026-11-15T01:00:00.000Z", 42)
    assert decode_cursor(cursor) == ("2026-11-15T01:00:00.000Z", 42)


@pytest.mark.parametrize(
    "cursor",
    [
        "not a cursor!!",
        base64.urlsafe_b64encode(b"[1, 2]").decode(),
        base64.urlsafe_b64encode(b'["2026-11-15T01:00:00.000Z", 0]').decode(),
        base64.urlsafe_b64encode(b'["2026-11-15T01:00:00.000Z", true]').decode(),
        base64.urlsafe_b64encode(b'["yesterday", 3]').decode(),
        base64.urlsafe_b64encode(b'"just text"').decode(),
    ],
)
def test_a_cursor_that_doesnt_decode_is_refused(cursor: str) -> None:
    with pytest.raises(ApiError) as caught:
        decode_cursor(cursor)
    assert caught.value.status == 422 and caught.value.code == "validation_failed"
    assert caught.value.details == {"field": "cursor"}


@pytest.mark.parametrize(
    ("state", "failed", "reasons", "reason", "message"),
    [
        ("partial", 2, ["low_volume"], None, "2 tracks failed: low volume"),
        (
            "partial",
            1,
            ["low_volume", "interrupted"],
            None,
            "1 track failed: low volume, interrupted",
        ),
        ("done", 1, ["discarded"], None, "1 track failed: discarded by Stop now"),
        ("partial", 3, [], None, "3 tracks failed"),
        ("partial", 0, [], "Playback paused for 20 s twice", "Playback paused for 20 s twice"),
        ("failed", 0, [], "Recorder exited with code 2", "Recorder exited with code 2"),
        ("unavailable", 0, [], None, "The playlist can't be found any more"),
        ("partial", 0, [], None, "Ended partial"),
        ("failed", 0, [], None, "Failed"),
    ],
)
def test_the_issue_messages(
    state: str, failed: int, reasons: list[str], reason: str | None, message: str
) -> None:
    assert issue_message(state, failed, reasons, reason) == message


# --- The run list


async def seed_history(services: Services) -> dict[str, int]:
    """Five rows (three runs, two with no run) and a failed start-up run, oldest to newest."""

    def fn(conn: sqlite3.Connection) -> dict[str, int]:
        return {
            "old": seed_run(
                conn,
                trigger="scheduled",
                started_at=at(10, 1),
                ended_at=at(10, 2),
                counters=(3, 5, 0, 0, 100),
            ),
            "skipped": seed_run(
                conn,
                kind="skipped",
                trigger="scheduled",
                state=None,
                started_at=at(11, 1),
                reason="previous_paused",
            ),
            "missed": seed_run(
                conn,
                kind="missed",
                trigger="scheduled",
                state=None,
                started_at=at(12, 1),
                reason="not_running",
            ),
            "mid": seed_run(
                conn,
                trigger="run_now",
                outcome="completed_with_issues",
                started_at=at(13, 1),
                ended_at=at(13, 3),
                window=(at(13, 1), at(13, 7)),
                counters=(10, 0, 2, 1, 2000),
            ),
            "running": seed_run(
                conn,
                trigger="scheduled",
                state="running",
                outcome=None,
                started_at=at(14, 1),
            ),
        }

    return await seed(services, fn)


async def test_list_runs_pages_newest_first_with_no_run_rows(
    running_app: FastAPI, services: Services
) -> None:
    ids = await seed_history(services)
    first = await services.history.list_runs(limit=2)
    assert [row.id for row in first.runs] == [ids["running"], ids["mid"]]
    assert first.next_cursor is not None
    second = await services.history.list_runs(cursor=first.next_cursor, limit=2)
    assert [row.id for row in second.runs] == [ids["missed"], ids["skipped"]]
    third = await services.history.list_runs(cursor=second.next_cursor, limit=2)
    assert [row.id for row in third.runs] == [ids["old"]]
    assert third.next_cursor is None


async def test_rows_carry_counters_only_for_runs(running_app: FastAPI, services: Services) -> None:
    ids = await seed_history(services)
    rows = {row.id: row for row in (await services.history.list_runs(limit=100)).runs}
    assert rows[ids["missed"]].counters is None and rows[ids["missed"]].outcome is None
    assert rows[ids["missed"]].window is None and rows[ids["missed"]].duration_s is None
    assert rows[ids["running"]].counters is not None  # zeros while it's going
    assert rows[ids["running"]].duration_s is None and rows[ids["running"]].ended_at is None
    mid = rows[ids["mid"]]
    assert mid.duration_s == 7200  # 01:00 to 03:00
    assert mid.counters is not None and mid.counters.recorded == 10
    assert mid.counters.skipped_other == 2 and mid.counters.failed == 1
    assert mid.window is not None and mid.window.end.hour == 7
    old = rows[ids["old"]]
    assert old.counters is not None and old.counters.skipped_duplicate == 5


async def test_list_runs_filters(running_app: FastAPI, services: Services) -> None:
    ids = await seed_history(services)

    def add_failed(conn: sqlite3.Connection) -> int:
        return seed_run(
            conn,
            trigger="startup",
            state="ended",
            outcome="failed",
            started_at=at(9, 1),
            ended_at=at(9, 1),
            reason="container_restarted",
        )

    failed = await seed(services, add_failed)

    def ids_of(page: Any) -> set[int]:
        return {row.id for row in page.runs}

    with_issues = await services.history.list_runs(filter="with_issues", limit=100)
    # The partly done run, the failed run and every row with no run; not the clean completions.
    assert ids_of(with_issues) == {ids["mid"], failed, ids["missed"], ids["skipped"]}
    scheduled = await services.history.list_runs(filter="scheduled", limit=100)
    assert ids_of(scheduled) == {ids["running"], ids["old"], ids["missed"], ids["skipped"], failed}
    run_now = await services.history.list_runs(filter="run_now", limit=100)
    assert ids_of(run_now) == {ids["mid"]}


async def test_a_bad_cursor_is_422(running_app: FastAPI, services: Services) -> None:
    await seed_history(services)
    with pytest.raises(ApiError) as caught:
        await services.history.list_runs(cursor="%%%")
    assert caught.value.status == 422 and caught.value.details == {"field": "cursor"}


async def test_a_bad_cursor_over_http_is_the_error_envelope(
    running_app: FastAPI, services: Services, client: httpx.AsyncClient
) -> None:
    response = await client.get("/api/runs", params={"cursor": "%%%"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert_schema("Error", response.json())  # 422s are global, so the contract doesn't list them


async def test_list_runs_over_http_matches_the_contract(
    running_app: FastAPI, services: Services, client: httpx.AsyncClient
) -> None:
    await seed_history(services)
    response = await client.get("/api/runs", params={"limit": 2})
    assert response.status_code == 200
    assert_response(response, "/api/runs")
    assert response.json()["next_cursor"] is not None


# --- A run's page


async def seed_run_page(services: Services) -> dict[str, Any]:
    """A run with four items: two that ran (one partial after two stalls, one up to date that
    carried over in), one that never ran, and one removed while Up next, with failed takes."""

    def fn(conn: sqlite3.Connection) -> dict[str, Any]:
        seed_item(conn, PLAYLIST_A, name="Chill Mix", thumb_path="a.jpg", image_id="img1")
        seed_item(conn, ALBUM, kind="album", name="Album B", thumb_path="b.jpg", image_id="img2")
        seed_item(conn, PLAYLIST_C, name="Gone Soon")
        seed_item(conn, PLAYLIST_D, name="Removed", removed_at=at(2))
        run = seed_run(
            conn,
            trigger="scheduled",
            outcome="completed_with_issues",
            started_at=at(1, 1),
            ended_at=at(1, 5),
            window=(at(1, 1), at(1, 7)),
            counters=(3, 4, 0, 1, 1000),
        )
        ran_b = seed_run_item(
            conn,
            run,
            ALBUM,
            queue_pos=3,
            ran_order=1,
            state="up_to_date",
            carried_over_in=1,
            up_to_date_by="nothing_missing",
        )
        ran_a = seed_run_item(
            conn,
            run,
            PLAYLIST_A,
            queue_pos=1,
            ran_order=2,
            state="partial",
            failed=1,
            recorded=3,
            skipped=4,
            interrupted_count=2,
        )
        never_c = seed_run_item(conn, run, PLAYLIST_C, queue_pos=1, state="stopped")
        removed_d = seed_run_item(conn, run, PLAYLIST_D, queue_pos=2, state="removed", failed=2)
        return {
            "run": run,
            "a": ran_a,
            "b": ran_b,
            "c": never_c,
            "d": removed_d,
        }

    return await seed(services, fn)


async def test_a_run_page_lists_items_in_the_order_they_ran(
    running_app: FastAPI, services: Services
) -> None:
    ids = await seed_run_page(services)
    detail = await services.history.run(ids["run"])
    assert [item.item_id for item in detail.items] == [ALBUM, PLAYLIST_A, PLAYLIST_C, PLAYLIST_D]
    assert [item.order for item in detail.items] == [1, 2, 3, 4]
    assert detail.run.counters is not None and detail.run.counters.recorded == 3


async def test_run_page_badges_covers_and_retry(running_app: FastAPI, services: Services) -> None:
    ids = await seed_run_page(services)
    items = {item.item_id: item for item in (await services.history.run(ids["run"])).items}
    assert items[ALBUM].badges == ["up_to_date", "carried_over_in"]
    assert items[PLAYLIST_A].badges == ["interrupted_twice"]
    assert items[PLAYLIST_C].badges == ["stopped"]
    assert items[PLAYLIST_D].badges == ["removed"]
    assert items[ALBUM].cover == "/api/albums/" + ALBUM + "/cover?size=thumb&v=img2"
    assert items[PLAYLIST_A].cover == "/api/library/" + PLAYLIST_A + "/cover?size=thumb&v=img1"
    assert items[PLAYLIST_C].cover is None
    assert items[PLAYLIST_A].can_retry is True  # failed takes, still in the Library
    assert items[PLAYLIST_D].can_retry is False  # failed takes, but removed
    assert items[PLAYLIST_C].started_at is None and items[PLAYLIST_C].reason is None


async def test_a_run_page_over_http_matches_the_contract(
    running_app: FastAPI, services: Services, client: httpx.AsyncClient
) -> None:
    ids = await seed_run_page(services)
    response = await client.get(f"/api/runs/{ids['run']}")
    assert response.status_code == 200
    assert_response(response, "/api/runs/{id}")


async def test_a_run_that_is_not_there_is_404(
    running_app: FastAPI, services: Services, client: httpx.AsyncClient
) -> None:
    with pytest.raises(ApiError) as caught:
        await services.history.run(999)
    assert caught.value.status == 404 and caught.value.code == "not_found"
    response = await client.get("/api/runs/999")
    assert response.status_code == 404
    assert_response(response, "/api/runs/{id}")


async def test_a_no_run_row_is_a_run_page_with_no_items(
    running_app: FastAPI, services: Services
) -> None:
    ids = await seed_history(services)
    detail = await services.history.run(ids["missed"])
    assert detail.items == [] and detail.run.kind == "missed"


# --- An item's takes in one run


async def seed_takes(services: Services) -> dict[str, Any]:
    def fn(conn: sqlite3.Connection) -> dict[str, Any]:
        seed_item(conn, PLAYLIST_A, name="Chill Mix")
        run = seed_run(
            conn,
            trigger="run_now",
            outcome="completed_with_issues",
            started_at=at(1, 1),
            ended_at=at(1, 5),
        )
        run_item = seed_run_item(conn, run, PLAYLIST_A, queue_pos=1, ran_order=1, state="partial")
        track_one = seed_track(conn, 1, ["Artist One", "Feat Two"], "One")
        file_id = seed_file(conn, run, "Artist One/Album/01 - One.m4a", 5000)
        seed_take(
            conn,
            run_item,
            "take-1",
            artist="Artist One",
            title="One",
            started=at(1, 1),
            result="recorded",
            position=0,
            track=track_one,
            file_id=file_id,
        )
        seed_take(
            conn,
            run_item,
            "take-2",
            artist="Two",
            title="Two",
            started=at(1, 2),
            result="failed",
            reason="low_volume",
            position=1,
        )
        seed_take(
            conn,
            run_item,
            "take-3",
            artist="Three",
            title="Three",
            started=at(1, 3),
            result="skipped",
            reason="duplicate",
        )
        # A take still recording: it has no result, so it isn't listed.
        seed_take(
            conn, run_item, "take-4", artist="Four", title="Four", started=at(1, 4), result=None
        )
        return {"run": run}

    return await seed(services, fn)


async def test_run_item_tracks_are_one_row_per_take(
    running_app: FastAPI, services: Services
) -> None:
    ids = await seed_takes(services)
    tracks = (await services.history.run_item_tracks(ids["run"], PLAYLIST_A)).tracks
    assert [track.take_id for track in tracks] == ["take-1", "take-2", "take-3"]
    assert [track.position for track in tracks] == [1, 2, None]
    recorded, failed, skipped = tracks
    assert recorded.result == "recorded" and recorded.size_bytes == 5000
    assert recorded.path == "Artist One/Album/01 - One.m4a"
    assert recorded.track_id == track_id(1)
    assert recorded.artists == ["Artist One", "Feat Two"]  # from the matched track
    assert failed.result == "failed" and failed.reason == "low_volume"
    assert failed.artists == ["Two"] and failed.size_bytes is None and failed.path is None
    assert skipped.result == "skipped" and skipped.reason == "duplicate"


async def test_run_item_tracks_over_http_matches_the_contract(
    running_app: FastAPI, services: Services, client: httpx.AsyncClient
) -> None:
    ids = await seed_takes(services)
    response = await client.get(f"/api/runs/{ids['run']}/items/{PLAYLIST_A}/tracks")
    assert response.status_code == 200
    assert_response(response, "/api/runs/{id}/items/{item}/tracks")
    assert len(response.json()["tracks"]) == 3


async def test_run_item_tracks_404s(running_app: FastAPI, services: Services) -> None:
    ids = await seed_takes(services)
    with pytest.raises(ApiError) as no_run:
        await services.history.run_item_tracks(999, PLAYLIST_A)
    assert no_run.value.status == 404
    with pytest.raises(ApiError) as no_item:
        await services.history.run_item_tracks(ids["run"], NO_ITEM)
    assert no_item.value.status == 404 and no_item.value.code == "not_found"


# --- The Dashboard's Last run


async def test_last_run_is_null_before_the_first_run(
    running_app: FastAPI, services: Services, client: httpx.AsyncClient
) -> None:
    last = await services.history.last_run()
    assert last.run is None and last.issues == []
    response = await client.get("/api/runs/last")
    assert response.status_code == 200
    assert_response(response, "/api/runs/last")


async def test_last_run_and_its_three_issues(running_app: FastAPI, services: Services) -> None:
    def fn(conn: sqlite3.Connection) -> dict[str, int]:
        for item_id, name in (
            (PLAYLIST_Y, "Chill Mix"),
            (PLAYLIST_V, "Also"),
            (PLAYLIST_X, "Other"),
            (PLAYLIST_Z, "Lost"),
            (PLAYLIST_W, "Fine"),
        ):
            seed_item(conn, item_id, name=name)
        seed_run(conn, trigger="scheduled", started_at=at(1, 1), ended_at=at(1, 2))  # older
        last = seed_run(
            conn,
            trigger="scheduled",
            outcome="completed_with_issues",
            started_at=at(5, 1),
            ended_at=at(5, 2),
            counters=(9, 0, 0, 3, 0),
        )
        seed_run(conn, trigger="run_now", state="running", outcome=None, started_at=at(6, 1))
        y = seed_run_item(
            conn, last, PLAYLIST_Y, queue_pos=1, ran_order=1, state="partial", failed=2
        )
        seed_take(
            conn,
            y,
            "take-a",
            artist="A",
            title="a",
            started=at(5, 1),
            result="failed",
            reason="low_volume",
        )
        seed_take(
            conn,
            y,
            "take-b",
            artist="B",
            title="b",
            started=at(5, 1),
            result="failed",
            reason="low_volume",
        )
        v = seed_run_item(conn, last, PLAYLIST_V, queue_pos=2, ran_order=4, state="done", failed=1)
        seed_take(
            conn,
            v,
            "take-c",
            artist="C",
            title="c",
            started=at(5, 1),
            result="failed",
            reason="interrupted",
        )
        seed_run_item(
            conn,
            last,
            PLAYLIST_X,
            queue_pos=3,
            ran_order=2,
            state="partial",
            reason="Playback paused for 20 s twice",
        )
        seed_run_item(conn, last, PLAYLIST_Z, queue_pos=4, ran_order=3, state="unavailable")
        seed_run_item(conn, last, PLAYLIST_W, queue_pos=5, ran_order=5, state="done")
        return {"last": last}

    ids = await seed(services, fn)
    last = await services.history.last_run()
    assert last.run is not None and last.run.id == ids["last"]  # not the run still going
    assert last.run.counters is not None and last.run.counters.failed == 3
    assert [issue.item_id for issue in last.issues] == [PLAYLIST_Y, PLAYLIST_V, PLAYLIST_X]
    assert [issue.message for issue in last.issues] == [
        "2 tracks failed: low volume",
        "1 track failed: interrupted",
        "Playback paused for 20 s twice",
    ]
    assert last.issues[0].name == "Chill Mix"


# --- The HistoryRow shape


async def test_history_row_matches_the_contract(running_app: FastAPI, services: Services) -> None:
    ids = await seed_history(services)
    for name in ("mid", "missed", "running", "old"):
        row = await services.history.history_row(ids[name])
        assert isinstance(row, HistoryRow)
        assert_schema("HistoryRow", row.model_dump(mode="json"))


async def test_history_row_of_a_missing_run_is_a_lookup_error(
    running_app: FastAPI, services: Services
) -> None:
    with pytest.raises(LookupError):
        await services.history.history_row(12345)
