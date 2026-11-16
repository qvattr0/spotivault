"""Migration 003 (S6): run item timings and reasons, the skip split, items' .m3u, the loop lag."""

import json
import sqlite3

import pytest

from spotivault.store import load_migrations
from spotivault.store.migrate import migrate

NOW = "2026-11-15T00:00:00.000Z"
ALBUM = "4glBZ0bZMgkmFyi6TD4h69"


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn, load_migrations())
    conn.execute(
        "INSERT INTO items (id, kind, uri, name, artist, total, added_by, added_at) "
        "VALUES (?, 'album', ?, 'Elsewhere', 'fakename', 5, 'user', ?)",
        (ALBUM, f"spotify:album:{ALBUM}", NOW),
    )
    conn.execute(
        "INSERT INTO runs (id, kind, trigger, state, started_at, recorded, skipped_duplicate, "
        "skipped_other, failed, bytes_added) VALUES (1, 'run', 'run_now', 'running', ?, 0, 0, 0, "
        "0, 0)",
        (NOW,),
    )
    return conn


def test_it_is_migration_3(conn: sqlite3.Connection) -> None:
    assert [m.name for m in load_migrations()][:3] == ["initial", "s5_catalog", "s6_runs"]
    version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    assert int(version) >= 3


def test_run_items_take_timings_reasons_and_the_skip_split(conn: sqlite3.Connection) -> None:
    timings = {"started_at": NOW, "phase_s": {"planning": 0.4}, "planned_ms": 1000}
    conn.execute(
        "INSERT INTO run_items (run_id, item_id, queue_pos, state, timings, interrupted_by, "
        "error_code, skipped, skipped_other) VALUES (1, ?, 1, 'interrupted', ?, 'takeover', "
        "'recorder_exit', 3, 1)",
        (ALBUM, json.dumps(timings)),
    )
    row = conn.execute("SELECT * FROM run_items").fetchone()
    assert json.loads(row["timings"]) == timings
    assert (row["interrupted_by"], row["skipped"], row["skipped_other"]) == ("takeover", 3, 1)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE run_items SET interrupted_by = 'boredom'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE run_items SET timings = 'not json'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE run_items SET skipped_other = -1")


def test_run_metrics_take_the_loop_lag(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO run_metrics (run_id, at, loop_lag_max_ms) VALUES (1, ?, 12)", (NOW,))
    assert conn.execute("SELECT loop_lag_max_ms FROM run_metrics").fetchone()[0] == 12
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE run_metrics SET loop_lag_max_ms = -5")


def test_items_remember_their_m3u(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE items SET m3u_path = 'Playlists/Elsewhere.m3u'")
    assert conn.execute("SELECT m3u_path FROM items").fetchone()[0] == "Playlists/Elsewhere.m3u"


def test_runs_have_a_window_index(conn: sqlite3.Connection) -> None:
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "runs_window" in names
