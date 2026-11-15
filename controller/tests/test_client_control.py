"""client/control.py: `LocalClientControl` against stand-ins for spotify-install, xwininfo and the
client's process. Nothing here runs the real client or the real installer."""

import asyncio
import contextlib
import dataclasses
import os
import signal
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from portcheck import assert_implements
from spotivault import ports
from spotivault.client import status
from spotivault.client.control import LocalClientControl
from spotivault.config import Config
from spotivault.ports import InstallInProgress, InstallProgress, MprisNoClient, MprisUnavailable

PROC = Path("/proc")


class StubMpris:
    """Only Quit matters here. `on_quit` is what the client does when asked to quit:
    - "exit": it answers and quits (SIGTERM stands in for its clean exit);
    - "exit_silently": it quits a moment later without answering, so the bus says NoReply;
    - "hang": it answers and keeps running;
    - "silent_hang": it doesn't answer, and keeps running;
    - "no_client": Quit can't reach it (nobody owns its MPRIS name)."""

    def __init__(self, on_quit: str = "exit") -> None:
        self.on_quit = on_quit
        self.quits = 0
        self.process: asyncio.subprocess.Process | None = None

    async def quit(self) -> None:
        self.quits += 1
        if self.on_quit == "no_client":
            raise MprisNoClient("org.freedesktop.DBus.Error.ServiceUnknown")
        if self.on_quit == "exit" and self.process is not None:
            self.process.terminate()
        if self.on_quit == "exit_silently":
            assert self.process is not None
            asyncio.get_running_loop().call_later(0.3, self.process.terminate)
        if self.on_quit in ("exit_silently", "silent_hang"):
            raise MprisUnavailable("org.freedesktop.DBus.Error.NoReply")


def script(folder: Path, name: str, body: str) -> Path:
    path = folder / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def control_for(config: Config, installer: Path | None = None) -> LocalClientControl:
    if installer is not None:
        config = dataclasses.replace(config, spotify_install_path=installer)
    return LocalClientControl(config, StubMpris())  # type: ignore[arg-type]


async def collect(lines: AsyncIterator[InstallProgress]) -> list[InstallProgress]:
    async with contextlib.aclosing(lines) as stream:
        return [line async for line in stream]


def test_it_implements_the_port() -> None:
    assert_implements(LocalClientControl, ports.ClientControl)


# --- install -------------------------------------------------------------------------------------

FAKE_INSTALL = r"""
set -eu
root="$SPOTIFY_ROOT"
echo '{"stage":"release","message":"Checking Spotify'"'"'s repository"}'
echo "{\"stage\":\"download\",\"message\":\"args: $*\",\"percent\":50,\"bytes\":5,\"total\":10}"
mkdir -p "$root/versions/1.3.4.258"
printf '#!/bin/sh\n' > "$root/versions/1.3.4.258/spotify"
chmod +x "$root/versions/1.3.4.258/spotify"
ln -s versions/1.3.4.258 "$root/current.new"
mv -T "$root/current.new" "$root/current"
echo '{"stage":"done","message":"Installed","version":"1.3.4.258","previous":"","changed":true}'
"""


async def test_install_runs_the_script_and_yields_its_lines(config: Config, tmp_path: Path) -> None:
    control = control_for(config, script(tmp_path, "spotify-install", FAKE_INSTALL))
    assert await control.installed_version() is None

    lines = await collect(control.install(version="1.3.4.258", force=True))
    assert [line.stage for line in lines] == ["release", "download", "done"]
    assert lines[1].message == "args: --version 1.3.4.258 --force"
    assert (lines[1].percent, lines[1].bytes, lines[1].total) == (50, 5, 10)
    assert (lines[2].version, lines[2].changed) == ("1.3.4.258", True)
    # SPOTIFY_ROOT is the config's spotify folder, so the version is where the controller looks.
    assert await control.installed_version() == "1.3.4.258"
    assert (config.spotify_dir / "current").is_symlink()


async def test_an_error_line_ends_the_install(config: Config, tmp_path: Path) -> None:
    installer = script(
        tmp_path,
        "spotify-install",
        """echo '{"stage":"release","message":"Checking"}'
echo '{"stage":"error","message":"download failed: no route","step":"release"}'
exit 1
""",
    )
    lines = await collect(control_for(config, installer).install())
    assert [(line.stage, line.step) for line in lines] == [("release", None), ("error", "release")]


async def test_a_script_that_stops_without_a_result_gets_an_error_line(
    config: Config, tmp_path: Path
) -> None:
    installer = script(
        tmp_path,
        "spotify-install",
        """echo '{"stage":"switch","message":"Switching"}'
echo "mv: cannot move 'x' to 'y': No space left on device" >&2
exit 1
""",
    )
    lines = await collect(control_for(config, installer).install())
    assert [line.stage for line in lines] == ["switch", "log", "error"]
    assert lines[1].message == "mv: cannot move 'x' to 'y': No space left on device"
    assert lines[2].step == "switch"
    assert lines[2].message == (
        "spotify-install stopped with exit code 1 and no result: "
        "mv: cannot move 'x' to 'y': No space left on device"
    )


async def test_a_held_lock_raises_install_in_progress(config: Config, tmp_path: Path) -> None:
    installer = script(
        tmp_path,
        "spotify-install",
        """echo '{"stage":"error","message":"another spotify-install is running","step":"start"}'
exit 1
""",
    )
    with pytest.raises(InstallInProgress):
        await collect(control_for(config, installer).install())


async def wait_until_gone(pid: int, timeout_s: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if not await asyncio.to_thread(status.pid_alive, PROC, pid):
            return True
        await asyncio.sleep(0.05)
    return False


async def test_closing_the_install_early_stops_the_script_and_its_children(
    config: Config, tmp_path: Path
) -> None:
    pids = tmp_path / "pids"
    installer = script(
        tmp_path,
        "spotify-install",
        f"""sleep 30 &
echo "$$ $!" > '{pids}'
echo '{{"stage":"release","message":"Checking"}}'
wait
""",
    )
    lines = control_for(config, installer).install()
    first = await anext(lines)
    assert first.stage == "release"
    script_pid, child_pid = (int(p) for p in pids.read_text().split())
    await lines.aclose()  # type: ignore[attr-defined]
    assert await wait_until_gone(script_pid)
    assert await wait_until_gone(child_pid)  # the download it started goes too


# --- The process and restart ---------------------------------------------------------------------


@pytest.fixture
def client_binary(config: Config) -> Path:
    """A stand-in client: Python, started as /config/spotify/current/spotify (here, under the
    test's config folder), so its process is named `spotify` like the real one."""
    folder = config.spotify_dir / "versions" / "1.3.4.258"
    folder.mkdir(parents=True)
    (folder / "spotify").symlink_to(Path(sys.executable).resolve())
    (config.spotify_dir / "current").symlink_to("versions/1.3.4.258")
    return config.spotify_dir / "current" / "spotify"


@pytest.fixture
async def running_client(client_binary: Path) -> AsyncIterator[asyncio.subprocess.Process]:
    proc = await asyncio.create_subprocess_exec(
        str(client_binary), "-c", "import time; time.sleep(30)"
    )
    yield proc
    if proc.returncode is None:
        proc.kill()
    await proc.wait()


async def test_is_running_finds_the_client(
    config: Config, running_client: asyncio.subprocess.Process
) -> None:
    control = control_for(config)
    assert await control.is_running()
    running_client.kill()
    await running_client.wait()
    assert not await control.is_running()


async def test_restart_asks_the_client_to_quit(
    config: Config, running_client: asyncio.subprocess.Process
) -> None:
    control = control_for(config)
    mpris = StubMpris("exit")
    mpris.process = running_client
    control.mpris = mpris  # type: ignore[assignment]
    await control.restart()
    assert mpris.quits == 1
    assert await running_client.wait() == -signal.SIGTERM  # it quit by itself; no SIGKILL


async def test_restart_kills_a_client_that_doesnt_quit(
    config: Config, running_client: asyncio.subprocess.Process
) -> None:
    control = control_for(config)
    control.mpris = StubMpris("hang")  # type: ignore[assignment]
    control.quit_timeout_s = 0.3
    await control.restart()
    assert await running_client.wait() == -signal.SIGKILL


async def test_restart_kills_the_client_at_once_when_quit_cant_reach_it(
    config: Config, running_client: asyncio.subprocess.Process
) -> None:
    control = control_for(config)
    mpris = StubMpris("no_client")
    control.mpris = mpris  # type: ignore[assignment]
    control.quit_timeout_s = 60.0  # never waited for: nothing can be quitting
    async with asyncio.timeout(10):
        await control.restart()
    assert mpris.quits == 1
    assert await running_client.wait() == -signal.SIGKILL


async def test_restart_waits_for_a_client_that_quits_without_answering(
    config: Config, running_client: asyncio.subprocess.Process
) -> None:
    control = control_for(config)
    mpris = StubMpris("exit_silently")
    mpris.process = running_client
    control.mpris = mpris  # type: ignore[assignment]
    await control.restart()
    assert mpris.quits == 1
    assert await running_client.wait() == -signal.SIGTERM  # it quit by itself; no SIGKILL


async def test_restart_kills_a_client_that_neither_answers_nor_quits(
    config: Config, running_client: asyncio.subprocess.Process
) -> None:
    control = control_for(config)
    control.mpris = StubMpris("silent_hang")  # type: ignore[assignment]
    control.quit_timeout_s = 0.3
    await control.restart()
    assert await running_client.wait() == -signal.SIGKILL


async def test_restart_without_a_client_does_nothing(config: Config, client_binary: Path) -> None:
    control = control_for(config)
    mpris = StubMpris("no_client")
    control.mpris = mpris  # type: ignore[assignment]
    await control.restart()
    assert mpris.quits == 0


# --- Login signals and prefs ---------------------------------------------------------------------


async def test_login_signals_read_the_folder_and_the_window_title(
    config: Config, tmp_path: Path
) -> None:
    control = control_for(config)
    control.xwininfo = str(
        script(
            tmp_path,
            "xwininfo",
            """[ "$1 $2 $3 $4" = "-display :99 -root -tree" ] || exit 9
echo '     0x1000003 "Spotify Premium": ("spotify" "Spotify")  1280x800+0+0  +0+0'
echo '     0x1000001 "spotify": ("spotify" "Spotify")  10x10+10+10  +10+10'
""",
        )
    )
    signals = await control.login_signals()
    assert (signals.user_folder, signals.window_title) == (False, "Spotify Premium")

    (config.home_dir / ".config" / "spotify" / "Users" / "lorne-user").mkdir(parents=True)
    signals = await control.login_signals()
    assert (signals.user_folder, signals.window_title) == (True, "Spotify Premium")


async def test_no_window_title_without_x(
    config: Config, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    control = control_for(config)
    control.xwininfo = str(
        script(tmp_path, "xwininfo", 'echo "xwininfo: error: unable to open display" >&2\nexit 1\n')
    )
    assert await control.window_title() is None
    assert await control.window_title() is None
    problems = [r.getMessage() for r in caplog.records if "login check" in r.getMessage()]
    assert len(problems) == 1  # logged once, not on every check
    assert problems[0].endswith("exited with 1: xwininfo: error: unable to open display")

    control.xwininfo = str(tmp_path / "missing")
    assert await control.window_title() is None


async def test_prefs_come_from_the_user_folder(config: Config) -> None:
    control = control_for(config)
    assert await control.prefs() is None
    folder = config.home_dir / ".config" / "spotify" / "Users" / "lorne-user"
    folder.mkdir(parents=True)
    (folder / "prefs").write_text("audio.automix=false\n")
    assert await control.prefs() == {"audio.automix": "false"}


def test_the_constructor_does_no_io(config: Config) -> None:
    control = LocalClientControl(
        dataclasses.replace(config, config_dir=Path("/nonexistent")),
        StubMpris(),  # type: ignore[arg-type]
    )
    assert control.config.spotify_dir == Path("/nonexistent/spotify")
    assert control.uid == os.getuid()
