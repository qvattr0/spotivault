"""The client manager: everything the controller knows about the Spotify client.

`services.client` (web-ui.md steps 2–4, Settings › Spotify client, the Player). Routers and other
modules call these; nothing else talks to the client's ports for status, installs or restarts:

| Call | For |
|---|---|
| `await status()` | GET /api/client/status, the `client` hello, the Player, setup steps 2–3 |
| `installing` | GET /api/health's `installing` |
| `await start_install()` | POST /api/client/install (202 at once; 409 if one runs, or a run) |
| `await restart()` | POST /api/client/restart (202 at once; 409 during a run) |
| `await checklist()` | GET /api/client/checklist (it's also Re-check), setup step 4 |
| `await confirm(ticks)` | POST /api/setup/checklist/confirm |
| `await drifted_rows()` | the run engine's pre-run check (S6): Auto rows that aren't OK |
| `await set_run_active(active)` | the run engine (S6), when a run starts and ends |
| `add_listener(fn)` | the setup module: `fn()` is awaited after the status or checklist changes |

**Status** is polled every 3 s, and at once after an install or a restart: the installed
version, the process, the MPRIS name and the login signals. A `client.status` event goes out when
it changes (events.md): the client starts or stops, is installed, logs in or out, a run starts or
ends, or an install starts or ends. **Login** (Q2, resolved in S0) is `status.is_logged_in`: a
`Users/*-user/` folder and a window title other than "Spotify"; MPRIS isn't a signal.
`login_signals` reports all three readings, the MPRIS name included, for the UI's diagnostics.

**Installs** run one at a time in the background. Each attempt is a row in `client_install`, and
its progress goes out as `client.install` events: each phase change, each new log line, and
download progress at most twice a second. On the first start, a missing client is installed
(design.md § The Spotify client), in real mode. At shutdown a running install is stopped and
recorded as failed.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from spotivault.api.models import (
    Checklist,
    ChecklistRow,
    ClientInstall,
    ClientStatus,
    ClientStatusLoginSignals,
)
from spotivault.client.checklist import (
    ROWS_BY_ID,
    build_checklist,
    drifted,
    load_confirmed,
    save_confirmed,
    save_readings,
    seed_rows,
)
from spotivault.client.install import (
    InstallTracker,
    fail_interrupted,
    insert_attempt,
    installed_outside,
    load_latest,
    not_started,
    save_finished,
    save_phase,
)
from spotivault.client.status import is_logged_in
from spotivault.errors import ApiError, run_active, validation_failed
from spotivault.ports import InstallInProgress, LoginSignals

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

STATUS_POLL_S = 3.0
PROGRESS_INTERVAL_S = 0.5  # download progress events at most twice a second

type ClientListener = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Observed:
    """One reading of the client's signals."""

    version: str | None
    running: bool
    mpris: bool
    user_folder: bool
    window_title: str | None


class ClientManager:
    """The client's state. Built by services.py as `services.client`."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        self.config = services.config
        self.clock = services.clock
        self._install: ClientInstall = not_started()
        self._installing = False  # set as soon as an install is asked for
        self._install_task: asyncio.Task[None] | None = None
        self._restart_task: asyncio.Task[None] | None = None
        self._observed: Observed | None = None
        self._last_sent: ClientStatus | None = None  # the status the last client.status carried
        self._ready: bool | None = None  # the last checklist reading's `ready`
        self._run_active = False
        self._group: asyncio.TaskGroup | None = None  # set while `run` runs
        self._poke = asyncio.Event()  # wakes the status poll early
        self._refreshing = asyncio.Lock()  # one reading at a time, so they can't cross
        self._listeners: list[ClientListener] = []
        self._problems: dict[str, str] = {}  # signal → the last failure logged for it

        services.bus.add_snapshot("client", self.status)
        services.add_startup("client", self.start)
        services.add_background("client", self.run)
        services.add_shutdown("client", self.stop)

    # --- Status --------------------------------------------------------------------------------

    async def status(self) -> ClientStatus:
        """The client's status as last polled (read now if it hasn't been yet). Never raises."""
        if self._observed is None:
            self._observed = await self._observe()
        return self._build(self._observed)

    @property
    def installing(self) -> bool:
        return self._installing

    async def refresh(self) -> ClientStatus:
        """Reads the client's signals now, and publishes `client.status` if it changed."""
        async with self._refreshing:
            self._observed = await self._observe()
            status = self._build(self._observed)
            changed = self._publish_if_changed(status)
        if changed:
            await self._notify()  # outside the lock: a listener may read the status again
        return status

    async def set_run_active(self, active: bool) -> None:
        """The run engine calls this when a run starts (True) and ends (False). During a run,
        install and restart are refused, and `restartable` is false."""
        self._run_active = active
        if self._publish_if_changed(await self.status()):
            await self._notify()

    def add_listener(self, fn: ClientListener) -> None:
        """`fn()` is awaited after a `client.status` change, a confirm, and a checklist reading
        whose `ready` changed (the first reading since start-up counts). Errors it raises are
        logged."""
        self._listeners.append(fn)

    # --- Install -------------------------------------------------------------------------------

    async def start_install(self) -> ClientInstall:
        """Starts an install in the background; returns its state at once (POST, 202)."""
        if self._run_active:
            raise run_active()
        if self._installing:
            raise ApiError(409, "install_in_progress", "The client install is already running.")
        await self._begin_install()
        return self._install

    # --- Restart -------------------------------------------------------------------------------

    async def restart(self) -> ClientStatus:
        """Restarts the client in the background (MPRIS Quit; s6 starts it again). Returns the
        current status at once; `client.status` events follow (POST, 202)."""
        if self._run_active:
            raise run_active()
        if self._restart_task is None or self._restart_task.done():
            group = self._running_group()
            self._restart_task = group.create_task(self._restart_job(), name="client.restart")
        return await self.status()

    # --- Checklist -----------------------------------------------------------------------------

    async def checklist(self) -> Checklist:
        """Step 4's checklist, with every Auto row read again from the prefs file."""
        prefs = await self._safely("prefs", self.services.ports.client.prefs(), None)
        confirmed = await load_confirmed(self.services.store)
        result = build_checklist(prefs, confirmed, self._now())
        await save_readings(self.services.store, result)
        # The first reading since start-up counts as a change: `ready` may have changed while
        # the controller was down, and the setup module must hear of it.
        changed = result.ready != self._ready
        self._ready = result.ready
        if changed:
            await self._notify()
        return result

    async def confirm(self, ticks: Mapping[str, bool]) -> Checklist:
        """Ticks (True) or unticks (False) Confirm rows. Any other row is refused with 422
        `validation_failed`, and then nothing is changed."""
        for row_id in ticks:
            spec = ROWS_BY_ID.get(row_id)
            if spec is None or spec.check != "confirm":
                kind = spec.check if spec is not None else "unknown"
                raise validation_failed(
                    f"rows.{row_id}",
                    f"rows.{row_id}: only Confirm rows can be ticked, and this one is {kind}.",
                )
        if ticks:
            await save_confirmed(self.services.store, ticks, self._now())
        result = await self.checklist()
        await self._notify()
        return result

    async def drifted_rows(self) -> list[ChecklistRow]:
        """The Auto rows that aren't OK right now. The run engine refuses to start a run while
        there are any (web-ui.md step 4, "After setup")."""
        return drifted(await self.checklist())

    # --- Lifecycle -----------------------------------------------------------------------------

    async def start(self) -> None:
        """Start-up: the checklist rows, interrupted installs, the last install, a first reading."""
        store = self.services.store
        await seed_rows(store)
        stale = await fail_interrupted(store, self._now())
        if stale:
            log.warning("client: %d install(s) were interrupted by a restart; marked failed", stale)
        self._observed = await self._observe()
        latest = await load_latest(store)
        if latest is not None:
            self._install = latest
        elif self._observed.version is not None:
            self._install = installed_outside(self._observed.version)
        status = self._build(self._observed)
        self._last_sent = status
        log.info(
            "client: %s, %s, %s",
            f"version {status.version}" if status.installed else "not installed",
            "running" if status.running else "not running",
            "logged in" if status.logged_in else "not logged in",
        )

    async def run(self) -> None:
        """The background task: installs a missing client, then polls the status until shutdown.
        Installs and restarts run as tasks in its TaskGroup.

        In fake mode nothing is installed by itself: the fake world starts as the fake agent sets
        it up, and POST /api/client/install runs the simulated install. That keeps fake mode's
        events in the tests' control."""
        try:
            async with asyncio.TaskGroup() as group:
                self._group = group
                missing = self._observed is not None and self._observed.version is None
                if missing and not self.config.fake:
                    log.info("client: not installed; installing it (first start)")
                    await self._begin_install()
                await self._watch()
        finally:
            self._group = None

    async def stop(self) -> None:
        """Shutdown: stops a running install (killing spotify-install) and a restart."""
        for task in (self._install_task, self._restart_task):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.wait({task})

    # --- Inside: status --------------------------------------------------------------------------

    async def _watch(self) -> None:
        while True:
            self._poke.clear()
            await self.refresh()
            await self._sleep_or_poke(STATUS_POLL_S)

    async def _sleep_or_poke(self, seconds: float) -> None:
        """Waits `seconds` on the clock, or until something pokes the poll."""
        sleeping = asyncio.ensure_future(self.clock.sleep(seconds))
        poked = asyncio.ensure_future(self._poke.wait())
        try:
            await asyncio.wait({sleeping, poked}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleeping.cancel()
            poked.cancel()
            await asyncio.wait({sleeping, poked})

    async def _observe(self) -> Observed:
        client = self.services.ports.client
        version = await self._safely("version", client.installed_version(), None)
        running = await self._safely("process", client.is_running(), False)
        mpris = await self._safely("mpris", self.services.ports.mpris.owner_present(), False)
        signals = await self._safely(
            "login", client.login_signals(), LoginSignals(user_folder=False, window_title=None)
        )
        return Observed(
            version=version,
            running=running,
            mpris=mpris,
            user_folder=signals.user_folder,
            window_title=signals.window_title,
        )

    def _build(self, observed: Observed) -> ClientStatus:
        signals = LoginSignals(user_folder=observed.user_folder, window_title=observed.window_title)
        return ClientStatus(
            installed=observed.version is not None,
            version=observed.version,
            running=observed.running,
            logged_in=is_logged_in(signals),
            login_signals=ClientStatusLoginSignals(
                mpris=observed.mpris,
                user_folder=observed.user_folder,
                window_title=observed.window_title,
            ),
            device_name=self.config.device_name,
            restartable=not self._run_active,
            install=self._install,
        )

    @staticmethod
    def _same(a: ClientStatus, b: ClientStatus) -> bool:
        """Equal but for install progress, which `client.install` events carry instead, and the
        window title alone, which changes with every track while logged in."""
        if a.install.state != b.install.state:
            return False
        exclude = {"install": True, "login_signals": {"window_title"}}
        return a.model_dump(exclude=exclude) == b.model_dump(exclude=exclude)

    def _publish_if_changed(self, status: ClientStatus) -> bool:
        """Publishes `client.status` if it differs from the last one sent. True if it did."""
        last = self._last_sent
        if last is not None and self._same(last, status):
            return False
        self._last_sent = status
        if last is not None and last.running != status.running:
            log.info("client: %s", "running" if status.running else "stopped")
        if last is not None and last.logged_in != status.logged_in:
            log.info("client: %s", "logged in" if status.logged_in else "logged out")
        self.services.bus.publish("client.status", status)
        return True

    async def _notify(self) -> None:
        for fn in list(self._listeners):
            try:
                await fn()
            except Exception:
                log.exception("client: a listener failed")

    async def _safely[T](self, name: str, reading: Awaitable[T], fallback: T) -> T:
        """Awaits one port reading. If it fails, logs it (once per new failure) and returns
        `fallback`, so one broken signal doesn't stop the others."""
        try:
            value = await reading
        except Exception as exc:
            problem = f"{type(exc).__name__}: {exc}"
            if self._problems.get(name) != problem:
                self._problems[name] = problem
                log.warning("client: reading %s failed: %s", name, problem)
            return fallback
        self._problems.pop(name, None)
        return value

    # --- Inside: install -------------------------------------------------------------------------

    async def _begin_install(self) -> None:
        """Records a new attempt, publishes it and starts it in the background."""
        group = self._running_group()
        self._installing = True
        try:
            started = self._now()
            attempt_id = await insert_attempt(self.services.store, started)
        except BaseException:
            self._installing = False
            raise
        tracker = InstallTracker(started)
        self._install = tracker.snapshot()
        log.info("client: install started (attempt %d)", attempt_id)
        self._publish_install(None)
        if self._publish_if_changed(await self.status()):
            await self._notify()
        self._install_task = group.create_task(
            self._install_job(attempt_id, tracker), name="client.install"
        )

    async def _install_job(self, attempt_id: int, tracker: InstallTracker) -> None:
        last_line: str | None = None  # the log line of the attempt's last update
        last_publish = float("-inf")
        try:
            async with contextlib.aclosing(self.services.ports.client.install()) as lines:
                async for line in lines:
                    if tracker.finished:
                        continue  # read to the end all the same: the script then exits by itself
                    update = tracker.apply(line, self._now())
                    if update.finished:
                        # Not shown yet: _finish_install shows the result once its row is saved.
                        last_line = update.log_line
                        continue
                    self._install = tracker.snapshot()
                    if update.phase_changed or update.log_line or self._due(last_publish):
                        if update.phase_changed:
                            await save_phase(self.services.store, attempt_id, tracker.phase)
                        last_publish = self.clock.monotonic()
                        self._publish_install(update.log_line)
        except InstallInProgress as exc:
            last_line = tracker.fail(
                "unknown", f"{exc}: an install started outside the controller.", self._now()
            )
        except asyncio.CancelledError:
            last_line = tracker.fail(
                "unknown", "The install was stopped: the controller shut down.", self._now()
            )
            await self._finish_install(attempt_id, tracker, last_line)
            raise
        except Exception as exc:
            log.exception("client: the install failed unexpectedly")
            last_line = tracker.fail("unknown", f"The install failed: {exc}", self._now())
        if not tracker.finished:
            last_line = tracker.fail(
                "unknown", "spotify-install stopped without a result.", self._now()
            )
        await self._finish_install(attempt_id, tracker, last_line)

    def _due(self, last_publish: float) -> bool:
        return self.clock.monotonic() - last_publish >= PROGRESS_INTERVAL_S

    async def _finish_install(
        self, attempt_id: int, tracker: InstallTracker, log_line: str | None
    ) -> None:
        """Saves the attempt's result, and only then shows it: in the status (which the poll may
        publish at any moment), in `installing`, and as the last `client.install` event. Until
        then, GET /api/client/status and GET /api/health both still say `installing`."""
        try:
            await save_finished(self.services.store, attempt_id, tracker)
        except Exception:
            log.exception("client: the install's result couldn't be saved")
        finally:
            self._install = tracker.snapshot()
            self._installing = False
        if tracker.state == "installed":
            log.info("client: installed Spotify %s (attempt %d)", tracker.version, attempt_id)
        else:
            error = tracker.error
            log.warning(
                "client: install attempt %d failed (%s): %s",
                attempt_id,
                error.code if error else "unknown",
                error.message if error else "",
            )
        self._publish_install(log_line)
        self._poke.set()  # the status poll reads the new version and publishes client.status

    def _publish_install(self, log_line: str | None) -> None:
        data = self._install.model_dump(mode="json")
        data["log_line"] = log_line
        self.services.bus.publish("client.install", data)

    # --- Inside: restart and helpers -------------------------------------------------------------

    async def _restart_job(self) -> None:
        log.info("client: restarting the Spotify client")
        try:
            await self.services.ports.client.restart()
        except Exception:
            log.exception("client: the restart failed")
        self._poke.set()

    def _running_group(self) -> asyncio.TaskGroup:
        if self._group is None:
            raise ApiError(503, "internal", "The controller is still starting.")
        return self._group

    def _now(self) -> datetime:
        """The time, to the millisecond (as the database and events keep it)."""
        now = self.clock.now()
        return now.replace(microsecond=now.microsecond // 1000 * 1000)
