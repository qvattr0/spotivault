"""client/status.py: the login rule (Q2), the window title, the client's processes, prefs and the
installed version. Plain functions on temporary folders; nothing here touches the real client."""

import os
from pathlib import Path

import pytest

from spotivault.client import status
from spotivault.ports import LoginSignals

# What `xwininfo -root -tree` shows (S0, FINDINGS row 24): a logged-in client, idle.
TREE_LOGGED_IN = """
xwininfo: Window id: 0x2a0 (the root window) (has no name)

  Root window id: 0x2a0 (the root window) (has no name)
  Parent window id: 0x0 (none)
     4 children:
     0x600003 (has no name): ()  1280x800+0+0  +0+0
        1 child:
        0x1000003 "Spotify Premium": ("spotify" "Spotify")  1280x800+0+0  +0+0
           1 child:
           0x1000004 (has no name): ()  1x1+-1+-1  +-1+-1
     0x1000001 "spotify": ("spotify" "Spotify")  10x10+10+10  +10+10
     0x400001 "matchbox": ()  1x1+-100+-100  +-100+-100
"""

TREE_LOGGED_OUT = """
     0x1000003 "Spotify": ("spotify" "Spotify")  1280x800+0+0  +0+0
     0x1000001 "spotify": ("spotify" "Spotify")  10x10+10+10  +10+10
"""

TREE_PLAYING = """
     0x1000001 "spotify": ("spotify" "Spotify")  10x10+10+10  +10+10
     0x1000003 "Mazzy Star - Fade Into You": ("spotify" "Spotify")  1280x800+0+0  +0+0
"""


@pytest.mark.parametrize(
    ("signals", "logged_in"),
    [
        (LoginSignals(user_folder=True, window_title="Spotify Premium"), True),
        (LoginSignals(user_folder=True, window_title="Artist - Title"), True),
        (LoginSignals(user_folder=True, window_title="Spotify"), False),
        (LoginSignals(user_folder=True, window_title="spotify"), False),
        (LoginSignals(user_folder=True, window_title=" Spotify "), False),
        (LoginSignals(user_folder=True, window_title=""), False),
        (LoginSignals(user_folder=True, window_title=None), False),
        (LoginSignals(user_folder=False, window_title="Spotify Premium"), False),
    ],
)
def test_logged_in_needs_the_user_folder_and_a_title_other_than_spotify(
    signals: LoginSignals, logged_in: bool
) -> None:
    assert status.is_logged_in(signals) is logged_in


@pytest.mark.parametrize(
    ("tree", "title"),
    [
        (TREE_LOGGED_IN, "Spotify Premium"),
        (TREE_LOGGED_OUT, "Spotify"),
        (TREE_PLAYING, "Mazzy Star - Fade Into You"),
        # A title may hold quotes and parentheses: it's taken up to the class list.
        (
            '     0x1 "Band - Song": (Live)": ("spotify" "Spotify")  800x600+0+0  +0+0',
            'Band - Song": (Live)',
        ),
        ("xwininfo: Window id: 0x2a0 (the root window) (has no name)\n", None),
        ("", None),
    ],
)
def test_the_main_window_is_the_largest_spotify_window(tree: str, title: str | None) -> None:
    assert status.main_window_title(tree) == title


def test_user_folders_and_prefs(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert status.user_folders(home) == []
    assert status.read_prefs(home) is None

    users = home / ".config" / "spotify" / "Users"
    (users / "old-user").mkdir(parents=True)
    (users / "old-user" / "prefs").write_text('audio.automix=true\nautologin.username="old"\n')
    os.utime(users / "old-user" / "prefs", (1_000_000, 1_000_000))
    (users / "lorne-user").mkdir()
    (users / "lorne-user" / "prefs").write_text(
        "audio.automix=false\n"
        "audio.play_bitrate_enumeration=4\n"
        'autologin.username="lorne"\n'
        "not a pair\n"
        "\n"
    )
    (users / "not-a-user-folder").mkdir()
    assert [p.name for p in status.user_folders(home)] == ["lorne-user", "old-user"]
    # Several accounts: the most recently saved prefs file is the current one's.
    assert status.read_prefs(home) == {
        "audio.automix": "false",
        "audio.play_bitrate_enumeration": "4",
        "autologin.username": '"lorne"',
    }


def test_a_user_folder_without_prefs_reads_as_none(tmp_path: Path) -> None:
    (tmp_path / ".config" / "spotify" / "Users" / "x-user").mkdir(parents=True)
    assert len(status.user_folders(tmp_path)) == 1
    assert status.read_prefs(tmp_path) is None


def make_client(spotify_dir: Path, version: str) -> Path:
    """A fake installed client: versions/<version>/spotify, executable, and the current link."""
    folder = spotify_dir / "versions" / version
    folder.mkdir(parents=True)
    binary = folder / "spotify"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    (spotify_dir / "current").symlink_to(f"versions/{version}")
    return binary


def test_installed_version_follows_the_current_link(tmp_path: Path) -> None:
    spotify_dir = tmp_path / "spotify"
    assert status.installed_version(spotify_dir) is None
    binary = make_client(spotify_dir, "1.3.4.258")
    assert status.installed_version(spotify_dir) == "1.3.4.258"
    binary.chmod(0o644)  # run-spotify waits for an executable binary, and so does this
    assert status.installed_version(spotify_dir) is None


def fake_process(proc: Path, pid: int, comm: str, argv: list[str], state: str = "S") -> None:
    folder = proc / str(pid)
    folder.mkdir(parents=True)
    (folder / "comm").write_text(comm + "\n")
    (folder / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (folder / "stat").write_text(f"{pid} ({comm}) {state} 1 {pid} {pid} 0 -1\n")


def test_client_pids_finds_the_main_process_only(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    binary = "/config/spotify/current/spotify"
    fake_process(proc, 120, "spotify", [binary, "--no-zygote", "--no-sandbox", "--disable-gpu"])
    fake_process(proc, 130, "spotify", [binary, "--type=renderer", "--lang=en-US"])
    fake_process(proc, 131, "chrome_crashpad", [binary, "--type=crashpad-handler"])
    fake_process(proc, 140, "spotify", ["/usr/bin/spotify"])  # someone else's Spotify
    fake_process(proc, 150, "sh", ["/bin/sh", "/etc/s6-overlay/scripts/run-spotify"])
    (proc / "self").mkdir()
    (proc / "uptime").write_text("1.0 1.0\n")

    root = Path("/config/spotify")
    assert status.client_pids(proc, root, None) == [120]
    assert status.client_pids(proc, root, None, include_helpers=True) == [120, 130]
    assert status.client_pids(proc, root, os.getuid()) == [120]
    assert status.client_pids(proc, root, os.getuid() + 1) == []
    assert status.client_pids(tmp_path / "no-proc", root, None) == []


def test_pid_alive_treats_a_zombie_as_gone(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    fake_process(proc, 7, "spotify (beta)", ["/x"], state="S")
    fake_process(proc, 8, "spotify", ["/x"], state="Z")
    assert status.pid_alive(proc, 7)
    assert not status.pid_alive(proc, 8)
    assert not status.pid_alive(proc, 9)
