"""Migration 002 (S5): the followed playlists, the usage-log warnings, the full-size cover."""

import sqlite3

import pytest

from spotivault.store import load_migrations
from spotivault.store.migrate import migrate

NOW = "2026-11-15T00:00:00.000Z"
PLAYLIST_ID = "a9poFNKiHX6sRmXWJ3e0mn"


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn, load_migrations())
    return conn


def test_it_is_migration_2_and_bumps_the_version(conn: sqlite3.Connection) -> None:
    names = [m.name for m in load_migrations()]
    assert names[:2] == ["initial", "s5_catalog"]
    version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    assert int(version) >= 2


def test_followed_playlists_holds_a_listing_row(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO followed_playlists (id, uri, name, owner_id, owner_name, collaborative, "
        "total, snapshot_id, listed_order, seen_at) VALUES (?, ?, 'Mix', 'user7', 'Someone', 0, "
        "35, 'snap', 0, ?)",
        (PLAYLIST_ID, f"spotify:playlist:{PLAYLIST_ID}", NOW),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO followed_playlists (id, uri, name, collaborative, listed_order, seen_at) "
            "VALUES ('short', 'x', 'y', 0, 0, ?)",
            (NOW,),
        )


def test_api_warnings_takes_only_the_four_kinds(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO api_warnings (at, kind, message, endpoint_id) VALUES (?, 'rate_limited', "
        "'Web API: 429 on GET /me/tracks, Retry-After 30 s', 6)",
        (NOW,),
    )
    for kind in ("burst", "repeated_4xx", "above_median"):
        conn.execute("INSERT INTO api_warnings (at, kind, message) VALUES (?, ?, 'm')", (NOW, kind))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO api_warnings (at, kind, message) VALUES (?, 'other', 'm')", (NOW,)
        )


def test_items_has_a_full_path_next_to_the_thumbnail(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(items)")}
    assert {"thumb_path", "full_path", "image_id", "cover_source"} <= columns
