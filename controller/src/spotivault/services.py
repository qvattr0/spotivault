"""Everything the controller is made of, built once at start-up and handed to the routers.

    config = load_config()
    services = build_services(config)       # real or fake ports, by config.fake
    app = create_app(services)              # routers reach it through api.deps.ServicesDep

`Services` holds the config, the ports (`services.ports.mpris` and so on), the store, the event bus
and one object per feature module (`services.settings`, `services.client`, …). A feature module
takes the Services object in its constructor and registers what it needs there:

    services.bus.add_snapshot("client", self.status)      # its part of the WS hello
    services.add_startup("client", self.start)            # awaited once, after the store opens
    services.add_background("client.watch", self.watch)   # runs until shutdown, in a TaskGroup
    services.add_shutdown("client", self.stop)            # awaited at shutdown, newest first

`running()` is the app's lifespan. No task is ever lost (design.md § Stack): every background task
runs in one TaskGroup, and one that fails is logged with its traceback and stops the controller
(`on_fatal`; `python -m spotivault` then exits non-zero and s6 restarts it).
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from spotivault import __version__
from spotivault.api.models import ClientInstall, ClientStatus, Connection, Setup, SetupStep, Status
from spotivault.backlog import BacklogService
from spotivault.catalog.albums import AlbumsService
from spotivault.catalog.covers import CoverService
from spotivault.catalog.library import LibraryService
from spotivault.catalog.refresh import CatalogService
from spotivault.client.control import LocalClientControl
from spotivault.client.manager import ClientManager
from spotivault.client.mpris import JeepneyMpris
from spotivault.clock import SystemClock
from spotivault.config import Config
from spotivault.connection import ConnectionService
from spotivault.container import ContainerService
from spotivault.desktop import LocalDesktop
from spotivault.events import EventBus
from spotivault.fake import build_fake_ports
from spotivault.fake.clock import ScaledClock
from spotivault.fake.seed import attach as attach_fake_world
from spotivault.imagecdn import HttpImageCdn
from spotivault.loopwatch import LoopWatch
from spotivault.matching import MatchingService
from spotivault.ports import Clock, Ports
from spotivault.settings import SettingsService
from spotivault.setup import SetupService
from spotivault.storage import LocalStorageProbe, StorageService
from spotivault.store import Store
from spotivault.unbuilt import UnbuiltRecorder
from spotivault.webapi.auth_store import AuthStore
from spotivault.webapi.client import SpotifyWebApi
from spotivault.webapi.usage import UsageService

log = logging.getLogger(__name__)

type HookFn = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Hook:
    name: str
    fn: HookFn


class Services:
    """The controller's parts. One per process; tests build their own with fake ports."""

    def __init__(
        self,
        config: Config,
        ports: Ports,
        *,
        store: Store | None = None,
        auth: AuthStore | None = None,
    ) -> None:
        """`store` and `auth` are the ones the real Web API port was built with (build_services
        makes them first); by default, new ones."""
        self.config = config
        self.ports = ports
        self.clock = ports.clock
        self.started_monotonic = ports.clock.monotonic()  # for Health.uptime_s
        self.store = store if store is not None else Store(config.db_path)
        # The Web API connection as stored (spotify_auth): shared by the real port, the fake one
        # in fake mode, and the connection module.
        self.auth = auth if auth is not None else AuthStore(self.store, ports.clock)
        self.bus = EventBus(ports.clock, version=__version__)
        self.loopwatch = LoopWatch()
        self.fatal_errors: list[BaseException] = []
        self.on_fatal: Callable[[BaseException], None] | None = None
        self._startup: list[Hook] = []
        self._shutdown: list[Hook] = []
        self._background: list[Hook] = []

        _add_placeholder_snapshots(self.bus, config)
        self.add_background("loopwatch", self.loopwatch.run)
        if config.fake:
            attach_fake_world(self)  # the fake Web API follows `auth`; the demo starts connected

        # Feature modules, in dependency order. Each may replace a placeholder snapshot above.
        self.settings = SettingsService(self)
        self.storage = StorageService(self)
        self.container = ContainerService(self)
        self.setup = SetupService(self)
        self.client = ClientManager(self)
        # S5's modules (ARCHITECTURE.md § What the built modules offer). Each constructor registers
        # its hooks, snapshots and listeners.
        self.webapi_usage = UsageService(self)  # webapi-core
        self.matching = MatchingService(self)  # matching-backlog
        self.covers = CoverService(self)  # albums-covers
        self.connection = ConnectionService(self)  # spotify-connect: hello `connection`
        self.catalog = CatalogService(self)  # catalog-library
        self.library = LibraryService(self)  # catalog-library
        self.albums = AlbumsService(self)  # albums-covers
        self.backlog = BacklogService(self)  # matching-backlog: hello `backlog`

    def add_startup(self, name: str, fn: HookFn) -> None:
        """`fn` is awaited once at start-up, after the store opens, in the order added. If it
        raises, start-up fails and the controller exits."""
        self._startup.append(Hook(name, fn))

    def add_shutdown(self, name: str, fn: HookFn) -> None:
        """`fn` is awaited at shutdown, before background tasks are cancelled, newest first.
        Errors are logged, and the other hooks still run."""
        self._shutdown.append(Hook(name, fn))

    def add_background(self, name: str, fn: HookFn) -> None:
        """`fn` runs as a task from start-up until shutdown, when it's cancelled. If it raises,
        the error is logged and the controller stops (`on_fatal`)."""
        self._background.append(Hook(name, fn))

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        """Opens the store, runs the start-up hooks and the background tasks; closes it all on
        exit. If the database can't be opened, it still serves (GET /api/health answers 503),
        but no hook or background task runs.

        At shutdown, in order: the shutdown hooks (newest first), the background tasks are
        cancelled and awaited, then the ports' HTTP clients close (a catalog refresh still going
        never meets a closed client), and the store last."""
        try:
            await self.store.open()
        except Exception:
            log.exception(
                "the database at %s can't be opened: GET /api/health answers 503, "
                "and no start-up hook or background task runs",
                self.store.path,
            )
        started = self.store.is_open
        try:
            if started:
                for hook in self._startup:
                    log.debug("start-up: %s", hook.name)
                    await hook.fn()
            async with asyncio.TaskGroup() as group:
                tasks = []
                if started:
                    tasks = [
                        group.create_task(self._supervise(hook), name=hook.name)
                        for hook in self._background
                    ]
                try:
                    yield
                finally:
                    if started:
                        await self._run_shutdown_hooks()
                    for task in tasks:
                        task.cancel()
            # Leaving the TaskGroup awaited every background task: none uses a port any more.
        finally:
            await self._close_http_ports()
            await self.store.close()

    async def _close_http_ports(self) -> None:
        """Closes the Web API's and the image CDN's HTTP clients. A failure is logged."""
        for name, close in (("webapi", self.ports.webapi.aclose), ("cdn", self.ports.cdn.aclose)):
            try:
                await close()
            except Exception:
                log.exception("closing the %s port's HTTP client failed", name)

    async def _supervise(self, hook: Hook) -> None:
        try:
            await hook.fn()
        except Exception as exc:
            log.exception("background task %r failed; stopping the controller", hook.name)
            self.fatal_errors.append(exc)
            if self.on_fatal is not None:
                self.on_fatal(exc)

    async def _run_shutdown_hooks(self) -> None:
        for hook in reversed(self._shutdown):
            try:
                await hook.fn()
            except Exception:
                log.exception("shutdown hook %r failed", hook.name)


def build_services(config: Config, *, clock: Clock | None = None) -> Services:
    """Services with real ports, or fake ones when `config.fake`. `clock` overrides the clock
    (tests pass a FakeClock). By default it's the system clock; in fake mode with
    SPOTIVAULT_FAKE_SPEED set, a clock that runs that many times faster."""
    if clock is None:
        if config.fake and config.fake_speed != 1:
            clock = ScaledClock(config.fake_speed)
        else:
            clock = SystemClock()
    # The store and the stored connection come first: the real Web API port needs both.
    store = Store(config.db_path)
    auth = AuthStore(store, clock)
    if config.fake:
        ports = build_fake_ports(config, clock, scenario=config.fake_scenario)
    else:
        ports = build_real_ports(config, clock, store=store, auth=auth)
    return Services(config, ports, store=store, auth=auth)


def build_real_ports(
    config: Config,
    clock: Clock,
    *,
    store: Store | None = None,
    auth: AuthStore | None = None,
) -> Ports:
    """The real outside world. The recorder (S6) is a stand-in until built. The Web API port
    shares `store` and `auth` with the Services built from these ports (build_services passes
    them); by default, new ones, which tests/test_ports.py's signature checks are fine with."""
    store = store if store is not None else Store(config.db_path)
    auth = auth if auth is not None else AuthStore(store, clock)
    mpris = JeepneyMpris(config)
    return Ports(
        clock=clock,
        mpris=mpris,
        client=LocalClientControl(config, mpris),
        recorder=UnbuiltRecorder(),
        webapi=SpotifyWebApi(config, clock, store, auth),
        storage=LocalStorageProbe(),
        desktop=LocalDesktop(config),
        cdn=HttpImageCdn(),
    )


def _add_placeholder_snapshots(bus: EventBus, config: Config) -> None:
    """Contract-valid "nothing known yet" values for every hello key, so hello works before every
    module is built. The module that owns a key replaces its placeholder:
    setup → SetupService, client → ClientManager, connection → ConnectionService (S5,
    spotify-connect), backlog → BacklogService (S5, matching-backlog), status → S6."""

    async def setup() -> Setup:
        steps = [
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
        return Setup(
            steps=[
                SetupStep(id=step, state="active" if step == "tos" else "todo") for step in steps
            ],
            first_unfinished="tos",
            completed=False,
            tos_acknowledged_at=None,
        )

    async def status() -> Status:
        return Status(
            state="idle", run=None, item=None, track=None, session_state=None, view_only=False
        )

    async def connection() -> Connection:
        return Connection(
            state="not_configured",
            display_name=None,
            user_id=None,
            client_id_masked=None,
            authorized_at=None,
            expires_at=None,
            scopes=[],
        )

    async def client() -> ClientStatus:
        return ClientStatus(
            installed=False,
            version=None,
            running=False,
            logged_in=False,
            login_signals={"mpris": False, "user_folder": False, "window_title": None},
            device_name=config.device_name,
            restartable=True,
            install=ClientInstall(
                state="not_started",
                phase=None,
                progress=None,
                bytes_done=None,
                bytes_total=None,
                version=None,
                previous_version=None,
                error=None,
                log_tail=[],
                started_at=None,
                finished_at=None,
            ),
        )

    async def backlog() -> None:
        return None

    bus.add_snapshot("setup", setup)
    bus.add_snapshot("status", status)
    bus.add_snapshot("connection", connection)
    bus.add_snapshot("client", client)
    bus.add_snapshot("backlog", backlog)
