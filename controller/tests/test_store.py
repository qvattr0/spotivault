"""store/: the database file, WAL, the single worker thread, transactions and migrations."""

import sqlite3
import stat
import threading
from pathlib import Path

import pytest

from spotivault.store import Migration, MigrationError, Store, StoreUnavailable, load_migrations


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
async def store(tmp_path: Path):
    db = Store(tmp_path / "config" / "db" / "spotivault.db")
    await db.open()
    yield db
    await db.close()


async def test_open_creates_a_private_wal_database(store: Store) -> None:
    assert store.is_open
    assert mode(store.path) == 0o600
    assert mode(store.path.parent) == 0o700
    assert await store.fetchval("PRAGMA journal_mode") == "wal"
    assert await store.fetchval("PRAGMA foreign_keys") == 1
    assert await store.fetchval("PRAGMA busy_timeout") == 5000
    await store.execute(
        "INSERT INTO settings (key, value, updated_at) "
        "VALUES ('format', '\"aac\"', '2026-11-15T00:00:00.000Z')"
    )
    for suffix in ("-wal", "-shm"):
        side = store.path.with_name(store.path.name + suffix)
        assert side.exists()
        assert mode(side) == 0o600


async def test_every_migration_is_applied(store: Store) -> None:
    latest = load_migrations()[-1].version
    assert store.schema_version == latest
    assert await store.fetchval("SELECT value FROM meta WHERE key = 'schema_version'") == str(
        latest
    )
    steps = await store.fetchall("SELECT step, state FROM setup_steps ORDER BY ordinal")
    assert [row["step"] for row in steps][0] == "tos"
    assert len(steps) == 9
    assert await store.fetchval("SELECT count(*) FROM api_endpoints") == 15


async def test_reopening_doesnt_migrate_again(tmp_path: Path) -> None:
    path = tmp_path / "db" / "spotivault.db"
    first = Store(path)
    await first.open()
    await first.execute("UPDATE setup_steps SET state = 'done' WHERE step = 'tos'")
    await first.close()
    second = Store(path)
    await second.open()
    try:
        assert second.schema_version == load_migrations()[-1].version
        assert await second.fetchval("SELECT state FROM setup_steps WHERE step = 'tos'") == "done"
    finally:
        await second.close()


async def test_every_call_runs_on_one_worker_thread(store: Store) -> None:
    def thread_id(conn: sqlite3.Connection) -> int:
        return threading.get_ident()

    ids = {await store.call(thread_id) for _ in range(5)}
    ids.add(await store.transaction(thread_id))
    assert len(ids) == 1
    assert ids != {threading.get_ident()}


async def test_a_failed_transaction_is_rolled_back(store: Store) -> None:
    def write_then_fail(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO meta (key, value, updated_at) "
            "VALUES ('probe', 'x', '2026-11-15T00:00:00.000Z')"
        )
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await store.transaction(write_then_fail)
    assert await store.fetchval("SELECT count(*) FROM meta WHERE key = 'probe'") == 0


async def test_transaction_commits_and_returns(store: Store) -> None:
    def insert(conn: sqlite3.Connection) -> int:
        cur = conn.execute("INSERT INTO schedule_hours (day, hour) VALUES (0, 1)")
        conn.execute("INSERT INTO schedule_hours (day, hour) VALUES (0, 2)")
        return cur.rowcount

    assert await store.transaction(insert) == 1
    assert await store.fetchval("SELECT count(*) FROM schedule_hours") == 2
    result = await store.executemany(
        "INSERT INTO schedule_hours (day, hour) VALUES (?, ?)", [(1, 1), (1, 2)]
    )
    assert result.rowcount == 2


async def test_checks_from_the_schema_are_enforced(store: Store) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        await store.execute("INSERT INTO schedule_hours (day, hour) VALUES (7, 1)")


async def test_closed_store_refuses_calls(tmp_path: Path) -> None:
    db = Store(tmp_path / "db" / "x.db")
    with pytest.raises(StoreUnavailable):
        await db.fetchone("SELECT 1")
    assert await db.ping() is False
    await db.open()
    assert await db.ping() is True
    await db.close()
    with pytest.raises(StoreUnavailable):
        await db.execute("SELECT 1")
    await db.close()  # closing twice is fine


async def test_a_failed_migration_is_rolled_back_whole(tmp_path: Path) -> None:
    good = load_migrations()
    bad = Migration(
        version=len(good) + 1,
        name="broken",
        sql="CREATE TABLE half (x INTEGER);\nTHIS IS NOT SQL;",
    )
    db = Store(tmp_path / "db" / "x.db", migrations=[*good, bad])
    with pytest.raises(sqlite3.OperationalError):
        await db.open()
    assert db.is_open is False
    assert db.error is not None and "OperationalError" in db.error

    reopened = Store(tmp_path / "db" / "x.db")
    await reopened.open()
    try:
        assert reopened.schema_version == good[-1].version
        assert (
            await reopened.fetchval("SELECT count(*) FROM sqlite_master WHERE name = 'half'") == 0
        )
    finally:
        await reopened.close()


async def test_a_newer_database_is_refused(tmp_path: Path) -> None:
    db = Store(tmp_path / "db" / "x.db")
    await db.open()
    await db.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    await db.close()
    again = Store(tmp_path / "db" / "x.db")
    with pytest.raises(MigrationError, match="newer"):
        await again.open()


async def test_an_existing_file_is_made_private(tmp_path: Path) -> None:
    path = tmp_path / "db" / "x.db"
    path.parent.mkdir(mode=0o755)
    path.touch(mode=0o644)
    path.chmod(0o644)
    db = Store(path)
    await db.open()
    await db.close()
    assert mode(path) == 0o600
    assert mode(path.parent) == 0o700
