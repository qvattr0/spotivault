"""matching.py: Spytify's duplicate index (read_recorded_index), its cache, and what it says about
the library (item counts, recorded tracks, D13)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from spotivault.fake.clock import FakeClock
from spotivault.matching import RecordedIndex, go_lower, read_recorded_index, track_key
from spotivault.services import Services

ITEM = "a9poFNKiHX6sRmXWJ3e0mn"
OTHER = "3cEYpjA9oz9GiPac4AsH4n"
NOW = "2026-11-15T00:00:00.000Z"


def write_index(music_dir: Path, lines: list[str]) -> Path:
    path = music_dir / ".spytify" / "recorded.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def make_file(music_dir: Path, name: str) -> str:
    path = music_dir / name
    path.write_bytes(b"audio")
    return str(path)


# --- The reader -----------------------------------------------------------------------------------


def test_a_missing_index_is_empty(music_dir: Path) -> None:
    assert read_recorded_index(music_dir / ".spytify" / "recorded.jsonl") == {}


def test_only_entries_whose_file_exists_count(music_dir: Path) -> None:
    here = make_file(music_dir, "here.flac")
    gone = str(music_dir / "deleted.flac")
    write_index(
        music_dir,
        [
            json.dumps({"Key": "a\x1fone", "Path": here}),
            json.dumps({"Key": "b\x1ftwo", "Path": gone}),
        ],
    )
    assert read_recorded_index(music_dir / ".spytify" / "recorded.jsonl") == {"a\x1fone": here}


def test_later_lines_win_and_bad_lines_are_skipped(music_dir: Path) -> None:
    first = make_file(music_dir, "first.flac")
    second = make_file(music_dir, "second.flac")
    other = make_file(music_dir, "other.flac")
    lines = [
        json.dumps({"Key": "k\x1f1", "Path": first}),
        "this is not json",
        "[1, 2, 3]",  # a list, not an object
        "42",  # a number
        json.dumps({"Path": other}),  # no Key
        json.dumps({"Key": "k\x1f2"}),  # no Path
        json.dumps({"Key": 7, "Path": other}),  # a Key that isn't text
        json.dumps({"Key": "k\x1f3", "Path": 5}),  # a Path that isn't text
        json.dumps({"Key": "", "Path": other}),  # an empty Key
        json.dumps({"Key": ["k"], "Path": other}),  # unhashable Key
        "",  # a blank line
        json.dumps({"Key": "k\x1f1", "Path": second}),  # overrides the first line
        json.dumps({"Key": "k\x1f4", "Path": other}),
    ]
    path = write_index(music_dir, lines)
    missing = str(music_dir / "never-written.flac")
    path.write_bytes(
        path.read_bytes() + b'{"Key": "bad\xff\xfe", "Path": "' + missing.encode() + b'"}\n'
    )
    result = read_recorded_index(path)
    assert result == {"k\x1f1": second, "k\x1f4": other}


def test_a_key_is_the_track_key_of_its_artist_and_title(music_dir: Path) -> None:
    path = make_file(music_dir, "song.flac")
    key = track_key(" Pink Floyd", "Money ")
    assert key == "pink floyd\x1fmoney"
    write_index(music_dir, [json.dumps({"Key": key, "Path": path})])
    assert read_recorded_index(music_dir / ".spytify" / "recorded.jsonl") == {key: path}
    assert go_lower("MONEY") == "money"


# --- The service's cache --------------------------------------------------------------------------


@pytest.fixture
def counted_reads(services: Services, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Counts the reads of the index file (each one a thread's work). Forgets the read the start-up
    estimate made, so each test starts with no cached index."""
    import spotivault.matching as matching

    services.matching.invalidate()
    reads: list[int] = []
    real = matching.read_recorded_index

    def counting(path: Path) -> dict[str, str]:
        reads.append(1)
        return real(path)

    monkeypatch.setattr(matching, "read_recorded_index", counting)
    return reads


async def test_a_young_read_is_reused_until_invalidated(
    running_app: Any, services: Services, fake_clock: FakeClock, counted_reads: list[int]
) -> None:
    first = await services.matching.index()
    again = await services.matching.index()
    assert again is first and len(counted_reads) == 1
    await fake_clock.advance(2.5)  # past max_age_s
    await services.matching.index()
    assert len(counted_reads) == 2
    services.matching.invalidate()
    await services.matching.index()
    assert len(counted_reads) == 3


async def test_concurrent_callers_share_one_read(
    running_app: Any, services: Services, counted_reads: list[int]
) -> None:
    results = await asyncio.gather(*(services.matching.index() for _ in range(5)))
    assert len(counted_reads) == 1
    assert all(result is results[0] for result in results)


async def test_a_read_older_than_an_invalidate_is_not_cached(
    running_app: Any, services: Services, counted_reads: list[int]
) -> None:
    pending = asyncio.create_task(services.matching.index())
    await asyncio.sleep(0)  # the read has started
    services.matching.invalidate()
    await pending
    await services.matching.index()  # not the old read's answer: a new one
    assert len(counted_reads) == 2


async def test_the_index_is_read_with_the_records_of_the_file(
    running_app: Any, services: Services, music_dir: Path
) -> None:
    path = make_file(music_dir, "one.flac")
    write_index(music_dir, [json.dumps({"Key": "x\x1fy", "Path": path})])
    services.matching.invalidate()  # the start-up estimate read the index before the file existed
    index = await services.matching.index()
    assert isinstance(index, RecordedIndex)
    assert index.has("x\x1fy") and index.path("x\x1fy") == path
    assert not index.has("x\x1fz") and index.path("x\x1fz") is None


# --- What the index says about the library ---------------------------------------------------


def seed_item(
    conn: Any,
    item_id: str,
    *,
    kind: str = "owned",
    item_access: int = 1,
    catalog_fetched_at: str | None = NOW,
    last_backup_at: str | None = None,
    snapshot_id: str | None = None,
    last_full_pass_snapshot: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO items (id, kind, uri, name, added_by, added_at, tracked, item_access, "
        "catalog_fetched_at, last_backup_at, snapshot_id, last_full_pass_snapshot, "
        "last_full_pass_at) VALUES (?, ?, ?, 'Mix', 'user', ?, 1, ?, ?, ?, ?, ?, ?)",
        (
            item_id,
            kind,
            f"spotify:playlist:{item_id}",
            NOW,
            item_access,
            catalog_fetched_at,
            last_backup_at,
            snapshot_id,
            last_full_pass_snapshot,
            NOW if last_full_pass_snapshot else None,
        ),
    )


def seed_track(conn: Any, track_id: str, artist: str, title: str) -> None:
    conn.execute(
        "INSERT INTO tracks (id, uri, name, artists, duration_ms, spytify_key, fetched_at) "
        "VALUES (?, ?, ?, ?, 180000, ?, ?)",
        (
            track_id,
            f"spotify:track:{track_id}",
            title,
            json.dumps([artist]),
            track_key(artist, title),
            NOW,
        ),
    )


def seed_entry(conn: Any, item_id: str, position: int, track_id: str | None, added_at: str | None):
    conn.execute(
        "INSERT INTO item_tracks (item_id, position, track_id, playable, unplayable_reason, "
        "added_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            item_id,
            position,
            track_id,
            1 if track_id else 0,
            None if track_id else "local",
            added_at,
        ),
    )


async def test_item_counts_split_recorded_and_new(
    running_app: Any, services: Services, music_dir: Path
) -> None:
    store = services.store
    recorded = make_file(music_dir, "rec.flac")
    write_index(music_dir, [json.dumps({"Key": track_key("A", "Done"), "Path": recorded})])
    services.matching.invalidate()
    tracks = [("tr00000000000000000001", "A", "Done"), ("tr00000000000000000002", "B", "Todo")]

    def seed(conn: Any) -> None:
        for track_id, artist, title in tracks:
            seed_track(conn, track_id, artist, title)
        seed_item(conn, ITEM, last_backup_at="2026-11-10T00:00:00.000Z")
        seed_entry(conn, ITEM, 0, tracks[0][0], "2026-11-01T00:00:00.000Z")
        seed_entry(conn, ITEM, 1, tracks[1][0], "2026-11-12T00:00:00.000Z")  # after the backup
        seed_entry(conn, ITEM, 2, None, None)  # local: not playable, not counted
        seed_item(conn, OTHER, catalog_fetched_at=None)  # never fetched: left out

    await store.transaction(seed)
    counts = await services.matching.item_counts()
    assert set(counts) == {ITEM}
    assert (counts[ITEM].total, counts[ITEM].recorded, counts[ITEM].new) == (2, 1, 1)
    only = await services.matching.item_counts([ITEM, OTHER])
    assert set(only) == {ITEM}


async def test_a_never_backed_up_item_is_all_new(running_app: Any, services: Services) -> None:
    def seed(conn: Any) -> None:
        seed_track(conn, "tr00000000000000000003", "C", "Never")
        seed_item(conn, ITEM)
        seed_entry(conn, ITEM, 0, "tr00000000000000000003", "2026-11-01T00:00:00.000Z")

    await services.store.transaction(seed)
    counts = await services.matching.item_counts([ITEM])
    assert (counts[ITEM].total, counts[ITEM].recorded, counts[ITEM].new) == (1, 0, 1)


async def test_recorded_track_ids_follow_the_index(
    running_app: Any, services: Services, music_dir: Path
) -> None:
    path = make_file(music_dir, "x.flac")
    write_index(music_dir, [json.dumps({"Key": track_key("D", "Yes"), "Path": path})])
    services.matching.invalidate()

    def seed(conn: Any) -> None:
        seed_track(conn, "tr00000000000000000004", "D", "Yes")
        seed_track(conn, "tr00000000000000000005", "D", "No")

    await services.store.transaction(seed)
    assert await services.matching.recorded_track_ids() == frozenset({"tr00000000000000000004"})


async def test_d13_needs_a_clean_pass_that_still_matches(
    running_app: Any, services: Services, music_dir: Path
) -> None:
    path = make_file(music_dir, "y.flac")
    write_index(music_dir, [json.dumps({"Key": "e\x1fseen", "Path": path})])
    services.matching.invalidate()
    matching = services.matching

    def seed(conn: Any) -> None:
        seed_item(conn, ITEM, item_access=0, snapshot_id="s2", last_full_pass_snapshot="s2")
        seed_item(conn, OTHER, item_access=0, snapshot_id="s3", last_full_pass_snapshot="s2")
        conn.execute(
            "INSERT INTO runs (kind, trigger, state, outcome, started_at, ended_at) "
            "VALUES ('run', 'run_now', 'ended', 'completed', ?, ?)",
            (NOW, NOW),
        )
        run_id = conn.execute("SELECT max(id) FROM runs").fetchone()[0]
        for item_id in (ITEM, OTHER):
            conn.execute(
                "INSERT INTO observed_tracks "
                "(item_id, ordinal, spytify_key, artist, title, run_id) "
                "VALUES (?, 1, 'e\x1fseen', 'e', 'seen', ?)",
                (item_id, run_id),
            )

    await services.store.transaction(seed)
    assert await matching.d13_up_to_date(ITEM) is True
    assert await matching.observed_all_in_index(ITEM) is True
    assert await matching.d13_up_to_date(OTHER) is False  # the playlist changed since the pass

    # A deleted file forces a full pass: the observed track is no longer in the index.
    (music_dir / "y.flac").unlink()
    matching.invalidate()
    assert await matching.d13_up_to_date(ITEM) is False


async def test_d13_without_observed_tracks_is_not_up_to_date(
    running_app: Any, services: Services
) -> None:
    await services.store.transaction(
        lambda conn: seed_item(
            conn, ITEM, item_access=0, snapshot_id="s1", last_full_pass_snapshot="s1"
        )
    )
    assert await services.matching.observed_all_in_index(ITEM) is False
    assert await services.matching.d13_up_to_date(ITEM) is False
    assert await services.matching.d13_up_to_date("missing-item-id-000001") is False
