"""Migration 001 is contracts/schema.sql, byte for byte, and the migration files are in order."""

import re
import sqlite3
from importlib import resources

import pytest

from contract import CONTRACTS
from spotivault.store import load_migrations
from spotivault.store.migrate import migrate


def test_migration_001_is_the_contract_schema() -> None:
    shipped = resources.files("spotivault.store") / "migrations" / "001_initial.sql"
    assert shipped.read_bytes() == (CONTRACTS / "schema.sql").read_bytes(), (
        "store/migrations/001_initial.sql must stay identical to contracts/schema.sql: "
        "copy the contract over it (or, once released, add a 002 migration instead)"
    )


def test_migrations_are_numbered_from_1_without_gaps() -> None:
    migrations = load_migrations()
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].name == "initial"


def test_every_table_in_the_schema_is_created() -> None:
    schema = (CONTRACTS / "schema.sql").read_text(encoding="utf-8")
    expected = set(re.findall(r"^CREATE TABLE (\w+)", schema, flags=re.MULTILINE))
    conn = sqlite3.connect(":memory:", autocommit=True)
    try:
        migrations = load_migrations()
        assert migrate(conn, migrations) == migrations[-1].version
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()
    assert expected <= tables
    assert len(expected) >= 15


def test_migration_004_allows_manual_refreshes_and_keeps_the_rows() -> None:
    """The Refresh button's trigger. The table is rebuilt, with foreign keys on as the store has
    them, and its rows and the followed playlists that refer to them stay."""
    conn = sqlite3.connect(":memory:", autocommit=True)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        migrations = load_migrations()
        assert migrate(conn, migrations[:3]) == 3
        conn.execute(
            "INSERT INTO catalog_refreshes (trigger, started_at, outcome, items_changed) "
            "VALUES ('setup', '2026-11-15T09:00:00.000Z', 'ok', 2)"
        )
        conn.execute(
            "INSERT INTO followed_playlists (id, uri, name, collaborative, listed_order, "
            "refresh_id, seen_at) VALUES ('a9poFNKiHX6sRmXWJ3e0mn', "
            "'spotify:playlist:a9poFNKiHX6sRmXWJ3e0mn', 'Playlist 1', 0, 0, 1, "
            "'2026-11-15T09:00:01.000Z')"
        )

        assert migrate(conn, migrations) == migrations[-1].version

        refreshes = conn.execute(
            "SELECT id, trigger, outcome, items_changed FROM catalog_refreshes"
        ).fetchall()
        assert refreshes == [(1, "setup", "ok", 2)]
        followed = conn.execute("SELECT id, refresh_id FROM followed_playlists").fetchall()
        assert followed == [("a9poFNKiHX6sRmXWJ3e0mn", 1)]
        conn.execute(
            "INSERT INTO catalog_refreshes (trigger, started_at) "
            "VALUES ('manual', '2026-11-15T09:30:00.000Z')"
        )
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        index = conn.execute(
            "SELECT tbl_name FROM sqlite_master WHERE name = 'catalog_refreshes_started'"
        ).fetchone()
        assert index == ("catalog_refreshes",)
        with pytest.raises(sqlite3.IntegrityError):  # the foreign key still holds
            conn.execute(
                "INSERT INTO followed_playlists (id, uri, name, collaborative, listed_order, "
                "refresh_id, seen_at) VALUES ('b9poFNKiHX6sRmXWJ3e0mn', 'u', 'n', 0, 1, 99, 'x')"
            )
        with pytest.raises(sqlite3.IntegrityError):  # and the check, for other triggers
            conn.execute(
                "INSERT INTO catalog_refreshes (trigger, started_at) VALUES ('other', 'x')"
            )
    finally:
        conn.close()
