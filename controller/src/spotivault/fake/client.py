"""The simulated Spotify client as a program (`ports.ClientControl`): install, process, login.

- **Install** yields spotify-install's own lines (image/rootfs/usr/local/bin/spotify-install):
  stages release, download (a line a second while the percent moves), verify, unpack, libraries,
  switch, then `done`, or `error` with the failing `step`. It takes about 18 s, like S0's 17.6 s
  (Q13); `install_time_scale` compresses it. `fail_install_at` makes it fail at a step, with the
  message the script would print.
- **The process:** s6 starts the client `start_delay_s` after it's installed, and again
  `restart_delay_s` after it quits or crashes, unless it was stopped on purpose (`stop()`).
- **Login** (Q2): logged in means a `Users/*-user/` folder and a window titled other than plain
  "Spotify". `log_in()` is the QR scan; the folder stays after `log_out()`. The window title
  follows the player ("Artist - Title" while playing). `auto_login_after_s` scans the code by
  itself, for walking the wizard in the dev server.
- **Prefs** (Q3): a dict of raw values, as the prefs file has them. `log_in()` gives a tidy file
  (`GOOD_PREFS`) unless told otherwise; `FRESH_PREFS` is what a first login leaves, with every Auto
  row at Spotify's default. `set_pref` changes one key, as the client does when a setting moves.

Owner: the fake agent.
"""

from collections.abc import AsyncIterator, Mapping
from typing import Any

from spotivault.fake.clock import Timer, schedule
from spotivault.fake.player import PlayerEvent, SimPlayer
from spotivault.ports import Clock, InstallInProgress, InstallProgress, LoginSignals

FAKE_VERSION = "1.3.4.258"
OLDER_VERSION = "1.2.63.394"
DEB_BYTES = 179_306_496
DEB_NAME = "spotify-client_1.3.4.258.g7f9d0b3a_amd64.deb"

# A tidy prefs file: every Auto row of the step 4 checklist reads OK (S0 row 26).
GOOD_PREFS = {
    "audio.allow_downgrade": "false",
    "audio.automix": "false",
    "audio.normalize_v2": "false",
    "audio.play_bitrate_enumeration": "4",
    "audio.crossfade_migrated_to_ps": "true",
    "audio.gapless_migrated_to_ps": "true",
}

# After a first login: only the keys for settings kept on Spotify's servers. Every Auto row is at
# Spotify's default, which isn't written (normalization and auto adjust on, quality automatic).
FRESH_PREFS = {
    "audio.crossfade_migrated_to_ps": "true",
    "audio.gapless_migrated_to_ps": "true",
}

# Seconds each stage takes on Docker Desktop (S0 row 23: 17.6 s in all, 14.9 s of download).
STAGE_SECONDS = {
    "release": 0.5,
    "download": 14.9,
    "verify": 0.4,
    "unpack": 1.7,
    "libraries": 0.2,
    "switch": 0.1,
}

# What spotify-install prints when a step fails: fail_install_at → (step, message).
FAILURES = {
    "release": (
        "release",
        "download failed: https://repository.spotify.com/dists/stable/InRelease: "
        "curl: (6) Could not resolve host: repository.spotify.com",
    ),
    "signature": (
        "release",
        'InRelease signature check failed (gpgv: BAD signature from "Spotify Public Repository '
        'Signing Key <tux@spotify.com>"); the repository key may have changed: update the image',
    ),
    "packages": ("packages", "Packages: sha256 doesn't match"),
    "space": ("space", "not enough free space in /config/spotify: 120 MB free, 683 MB needed"),
    "download": ("download", "download failed: curl: (56) Recv failure: Connection reset by peer"),
    "verify": ("verify", f"{DEB_NAME}: sha256 doesn't match"),
    "unpack": ("unpack", "unpacking failed: dpkg-deb: error: archive has premature member"),
    "libraries": (
        "libraries",
        f"Spotify {FAKE_VERSION} needs libraries this image doesn't have (libgbm.so.1): "
        "update the image",
    ),
    "switch": ("switch", "mv: cannot move '/config/spotify/.tmp/root': Permission denied"),
}


class FakeClientControl:
    """`ports.ClientControl` over the simulated client. See the module docstring."""

    def __init__(self, clock: Clock, player: SimPlayer) -> None:
        self.clock = clock
        self.player = player
        self.version: str | None = None  # the installed version (`current`)
        self.repository_versions = (OLDER_VERSION, FAKE_VERSION)  # newest last
        self.has_user_folder = False  # Users/*-user/ exists; it outlives a logout
        self.login_saved = False  # the client comes back logged in after a restart
        self.prefs_values: dict[str, str] | None = None
        self.prefs_unreadable = False  # prefs() can't read the file: the Unknown pills
        self.signals_override: LoginSignals | None = None  # login_signals() returns this
        self.fail_install_at: str | None = None  # a key of FAILURES
        self.install_time_scale = 1.0  # 0.1: the install takes a tenth of the time
        self.step_seconds: float | None = None  # set: every stage takes this long instead
        self.start_delay_s = 2.0
        self.restart_delay_s = 3.0
        self.auto_login_after_s: float | None = None  # seconds after the client starts
        self.auto_fix_prefs_after_s: float | None = None  # seconds after that login
        self.installs = 0  # finished installs
        self.restarts = 0  # restart() calls
        self.kept_down = False  # stop() was called: s6 doesn't start it again
        self.world: object | None = None  # the FakeWorld it belongs to
        self._installing = False
        self._timers: list[Timer] = []
        player.listeners.append(self._on_player)

    # --- Changing the world (tests and the fake world) -----------------------------------------

    @property
    def running(self) -> bool:
        return self.player.on_bus

    @running.setter
    def running(self, value: bool) -> None:
        if value:
            self.start()
        else:
            self.stop()

    @property
    def signals(self) -> LoginSignals:
        """What login_signals() returns now. Assigning one fixes it until set back to None
        (`signals_override`)."""
        return self.signals_override or LoginSignals(
            user_folder=self.has_user_folder, window_title=self.player.window_title()
        )

    @signals.setter
    def signals(self, value: LoginSignals | None) -> None:
        self.signals_override = value

    def start(self) -> None:
        """The client starts now (s6 brings the service up)."""
        self.kept_down = False
        self._cancel_timers()
        self._client_up()

    def stop(self) -> None:
        """The client stops and stays down."""
        self.kept_down = True
        self._cancel_timers()
        self.player.client_gone()

    def crash(self) -> None:
        """The client dies; s6 starts it again after `restart_delay_s`."""
        self.player.client_gone()

    def log_in(self, *, prefs: Mapping[str, str] | None = None) -> None:
        """The QR code was scanned. `prefs` is the prefs file it leaves: GOOD_PREFS unless given,
        and an existing file is kept."""
        self.has_user_folder = True
        self.login_saved = True
        if self.prefs_values is None or prefs is not None:
            self.prefs_values = dict(GOOD_PREFS if prefs is None else prefs)
        if self.player.on_bus:
            self.player.set_logged_in(True)

    def log_out(self) -> None:
        """The client is logged out (its Users folder stays)."""
        self.login_saved = False
        self.player.set_logged_in(False)

    def set_pref(self, key: str, value: str | None) -> None:
        """Changes one key of the prefs file; None removes it (a setting back at its default)."""
        prefs = dict(self.prefs_values or {})
        if value is None:
            prefs.pop(key, None)
        else:
            prefs[key] = value
        self.prefs_values = prefs

    def apply_good_prefs(self) -> None:
        """Every Auto row set as the checklist wants, as a user would in the client."""
        prefs = dict(self.prefs_values or {})
        prefs.update(GOOD_PREFS)
        self.prefs_values = prefs

    def installed(self, version: str = FAKE_VERSION) -> None:
        """Puts the client in place at once, as an earlier install would have."""
        self.version = version

    # --- ports.ClientControl -------------------------------------------------------------------

    async def install(
        self, *, version: str | None = None, force: bool = False
    ) -> AsyncIterator[InstallProgress]:
        if self._installing:
            raise InstallInProgress("another spotify-install is running")
        self._installing = True
        try:
            async for line in self._install(version, force):
                yield line
        finally:
            self._installing = False

    async def installed_version(self) -> str | None:
        return self.version

    async def is_running(self) -> bool:
        return self.player.on_bus

    async def restart(self) -> None:
        """Quits the client and returns once it's gone; it comes back `restart_delay_s` later,
        still logged in if it was (the login is saved in /config)."""
        self.restarts += 1
        self.player.client_gone()

    async def login_signals(self) -> LoginSignals:
        return self.signals

    async def prefs(self) -> dict[str, str] | None:
        if not self.has_user_folder or self.prefs_unreadable or self.prefs_values is None:
            return None
        return dict(self.prefs_values)

    # --- Inside --------------------------------------------------------------------------------

    async def _install(self, version: str | None, force: bool) -> AsyncIterator[InstallProgress]:
        failure = FAILURES.get(self.fail_install_at or "")
        fails_at = failure[0] if failure else None

        yield _line("release", "Checking Spotify's repository")
        await self._wait("release")
        if fails_at == "release":
            yield _error(failure)
            return
        if fails_at == "packages":
            yield _error(failure)
            return
        target = version or self.repository_versions[-1]
        if target not in self.repository_versions:
            yield _error(("packages", f"no spotify-client {target} in the repository"))
            return
        if self.version == target and not force:
            yield _line(
                "done",
                f"Spotify {target} is already installed",
                version=target,
                previous="",
                changed=False,
            )
            return
        if fails_at == "space":
            yield _error(failure)
            return

        # The script checks the file's size once a second and prints the percent when it moved.
        message = f"Downloading Spotify {target}"
        yield _line("download", message, percent=0, bytes=0, total=DEB_BYTES)
        total_s = STAGE_SECONDS["download"]
        whole_s = int(total_s)
        for second in range(1, whole_s + 1):
            await self._wait("download", 1 / total_s)
            percent = int(second * 100 / total_s)
            if fails_at == "download" and percent >= 40:
                yield _error(failure)
                return
            done = DEB_BYTES * percent // 100
            yield _line("download", message, percent=percent, bytes=done, total=DEB_BYTES)
        await self._wait("download", (total_s - whole_s) / total_s)
        yield _line(
            "download",
            f"Downloaded Spotify {target}",
            percent=100,
            bytes=DEB_BYTES,
            total=DEB_BYTES,
        )

        steps = [
            ("verify", "Checking the download"),
            ("unpack", "Unpacking"),
            ("libraries", "Checking the client's libraries"),
            ("switch", f"Switching to Spotify {target}"),
        ]
        for stage, text in steps:
            yield _line(stage, text)
            await self._wait(stage)
            if fails_at == stage:
                yield _error(failure)
                return

        previous = self.version if self.version != target else None
        self.version = target
        self.installs += 1
        yield _line(
            "done",
            f"Installed Spotify {target}",
            version=target,
            previous=previous or "",
            changed=True,
        )
        if not self.player.on_bus and not self.kept_down:
            self._later(self.start_delay_s, self._client_up)

    async def _wait(self, stage: str, share: float = 1.0) -> None:
        """Sleeps for `share` of a stage's time on the clock."""
        if self.step_seconds is not None:
            seconds = self.step_seconds * share
        else:
            seconds = STAGE_SECONDS[stage] * share * self.install_time_scale
        await self.clock.sleep(seconds)

    def _client_up(self) -> None:
        """s6 has started the client: on the bus, logged in if a login is saved."""
        if self.version is None or self.kept_down or self.player.on_bus:
            return
        self.player.logged_in = False
        self.player.client_started()
        if self.login_saved:
            self.player.set_logged_in(True)
        elif self.auto_login_after_s is not None:
            self._later(self.auto_login_after_s, self._auto_login)

    def _auto_login(self) -> None:
        if not self.player.on_bus or self.login_saved:
            return
        if self.auto_fix_prefs_after_s is None:
            self.log_in()
            return
        self.log_in(prefs=FRESH_PREFS)
        self._later(self.auto_fix_prefs_after_s, self.apply_good_prefs)

    def _on_player(self, event: PlayerEvent) -> None:
        # The client left the bus (Quit, a crash, a restart): s6 starts it again.
        if event.kind == "bus" and not event.on_bus:
            self._cancel_timers()
            if not self.kept_down:
                self._later(self.restart_delay_s, self._client_up)

    def _later(self, delay: float, callback: Any) -> None:
        self._timers.append(schedule(self.clock, delay, callback))

    def _cancel_timers(self) -> None:
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()


def _line(stage: str, message: str, **extra: Any) -> InstallProgress:
    """One spotify-install line, with `raw` as the script prints it."""
    raw = {"stage": stage, "message": message, **extra}
    return InstallProgress(stage=stage, message=message, raw=raw, **extra)


def _error(failure: tuple[str, str] | None) -> InstallProgress:
    step, message = failure or ("start", "spotify-install failed")
    return InstallProgress(
        stage="error",
        message=message,
        step=step,
        raw={"stage": "error", "message": message, "step": step},
    )
