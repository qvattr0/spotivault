"""catalog/tracks.py: storing a track list, with the entries that can't be recorded marked."""

import json
import sqlite3
from dataclasses import replace

import pytest

from spotivault.catalog.tracks import ListedTrack, replace_item_tracks, unplayable_reason
from spotivault.fake.catalog import make_track
from spotivault.matching import track_key
from spotivault.ports import Track
from spotivault.store import load_migrations
from spotivault.store.migrate import migrate

NOW = "2026-11-15T00:00:00.000Z"
ITEM = "a9poFNKiHX6sRmXWJ3e0mn"

PLAYABLE = make_track(" Passage ", artist=("fakename", "Other"), duration_ms=87_000)
UNPLAYABLE = make_track("Gone", is_playable=False, duration_ms=10_000)
UNKNOWN = make_track("Unsaid", is_playable=None, duration_ms=1_000)
LOCAL = Track(
    id=None,
    uri="spotify:local:Some+Band:Home+Demos:Garage+Take:201",
    name="Garage Take",
    artists=("Some Band",),
    album_id=None,
    album_name="Home Demos",
    track_number=None,
    disc_number=None,
    duration_ms=201_000,
    is_local=True,
    is_playable=None,
    is_episode=False,
)
EPISODE = replace(make_track("Episode 12"), is_episode=True, uri="spotify:episode:x")


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn, load_migrations())
    conn.execute(
        "INSERT INTO items (id, kind, uri, name, added_by, added_at) "
        "VALUES (?, 'owned', ?, 'Mix', 'auto', ?)",
        (ITEM, f"spotify:playlist:{ITEM}", NOW),
    )
    return conn


def test_why_an_entry_cant_be_recorded() -> None:
    assert unplayable_reason(PLAYABLE) is None
    assert unplayable_reason(UNKNOWN) is None  # the answer didn't say: playable
    assert unplayable_reason(UNPLAYABLE) == "not_playable"
    assert unplayable_reason(LOCAL) == "local"
    assert unplayable_reason(EPISODE) == "episode"
    assert unplayable_reason(None) == "no_item"
    assert unplayable_reason(replace(PLAYABLE, id=None)) == "no_item"


def test_a_list_is_stored_in_order_with_keys(conn: sqlite3.Connection) -> None:
    entries = [
        ListedTrack(PLAYABLE, "2026-01-01T00:00:00Z"),
        ListedTrack(UNPLAYABLE),
        ListedTrack(LOCAL),
        ListedTrack(EPISODE),
        ListedTrack(None),
        ListedTrack(UNKNOWN),
        ListedTrack(PLAYABLE),  # the same track twice
    ]
    summary = replace_item_tracks(conn, ITEM, entries, NOW)
    assert (summary.entries, summary.playable, summary.playable_ms) == (7, 3, 175_000)
    rows = conn.execute(
        "SELECT position, track_id, playable, unplayable_reason, added_at FROM item_tracks "
        "WHERE item_id = ? ORDER BY position",
        (ITEM,),
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (0, PLAYABLE.id, 1, None, "2026-01-01T00:00:00Z"),
        (1, UNPLAYABLE.id, 0, "not_playable", None),
        (2, None, 0, "local", None),
        (3, EPISODE.id, 0, "episode", None),
        (4, None, 0, "no_item", None),
        (5, UNKNOWN.id, 1, None, None),
        (6, PLAYABLE.id, 1, None, None),
    ]
    track = conn.execute("SELECT * FROM tracks WHERE id = ?", (PLAYABLE.id,)).fetchone()
    assert track["spytify_key"] == track_key("fakename", " Passage ") == "fakename\x1fpassage"
    assert json.loads(track["artists"]) == ["fakename", "Other"]
    assert track["duration_ms"] == 87_000 and track["fetched_at"] == NOW


def test_storing_again_replaces_the_list_and_updates_tracks(conn: sqlite3.Connection) -> None:
    replace_item_tracks(conn, ITEM, [ListedTrack(PLAYABLE), ListedTrack(UNPLAYABLE)], NOW)
    renamed = replace(PLAYABLE, name="Passage (Remastered)")
    summary = replace_item_tracks(conn, ITEM, [ListedTrack(renamed)], "2026-11-16T00:00:00.000Z")
    assert summary.entries == 1
    assert conn.execute("SELECT count(*) FROM item_tracks").fetchone()[0] == 1
    name = conn.execute("SELECT name FROM tracks WHERE id = ?", (PLAYABLE.id,)).fetchone()[0]
    assert name == "Passage (Remastered)"


def test_an_empty_list(conn: sqlite3.Connection) -> None:
    replace_item_tracks(conn, ITEM, [ListedTrack(PLAYABLE)], NOW)
    summary = replace_item_tracks(conn, ITEM, [], NOW)
    assert (summary.entries, summary.playable, summary.playable_ms) == (0, 0, 0)
    assert conn.execute("SELECT count(*) FROM item_tracks").fetchone()[0] == 0
