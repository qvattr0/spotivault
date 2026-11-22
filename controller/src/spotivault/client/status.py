"""The client's running and login state (web-ui.md step 3; Q2, resolved in S0).

Logged in means the `Users/*-user/` folder under /config/home/.config/spotify exists **and** the
client's window has a title other than plain "Spotify" ("Spotify Premium" when idle, "Artist -
Title" while playing). A logged-out client still publishes MPRIS, so MPRIS is no signal. The Web
API device list confirms it (step 5, S5). Evidence: prototype/FINDINGS.md row 24.

The functions here are plain and blocking (they read files and /proc): `LocalClientControl` runs
them with `asyncio.to_thread`. `is_logged_in` and `main_window_title` are pure.
"""

import os
import re
from pathlib import Path

from spotivault.ports import LoginSignals

# The titles a logged-out client shows (S0: "Spotify" and "spotify"), compared without case.
LOGGED_OUT_TITLE = "spotify"

# One window in `xwininfo -root -tree`:
#     0x1000003 "Spotify Premium": ("spotify" "Spotify")  1280x800+0+0  +0+0
# The name may hold anything, so it's matched greedily up to the class list in parentheses.
_TREE_WINDOW = re.compile(
    r'^\s*0x[0-9a-fA-F]+ "(?P<name>.*)": \((?P<cls>[^()]*)\)\s+(?P<w>\d+)x(?P<h>\d+)'
)


def is_logged_in(signals: LoginSignals) -> bool:
    """Q2's rule: the user folder exists and the window title isn't plain "Spotify"."""
    title = (signals.window_title or "").strip()
    return signals.user_folder and title != "" and title.lower() != LOGGED_OUT_TITLE


def main_window_title(tree: str) -> str | None:
    """The client's main window title in the output of `xwininfo -root -tree`, or None.

    The client's windows have the class `("spotify" "Spotify")`. Chromium also makes small
    helper windows with that class (named "spotify"), so the main window is the largest one.
    """
    best: tuple[int, str] | None = None
    for line in tree.splitlines():
        match = _TREE_WINDOW.match(line)
        if match is None or "spotify" not in match["cls"].lower():
            continue
        area = int(match["w"]) * int(match["h"])
        if best is None or area > best[0]:
            best = (area, match["name"])
    return None if best is None else best[1]


def spotify_config_dir(home: Path) -> Path:
    """The client's settings folder: $HOME/.config/spotify."""
    return home / ".config" / "spotify"


def user_folders(home: Path) -> list[Path]:
    """The client's `Users/<id>-user/` folders. One exists once someone has logged in."""
    users = spotify_config_dir(home) / "Users"
    try:
        return sorted(p for p in users.iterdir() if p.is_dir() and p.name.endswith("-user"))
    except OSError:
        return []


def read_prefs(home: Path) -> dict[str, str] | None:
    """The logged-in user's prefs file (`Users/<id>-user/prefs`) as key → raw value, or None
    when there's none or it can't be read.

    Each line is `key=value`; values are kept as written (`false`, `4`, `"text"`). If several
    accounts have logged in on this client, the most recently saved prefs file is the current
    one's.
    """
    files = []
    for folder in user_folders(home):
        path = folder / "prefs"
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue
    if not files:
        return None
    _, newest = max(files)
    try:
        text = newest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    prefs: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip():
            prefs[key.strip()] = value.strip()
    return prefs


def installed_version(spotify_dir: Path) -> str | None:
    """The version `spotify_dir/current` points to (`versions/<version>`), if its binary can run
    (the test run-spotify waits on). spotify-install switches the link in one rename, so it's
    never half-written."""
    current = spotify_dir / "current"
    try:
        target = os.readlink(current)
    except OSError:
        return None
    if not os.access(current / "spotify", os.X_OK):
        return None
    version = Path(target).name
    return version or None


def client_pids(
    proc_root: Path, client_root: Path, uid: int | None, *, include_helpers: bool = False
) -> list[int]:
    """The client's main processes: started from a binary under `client_root` (/config/spotify;
    run-spotify starts /config/spotify/current/spotify) and named `spotify`. Chromium's helper
    processes (`--type=renderer` and the like) are left out unless `include_helpers`. `uid`
    limits it to one user's processes (the app user's), None to any.
    """
    prefix = str(client_root).rstrip("/") + "/"
    pids = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if uid is not None and entry.stat().st_uid != uid:
                continue
            comm = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
            if comm != "spotify":
                continue
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue  # it exited meanwhile, or isn't ours to read
        program = argv[0].decode("utf-8", errors="replace")
        if not program.startswith(prefix):
            continue
        if not include_helpers and any(arg.startswith(b"--type=") for arg in argv[1:]):
            continue
        pids.append(int(entry.name))
    return sorted(pids)


def pid_alive(proc_root: Path, pid: int) -> bool:
    """The process exists and isn't a zombie."""
    try:
        stat = (proc_root / str(pid) / "stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    # "<pid> (<comm>) <state> ...": the state follows the last ")".
    state = stat.rpartition(")")[2].split()
    return bool(state) and state[0] != "Z"
