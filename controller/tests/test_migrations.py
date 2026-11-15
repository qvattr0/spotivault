"""Migration 001 is contracts/schema.sql, byte for byte, and the migration files are in order."""

import re
import sqlite3
from importlib import resources

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
        assert migrate(conn, load_migrations()) == 1
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()
    assert expected <= tables
    assert len(expected) >= 15
