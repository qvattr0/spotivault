"""Schema migrations: numbered SQL files in store/migrations, applied in order.

`001_initial.sql` is a byte-for-byte copy of contracts/schema.sql (a test checks it). A later
change is a new file, `002_<what>.sql`, which never edits an earlier one. The database's version
is the `schema_version` row in the `meta` table, which the runner updates after each migration.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources

from spotivault.clock import iso_ms

_FILE_NAME = re.compile(r"(\d{3})_([a-z0-9_]+)\.sql")


class MigrationError(RuntimeError):
    """The migrations can't be applied: a bad file list, or a database newer than the code."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations() -> list[Migration]:
    """Every `NNN_name.sql` shipped in spotivault/store/migrations, by version.

    Versions must run 1, 2, 3 … with no gap, so a missing or misnamed file is caught here.
    """
    folder = resources.files("spotivault.store") / "migrations"
    found = []
    for entry in folder.iterdir():
        match = _FILE_NAME.fullmatch(entry.name)
        if match:
            sql = entry.read_text(encoding="utf-8")
            found.append(Migration(version=int(match.group(1)), name=match.group(2), sql=sql))
    found.sort(key=lambda m: m.version)
    for expected, migration in enumerate(found, start=1):
        if migration.version != expected:
            raise MigrationError(
                f"migration {expected:03d} is missing (found {migration.version:03d})"
            )
    return found


def current_version(conn: sqlite3.Connection) -> int:
    """The database's schema version: 0 for a new database."""
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
    ).fetchone()
    if not has_meta:
        return 0
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row[0]) if row else 0


def migrate(conn: sqlite3.Connection, migrations: list[Migration]) -> int:
    """Applies every migration newer than the database, each in its own transaction.

    Runs on the database thread, with a connection in autocommit mode. A failed migration is
    rolled back whole and its error raised; the earlier ones stay applied. Returns the version.
    """
    version = current_version(conn)
    latest = migrations[-1].version if migrations else 0
    if version > latest:
        raise MigrationError(
            f"the database is at schema {version}, newer than this controller knows ({latest}): "
            "update the image"
        )
    for migration in migrations:
        if migration.version <= version:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            # With autocommit=True, executescript adds no COMMIT of its own: the script runs
            # inside the transaction above.
            conn.executescript(migration.sql)
            conn.execute(
                "INSERT INTO meta (key, value, updated_at) VALUES ('schema_version', ?, ?) "
                "ON CONFLICT (key) DO UPDATE SET "
                "value = excluded.value, updated_at = excluded.updated_at",
                (str(migration.version), iso_ms(datetime.now(UTC))),
            )
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        version = migration.version
    return version
