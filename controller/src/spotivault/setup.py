"""The setup wizard's state: steps 1 to 9 (web-ui.md § Setup wizard).

Each step's state is stored in the `setup_steps` table, so a reload or a restart resumes at the
first unfinished step. A step is `done` in one of two ways:

| Step | Done when |
|---|---|
| 1 `tos` | The Terms notice is acknowledged (POST /api/setup/tos). |
| 2 `client` | Check: `services.client.status()` says installed; `failed` if the last install did. |
| 3 `login` | Check: `services.client.status()` says logged in (Q2's rule, in client/status.py). |
| 4 `client_settings` | Check: `services.client.checklist()` is `ready`. |
| 5 `webapi` | S5 calls `mark_done("webapi")` once the token works and our device is listed. |
| 6 `output` | Check: GET /api/storage's `ok`. `failed`, with the reason, while it isn't. |
| 7 `playlists` | The step 7 choice is saved: a PUT /api/settings with `auto_track_owned`. |
| 8 `albums` | S5 calls `mark_done("albums")` after POST /api/albums. |
| 9 `done` | `complete()`, which also sets `completed`. |

**Done is sticky:** a live check only ever turns a step done, and only "Run setup again"
(`restart()`) turns steps 2 to 9 back to `todo`; they then turn done again from the live checks,
as schema.sql describes. So once setup is complete, a client that logs out doesn't send the UI
back to the wizard: the Dashboard shows that instead.

**When the checks run:** on GET /api/setup, GET /api/storage, every action here, `refresh()`, and
whenever the client module says its status or checklist changed (its `add_listener`). A
`setup.state` event follows any change. The WS hello shows the stored state without running checks.
"""

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, cast

from spotivault.api.models import Checklist, ClientStatus, Setup, SetupStep, Storage
from spotivault.clock import iso_ms
from spotivault.errors import ApiError, run_active
from spotivault.storage import storage_problem

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

type StepId = Literal[
    "tos",
    "client",
    "login",
    "client_settings",
    "webapi",
    "output",
    "playlists",
    "albums",
    "done",
]
type StepState = Literal["todo", "active", "done", "failed"]

STEPS: tuple[StepId, ...] = (
    "tos",
    "client",
    "login",
    "client_settings",
    "webapi",
    "output",
    "playlists",
    "albums",
    "done",
)
# Steps a live check turns done, in the order they're checked.
CHECKED_STEPS: tuple[StepId, ...] = ("client", "login", "client_settings", "output")
# Steps marked done by another module with mark_done().
MARKED_STEPS: tuple[StepId, ...] = ("webapi", "playlists", "albums")
# Steps 1 to 6 have no safe default: nothing can be recorded without them. Steps 7 and 8 are
# choices with defaults, so complete() accepts them as they are.
REQUIRED_STEPS: tuple[StepId, ...] = STEPS[:6]

_TOS_KEY = "tos_acknowledged_at"
_COMPLETED_KEY = "setup_completed_at"


class ClientModule(Protocol):
    """What steps 2 to 4 need from the client module, `services.client` (client/manager.py)."""

    async def status(self) -> ClientStatus:
        """The client's status as last polled: installed, the last install, logged in."""
        ...

    async def checklist(self) -> Checklist:
        """Step 4's checklist, read now; `ready` when every blocker row is OK or ticked."""
        ...

    def add_listener(self, fn: Callable[[], Awaitable[None]]) -> None:
        """`fn()` is awaited after the client's status or checklist changes."""
        ...


@dataclass(frozen=True, slots=True)
class StepCheck:
    """A live check's answer: done, failed with a reason, or neither yet."""

    done: bool
    failure: str | None = None


PASSED = StepCheck(done=True)
NOT_YET = StepCheck(done=False)


@dataclass(frozen=True, slots=True)
class _Stored:
    """What the database holds: each step's state and message, and the two setup times."""

    rows: dict[str, tuple[str, str | None]]
    tos_at: str | None
    completed_at: str | None


class SetupService:
    """The wizard's state. Built by services.py as `services.setup`."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        self._lock = asyncio.Lock()  # one evaluation at a time, so each change is published once
        self._check_errors: dict[str, str] = {}
        self._client_changed = asyncio.Event()
        services.bus.add_snapshot("setup", self.snapshot)
        services.settings.add_listener(self._settings_saved)
        services.add_startup("setup", self.start)
        services.add_background("setup.follow", self.follow_client)

    async def start(self) -> None:
        # services.client is built after this module, so it's reached here, at start-up.
        self._client().add_listener(self._on_client_change)

    async def follow_client(self) -> None:
        """Refreshes the steps after the client module reports a change.

        The client's listener only sets an event: refresh() calls back into the client module
        (checklist()), which may notify its listeners again, so refreshing inside the listener
        would wait on its own lock.
        """
        while True:
            await self._client_changed.wait()
            self._client_changed.clear()
            try:
                await self.refresh()
            except Exception:
                log.exception("setup: can't refresh the steps after a client change")

    async def _on_client_change(self) -> None:
        self._client_changed.set()

    # --- Reading ------------------------------------------------------------------------------

    async def refresh(self, *, storage: Storage | None = None) -> Setup:
        """Runs the live checks, saves what changed, publishes `setup.state` if anything did, and
        returns the state (GET /api/setup). Call it when a fact behind a step changes: the client
        installed or logged in, a checklist row ticked, the connection made.

        `storage` is a storage check just made, so step 6 doesn't probe /music again.
        """
        async with self._lock:
            return await self._refresh(storage)

    async def snapshot(self) -> Setup:
        """The WS hello's `setup`: the stored state, without running any check. Never raises."""
        try:
            return _compose(await self._load(), {})
        except Exception:
            log.exception("setup: can't read the wizard's state for the hello")
            return _compose(_Stored(rows={}, tos_at=None, completed_at=None), {})

    async def is_complete(self) -> bool:
        """Setup is done: the UI leaves the wizard, and runs may start (else `setup_incomplete`)."""
        return (await self._load()).completed_at is not None

    # --- Actions ------------------------------------------------------------------------------

    async def acknowledge_tos(self) -> Setup:
        """Step 1: stores the acknowledgement with its time. Again later, it keeps the first."""
        now = iso_ms(self.services.clock.now())
        await self.services.store.execute(
            "INSERT INTO meta (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (key) DO NOTHING",
            (_TOS_KEY, now, now),
        )
        return await self.refresh()

    async def restart(self) -> Setup:
        """Settings › About › "Run setup again": steps 2 to 9 back to `todo`, and `completed`
        false. Nothing else is deleted. Refused with 409 `run_active` during a run.

        The answer shows the steps as just reset, so the wizard reopens at step 2. The live checks
        run right after, with their own `setup.state`, and turn steps 2, 3, 4 and 6 done again
        when their facts still hold: nothing else would run them (the UI follows the socket, and
        the hello doesn't check), and the wizard can't walk past a step that isn't done.
        """
        if await self._run_is_active():
            raise run_active()
        now = iso_ms(self.services.clock.now())

        def reset(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE setup_steps SET state = 'todo', message = NULL, updated_at = ? "
                "WHERE step <> 'tos'",
                (now,),
            )
            conn.execute("DELETE FROM meta WHERE key = ?", (_COMPLETED_KEY,))

        async with self._lock:
            before = await self._load()
            await self.services.store.transaction(reset)
            after = await self._load()
            setup = _compose(after, {})
            await self._save(setup, after)
            if _compose(before, {}) != setup:
                self._publish(setup)
            await self._refresh(None)
        log.info("setup: run again from step 2")
        return setup

    async def mark_done(self, step: StepId) -> Setup:
        """Marks a step done that no live check covers: `webapi` (S5, once the token works and our
        device is listed), `playlists` (the step 7 choice) and `albums` (S5, after the step 8
        choice). A no-op once setup is complete."""
        if step not in MARKED_STEPS:
            raise ValueError(f"step {step!r} isn't marked by hand; see setup.py")
        async with self._lock:
            return await self._refresh(None, marks={step: ("done", None)})

    async def mark_failed(self, step: StepId, message: str) -> Setup:
        """Shows a step marked by hand as failed, with why (S5's step 5: "our device isn't
        listed"). A step already done stays done; mark_done() clears a failure."""
        if step not in MARKED_STEPS:
            raise ValueError(f"step {step!r} isn't marked by hand; see setup.py")
        async with self._lock:
            return await self._refresh(None, marks={step: ("failed", message)})

    async def complete(self) -> Setup:
        """Finishes the wizard (step 9): steps 7 to 9 done and `completed` true.

        Refused with 409 `setup_incomplete`, listing the steps, while a step from 1 to 6 isn't
        done (POST /api/setup/complete).
        """
        async with self._lock:
            setup = await self._refresh(None)
            missing = [s.id for s in setup.steps if s.id in REQUIRED_STEPS and s.state != "done"]
            if missing:
                raise ApiError(
                    409,
                    "setup_incomplete",
                    "Finish the setup steps first: " + ", ".join(missing) + ".",
                    {"steps": missing},
                )
            now = iso_ms(self.services.clock.now())

            def finish(conn: sqlite3.Connection) -> None:
                conn.execute(
                    "INSERT INTO meta (key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
                    "updated_at = excluded.updated_at",
                    (_COMPLETED_KEY, now, now),
                )

            await self.services.store.transaction(finish)
            result = await self._refresh(None)
        log.info("setup: complete")
        return result

    # --- The checks ---------------------------------------------------------------------------

    async def _refresh(
        self,
        storage: Storage | None,
        *,
        marks: dict[StepId, tuple[StepState, str | None]] | None = None,
    ) -> Setup:
        """refresh() inside the lock. `marks` set steps by hand first; a step done stays done."""
        stored = await self._load()
        view = stored
        if marks:
            rows = dict(stored.rows)
            for step, row in marks.items():
                if rows.get(step, ("todo", None))[0] != "done":
                    rows[step] = row
            view = _Stored(rows=rows, tos_at=stored.tos_at, completed_at=stored.completed_at)
        checks: dict[StepId, StepCheck] = {}
        if view.completed_at is None:
            pending = [s for s in CHECKED_STEPS if view.rows.get(s, ("todo", None))[0] != "done"]
            checks = await self._run_checks(pending, storage)
        setup = _compose(view, checks)
        if await self._save(setup, stored):
            self._publish(setup)
        return setup

    async def _run_checks(
        self, pending: list[StepId], storage: Storage | None
    ) -> dict[StepId, StepCheck]:
        """The live checks of the steps in `pending`. A check that can't run is left out, so its
        step keeps its state."""
        results: dict[StepId, StepCheck] = {}
        client = self._client()
        if "client" in pending or "login" in pending:
            status = await self._attempt("client status", lambda: client.status())
            if status is not None:
                if "client" in pending:
                    results["client"] = _client_check(status)
                if "login" in pending:
                    results["login"] = PASSED if status.logged_in else NOT_YET
        if "client_settings" in pending:
            checklist = await self._attempt("client checklist", lambda: client.checklist())
            if checklist is not None:
                results["client_settings"] = PASSED if checklist.ready else NOT_YET
        if "output" in pending:
            if storage is None:
                storage = await self._attempt("storage", self.services.storage.check)
            if storage is not None:
                problem = storage_problem(storage)
                results["output"] = PASSED if storage.ok else StepCheck(False, problem)
        return results

    async def _attempt[T](self, what: str, read: Callable[[], Awaitable[T]]) -> T | None:
        """`await read()`, or None when it fails. Each new failure is logged once."""
        try:
            value = await read()
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"
            if self._check_errors.get(what) != text:
                log.warning("setup: can't read the %s: %s", what, text)
                self._check_errors[what] = text
            return None
        self._check_errors.pop(what, None)
        return value

    def _client(self) -> ClientModule:
        return cast(ClientModule, self.services.client)

    async def _settings_saved(self, keys: frozenset[str]) -> None:
        """Step 7's choice is the `auto_track_owned` setting (web-ui.md § 7)."""
        if "auto_track_owned" in keys:
            await self.mark_done("playlists")

    # --- The database -------------------------------------------------------------------------

    async def _load(self) -> _Stored:
        def load(conn: sqlite3.Connection) -> _Stored:
            rows = {
                row["step"]: (row["state"], row["message"])
                for row in conn.execute("SELECT step, state, message FROM setup_steps")
            }
            meta = {
                row["key"]: row["value"]
                for row in conn.execute(
                    "SELECT key, value FROM meta WHERE key IN (?, ?)", (_TOS_KEY, _COMPLETED_KEY)
                )
            }
            return _Stored(
                rows=rows, tos_at=meta.get(_TOS_KEY), completed_at=meta.get(_COMPLETED_KEY)
            )

        return await self.services.store.call(load)

    async def _save(self, setup: Setup, stored: _Stored) -> bool:
        """Writes the steps whose state or message changed. True when any did."""
        now = iso_ms(self.services.clock.now())
        changed = [
            (step.id, STEPS.index(step.id) + 1, step.state, step.message, now)
            for step in setup.steps
            if stored.rows.get(step.id) != (step.state, step.message)
        ]
        if not changed:
            return False

        def write(conn: sqlite3.Connection) -> None:
            conn.executemany(
                "INSERT INTO setup_steps (step, ordinal, state, message, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (step) DO UPDATE SET state = excluded.state, "
                "message = excluded.message, updated_at = excluded.updated_at",
                changed,
            )

        await self.services.store.transaction(write)
        return True

    async def _run_is_active(self) -> bool:
        """A run is going: the runs table has one that hasn't ended (schema.sql runs_one_active)."""
        row = await self.services.store.fetchone(
            "SELECT 1 FROM runs WHERE kind = 'run' AND state <> 'ended' LIMIT 1"
        )
        return row is not None

    def _publish(self, setup: Setup) -> None:
        self.services.bus.publish("setup.state", setup)


def _client_check(status: ClientStatus) -> StepCheck:
    """Step 2: installed, or failed when the last install failed (web-ui.md step 2)."""
    if status.installed:
        return PASSED
    if status.install.state == "failed":
        error = status.install.error
        return StepCheck(False, error.message if error else "The Spotify client install failed.")
    return NOT_YET


def _compose(stored: _Stored, checks: dict[StepId, StepCheck]) -> Setup:
    """The API's Setup from the stored rows and this round's live checks.

    Done is sticky; a check turns a step done, or failed with a reason, or clears an old failure.
    The first step that isn't done is `first_unfinished`, shown `active` unless it failed.
    """
    done: set[StepId] = set()
    failed: dict[StepId, str] = {}
    for step in STEPS:
        state, message = stored.rows.get(step, ("todo", None))
        if state == "done":
            done.add(step)
        elif state == "failed":
            failed[step] = message or "This step failed."
    if stored.tos_at is not None:
        done.add("tos")
    if stored.completed_at is not None:
        done.update(STEPS)
    for step, check in checks.items():
        if step in done:
            continue
        if check.done:
            done.add(step)
            failed.pop(step, None)
        elif check.failure is not None:
            failed[step] = check.failure
        else:
            failed.pop(step, None)

    first = next((step for step in STEPS if step not in done), None)
    steps = []
    for step in STEPS:
        if step in done:
            steps.append(SetupStep(id=step, state="done", message=None))
        elif step in failed:
            steps.append(SetupStep(id=step, state="failed", message=failed[step]))
        else:
            steps.append(SetupStep(id=step, state="active" if step == first else "todo"))
    return Setup(
        steps=steps,
        first_unfinished=first,
        completed=stored.completed_at is not None,
        tos_acknowledged_at=stored.tos_at,
    )
