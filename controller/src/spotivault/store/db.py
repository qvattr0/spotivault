"""The SQLite database, behind one worker thread with an async API on top.

sqlite3 calls block, so they never run on the event loop (design.md § Stack). Every query, from
every module, goes through this one thread, in the order it was asked for. Code on the loop awaits
the result:

    row = await store.fetchone("SELECT value FROM settings WHERE key = ?", ("format",))

    def add_run(conn: sqlite3.Connection) -> int:
        cur = conn.execute("INSERT INTO runs (...) VALUES (...)", (...))
        conn.execute("UPDATE ...")
        return cur.lastrowid
    run_id = await store.transaction(add_run)

`transaction(fn)` runs a whole function on the thread inside BEGIN IMMEDIATE … COMMIT, rolled back
if it raises. Keep such functions plain and quick: they hold the only database thread.
"""

import asyncio
import os
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spotivault.store.migrate import Migration, load_migrations, migrate

type Params = Sequence[Any] | Mapping[str, Any]

# STRICT tables (contracts/schema.sql) need SQLite 3.37 or later. Ubuntu 24.04 has 3.45.
_MIN_SQLITE = (3, 37, 0)


class StoreUnavailable(RuntimeError):
    """The database isn't open: it failed to open at start-up, or it has been closed."""


@dataclass(frozen=True, slots=True)
class ExecResult:
    rowcount: int
    lastrowid: int | None


class Store:
    """The controller's SQLite database (contracts/schema.sql), in WAL mode, file mode 0600."""

    def __init__(self, path: Path, migrations: list[Migration] | None = None) -> None:
        self.path = path
        self._migrations = migrations
        self._executor: ThreadPoolExecutor | None = None
        self._conn: sqlite3.Connection | None = None  # touched only on the database thread
        self.error: str | None = None  # why the last open failed
        self.schema_version = 0

    @property
    def is_open(self) -> bool:
        return self._executor is not None

    async def open(self) -> None:
        """Creates the database if needed, applies the migrations and starts the thread.

        On failure it records `error` (GET /api/health then answers 503) and raises.
        """
        if self._executor is not None:
            return
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite")
        loop = asyncio.get_running_loop()
        try:
            self.schema_version = await loop.run_in_executor(executor, self._open_on_thread)
        except BaseException as exc:
            executor.shutdown(wait=False)
            self.error = f"{type(exc).__name__}: {exc}"
            raise
        self.error = None
        self._executor = executor

    async def close(self) -> None:
        """Closes the connection and stops the thread. Later calls raise StoreUnavailable."""
        executor = self._executor
        if executor is None:
            return
        self._executor = None
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(executor, self._close_on_thread)
        await asyncio.to_thread(executor.shutdown, True)

    async def call[T](self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Runs `fn(conn)` on the database thread and returns its result. No transaction is added:
        each statement commits on its own. Use `transaction` for several writes together."""
        executor = self._executor
        if executor is None:
            raise StoreUnavailable(self.error or "the database is closed")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, self._run_on_thread, fn)

    async def transaction[T](self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Runs `fn(conn)` on the database thread inside BEGIN IMMEDIATE … COMMIT.

        If `fn` raises, the transaction is rolled back and the exception re-raised here.
        """

        def wrapped(conn: sqlite3.Connection) -> T:
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = fn(conn)
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
            return result

        return await self.call(wrapped)

    async def execute(self, sql: str, params: Params = ()) -> ExecResult:
        """One statement, committed on its own."""

        def run(conn: sqlite3.Connection) -> ExecResult:
            cur = conn.execute(sql, params)
            return ExecResult(rowcount=cur.rowcount, lastrowid=cur.lastrowid)

        return await self.call(run)

    async def executemany(self, sql: str, rows: Sequence[Params]) -> ExecResult:
        """One statement for many rows, in one transaction."""

        def run(conn: sqlite3.Connection) -> ExecResult:
            cur = conn.executemany(sql, rows)
            return ExecResult(rowcount=cur.rowcount, lastrowid=cur.lastrowid)

        return await self.transaction(run)

    async def fetchone(self, sql: str, params: Params = ()) -> sqlite3.Row | None:
        return await self.call(lambda conn: conn.execute(sql, params).fetchone())

    async def fetchall(self, sql: str, params: Params = ()) -> list[sqlite3.Row]:
        return await self.call(lambda conn: conn.execute(sql, params).fetchall())

    async def fetchval(self, sql: str, params: Params = ()) -> Any:
        """The first column of the first row, or None when there's no row."""
        row = await self.fetchone(sql, params)
        return None if row is None else row[0]

    async def ping(self) -> bool:
        """True while the database answers a query. For GET /api/health."""
        try:
            return await self.fetchval("SELECT 1") == 1
        except (StoreUnavailable, sqlite3.Error):
            return False

    # --- On the database thread only -----------------------------------------------------------

    def _open_on_thread(self) -> int:
        if sqlite3.sqlite_version_info < _MIN_SQLITE:
            raise RuntimeError(
                f"SQLite {sqlite3.sqlite_version} is too old: 3.37 or later is needed"
            )
        # /config/db is private, and the file holds the Web API tokens: 0700 and 0600.
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        # autocommit=True: the sqlite3 module opens no transactions of its own; `transaction`
        # and the migrations say BEGIN and COMMIT themselves.
        conn = sqlite3.connect(self.path, autocommit=True, timeout=5.0)
        try:
            conn.row_factory = sqlite3.Row
            mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if mode != "wal":
                raise RuntimeError(f"can't switch the database to WAL mode (got {mode!r})")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            # SQLite gives -wal and -shm the main file's mode; fix any left from an older run.
            for suffix in ("-wal", "-shm"):
                side = self.path.with_name(self.path.name + suffix)
                if side.exists():
                    os.chmod(side, 0o600)
            migrations = self._migrations if self._migrations is not None else load_migrations()
            version = migrate(conn, migrations)
        except BaseException:
            conn.close()
            raise
        self._conn = conn
        return version

    def _close_on_thread(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _run_on_thread[T](self, fn: Callable[[sqlite3.Connection], T]) -> T:
        if self._conn is None:
            raise StoreUnavailable("the database is closed")
        return fn(self._conn)
