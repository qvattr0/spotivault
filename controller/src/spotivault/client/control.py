"""`LocalClientControl`, the real `ports.ClientControl` for the container.

- **install()** runs spotify-install (config.spotify_install_path) as an asyncio subprocess, in its
  own process group, and yields each JSON line as `InstallProgress`. Its stderr is folded into
  stdout; a line that isn't JSON comes out with stage `log`. If the script exits without a done
  or error line (`set -e` stopped it), a last `error` line is made up. Closing the generator
  early stops the script and its downloads (SIGTERM to the group, SIGKILL 3 s later).
- **installed_version()** reads the /config/spotify/current link.
- **is_running()** looks in /proc for the client's main process (status.client_pids).
- **restart()**: the `spotify` service runs as root's s6, and its control files aren't writable
  by the app user, so `s6-svc -r` can't be used. Instead the client is asked to quit over MPRIS
  (it saves its prefs on the way out), run-spotify's `wait` returns, the script exits, and s6
  starts it again. If it hasn't quit after 15 s, its processes get SIGKILL, as run-spotify's own
  stop does. They run as the app user too, so that's allowed. Only when Quit can't have reached
  the client (MprisNoClient: no bus, or nobody owns the name) is it killed at once. A Quit with
  no answer (NoReply, a timeout) gets the 15 s too: the client may be quitting already.
- **login_signals()**: the `Users/*-user/` folder, and the main window's title from
  `xwininfo -root -tree` (x11-utils). xprop could only read a window it's given; xwininfo lists
  them without help from the window manager, and it's what S0 used.
- **prefs()** reads `Users/*-user/prefs`.

Blocking file and /proc reads go through `asyncio.to_thread` (design.md § Stack).
"""

import asyncio
import contextlib
import json
import logging
import os
import signal
from asyncio.subprocess import DEVNULL, PIPE, STDOUT, Process
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from spotivault.client import status
from spotivault.config import Config
from spotivault.ports import (
    InstallInProgress,
    InstallProgress,
    LoginSignals,
    Mpris,
    MprisNoClient,
    MprisUnavailable,
)

log = logging.getLogger(__name__)

QUIT_TIMEOUT_S = 15.0  # as long as run-spotify's own stop waits
KILL_TIMEOUT_S = 5.0
EXIT_POLL_S = 0.25
INSTALL_STOP_GRACE_S = 3.0
XWININFO_TIMEOUT_S = 2.0  # a local Xvfb answers in milliseconds

# spotify-install's message when its lock is held (step `start`).
LOCK_HELD = "another spotify-install is running"


def parse_install_line(text: str) -> InstallProgress | None:
    """One line of spotify-install's output. None for an empty line; stage `log` for a line that
    isn't one of its JSON objects (stderr from a command that failed)."""
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("stage"), str):
        return InstallProgress(stage="log", message=text)
    return InstallProgress(
        stage=data["stage"],
        message=_text(data.get("message")) or "",
        percent=_number(data.get("percent")),
        bytes=_number(data.get("bytes")),
        total=_number(data.get("total")),
        version=_text(data.get("version")) or None,
        previous=_text(data.get("previous")),
        changed=data["changed"] if isinstance(data.get("changed"), bool) else None,
        step=_text(data.get("step")),
        raw=data,
    )


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class LocalClientControl:
    """`ports.ClientControl` for the container. The attributes set in the constructor (other than
    `config` and `mpris`) are there for tests to point elsewhere."""

    def __init__(self, config: Config, mpris: Mpris) -> None:
        self.config = config
        self.mpris = mpris
        self.proc_root = Path("/proc")
        self.uid: int | None = os.getuid()  # only this user's processes are the client's
        self.xwininfo = "xwininfo"
        self.quit_timeout_s = QUIT_TIMEOUT_S
        self.kill_timeout_s = KILL_TIMEOUT_S
        self._title_problem: str | None = None  # the last xwininfo failure, logged once

    # --- Installing ----------------------------------------------------------------------------

    async def install(
        self, *, version: str | None = None, force: bool = False
    ) -> AsyncIterator[InstallProgress]:
        # env(1) adds SPOTIFY_ROOT to the inherited environment, so the script installs where
        # installed_version() looks, whatever SPOTIVAULT_CONFIG_DIR says.
        command = [
            "env",
            f"SPOTIFY_ROOT={self.config.spotify_dir}",
            str(self.config.spotify_install_path),
        ]
        if version:
            command += ["--version", version]
        if force:
            command.append("--force")
        proc = await asyncio.create_subprocess_exec(
            *command, stdin=DEVNULL, stdout=PIPE, stderr=STDOUT, start_new_session=True
        )
        last_stage: str | None = None
        last_other: str | None = None  # the last line that wasn't JSON
        finished = False
        try:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = parse_install_line(raw.decode("utf-8", errors="replace"))
                if line is None:
                    continue
                if line.stage == "error" and line.step == "start" and LOCK_HELD in line.message:
                    raise InstallInProgress(line.message)
                if line.stage == "log":
                    last_other = line.message
                elif line.stage in ("done", "error"):
                    finished = True
                else:
                    last_stage = line.stage
                yield line
            code = await proc.wait()
            if not finished:
                message = f"spotify-install stopped with exit code {code} and no result"
                if last_other:
                    message += f": {last_other}"
                yield InstallProgress(stage="error", message=message, step=last_stage or "start")
        finally:
            await _stop_group(proc, INSTALL_STOP_GRACE_S)

    async def installed_version(self) -> str | None:
        return await asyncio.to_thread(status.installed_version, self.config.spotify_dir)

    # --- The process ---------------------------------------------------------------------------

    async def is_running(self) -> bool:
        return bool(await asyncio.to_thread(self._main_pids))

    async def restart(self) -> None:
        main = await asyncio.to_thread(self._main_pids)
        if not main:
            log.info("restart: the client isn't running; s6 starts it once it's installed")
            return
        everything = await asyncio.to_thread(self._all_pids)
        try:
            await self.mpris.quit()
            log.info("restart: asked the client to quit (MPRIS Quit); s6 starts it again")
        except MprisNoClient as exc:
            log.warning("restart: MPRIS Quit can't reach the client (%s); killing it", exc)
            await self._kill(main, everything)
            return
        except MprisUnavailable as exc:
            # The client may have got Quit: one that's quitting can leave the bus before it
            # answers. So it gets the same time to finish as after an answer.
            log.warning("restart: MPRIS Quit failed (%s); it may be quitting all the same", exc)
        if await self._wait_gone(main, self.quit_timeout_s):
            return
        log.warning(
            "restart: the client didn't quit within %.0f s; killing it", self.quit_timeout_s
        )
        await self._kill(main, everything)

    async def _kill(self, main: list[int], everything: list[int]) -> None:
        """SIGKILL to every client process, then waits for the main ones to go."""
        for pid in everything:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
        if not await self._wait_gone(main, self.kill_timeout_s):
            log.error("restart: the client (pid %s) is still running after SIGKILL", main)

    # --- Login and settings --------------------------------------------------------------------

    async def login_signals(self) -> LoginSignals:
        folders = await asyncio.to_thread(status.user_folders, self.config.home_dir)
        title = await self.window_title()
        return LoginSignals(user_folder=bool(folders), window_title=title)

    async def window_title(self) -> str | None:
        """The client's main window title, or None when there's no client window (or no X)."""
        command = [self.xwininfo, "-display", self.config.display, "-root", "-tree"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *command, stdin=DEVNULL, stdout=PIPE, stderr=PIPE
            )
        except OSError as exc:
            self._title_failed(f"can't run {self.xwininfo}: {exc}")
            return None
        try:
            async with asyncio.timeout(XWININFO_TIMEOUT_S):
                out, err = await proc.communicate()
        except TimeoutError:
            self._title_failed(f"{self.xwininfo} didn't answer within {XWININFO_TIMEOUT_S:.0f} s")
            return None
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
        if proc.returncode != 0:
            detail = err.decode("utf-8", errors="replace").strip().splitlines()
            self._title_failed(
                f"{self.xwininfo} exited with {proc.returncode}: {detail[-1] if detail else ''}"
            )
            return None
        self._title_problem = None
        return status.main_window_title(out.decode("utf-8", errors="replace"))

    async def prefs(self) -> dict[str, str] | None:
        return await asyncio.to_thread(status.read_prefs, self.config.home_dir)

    # --- Inside --------------------------------------------------------------------------------

    def _main_pids(self) -> list[int]:
        return status.client_pids(self.proc_root, self.config.spotify_dir, self.uid)

    def _all_pids(self) -> list[int]:
        return status.client_pids(
            self.proc_root, self.config.spotify_dir, self.uid, include_helpers=True
        )

    async def _wait_gone(self, pids: list[int], timeout_s: float) -> bool:
        """Waits until none of `pids` runs any more. False if one still does after `timeout_s`."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while True:
            alive = await asyncio.to_thread(self._any_alive, pids)
            if not alive:
                return True
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(EXIT_POLL_S)

    def _any_alive(self, pids: list[int]) -> bool:
        return any(status.pid_alive(self.proc_root, pid) for pid in pids)

    def _title_failed(self, problem: str) -> None:
        if problem != self._title_problem:
            log.warning("login check: %s", problem)
            self._title_problem = problem


async def _stop_group(proc: Process, grace_s: float) -> None:
    """Stops a process started with start_new_session, and everything in its group: SIGTERM, then
    SIGKILL after `grace_s`. Returns once it has exited."""
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        async with asyncio.timeout(grace_s):
            await proc.wait()
        return
    except TimeoutError:
        pass
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)
    await proc.wait()
