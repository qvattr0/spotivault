"""Installing the client: spotify-install's progress lines to the contract's `ClientInstall`.

spotify-install (image/rootfs/usr/local/bin/spotify-install) prints one JSON object per line. Its
stages are release, download, verify, unpack, libraries, switch, then done or error (an error has
the `step` that failed: start, release, packages, space, download, verify, unpack, libraries,
switch or cleanup). The contract's phases are release, packages, download, unpack, libraries and
switch; its error codes network, signature, checksum, disk_full, missing_libraries and unknown.

- `InstallTracker` follows one attempt line by line and builds the `ClientInstall` snapshot.
- The `client_install` table keeps one row per attempt (contracts/schema.sql). The functions at
  the bottom read and write it; the log tail lives in memory only.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from spotivault.api.models import ClientInstall, ClientInstallError
from spotivault.clock import iso_ms, parse_iso
from spotivault.ports import InstallProgress
from spotivault.store import Store

type Phase = Literal["release", "packages", "download", "unpack", "libraries", "switch"]
type ErrorCode = Literal[
    "network", "signature", "checksum", "disk_full", "missing_libraries", "unknown"
]

LOG_TAIL_MAX = 50  # ClientInstall.log_tail's maxItems

# The script's stage → the contract's phase. `verify` checks the .deb's sha256, which the contract
# counts as part of `download`. `packages` has no line of its own (the script goes from `release`
# to `download` without one), so that phase only shows up when it fails.
STAGE_PHASES: dict[str, Phase] = {
    "release": "release",
    "download": "download",
    "verify": "download",
    "unpack": "unpack",
    "libraries": "libraries",
    "switch": "switch",
}

# An error line's `step` → the phase it failed in. `start` (the lock, or run as root) has none;
# `space` is the free-space check just before the download; `cleanup` comes after the switch.
STEP_PHASES: dict[str, Phase] = {
    "release": "release",
    "packages": "packages",
    "space": "download",
    "download": "download",
    "verify": "download",
    "unpack": "unpack",
    "libraries": "libraries",
    "switch": "switch",
    "cleanup": "switch",
}

# Overall progress (0 to 1) at the start and end of each phase. Rough shares of S0's 17.6 s install
# (prototype/FINDINGS.md row 23), where the 179 MB download took 14.9 s.
PHASE_SPANS: dict[Phase, tuple[float, float]] = {
    "release": (0.0, 0.03),
    "packages": (0.03, 0.05),
    "download": (0.05, 0.9),
    "unpack": (0.9, 0.97),
    "libraries": (0.97, 0.99),
    "switch": (0.99, 1.0),
}


def error_code(step: str | None, message: str) -> ErrorCode:
    """The contract's error code for an error line, from its step and spotify-install's message."""
    text = message.lower()
    if step == "space" or "no space left" in text:
        return "disk_full"
    if text.startswith("download failed"):
        return "network"
    if "signature" in text:
        return "signature"
    if "sha256" in text or "wrong size" in text:
        return "checksum"
    if step == "libraries":
        return "missing_libraries"
    return "unknown"


def overall_progress(stage: str, percent: int | None) -> float | None:
    """Overall progress for a progress line, or None for a stage that has no phase."""
    phase = STAGE_PHASES.get(stage)
    if phase is None:
        return None
    start, end = PHASE_SPANS[phase]
    if stage == "verify":
        return end  # the download is complete
    if stage == "download" and percent is not None:
        share = min(max(percent, 0), 100) / 100
        return round(start + (end - start) * share, 3)
    return start


@dataclass(frozen=True, slots=True)
class InstallUpdate:
    """What one line changed, so the manager knows what to save and whether to publish."""

    phase_changed: bool
    log_line: str | None  # a new line for the log tail, or None
    finished: bool  # this line was the attempt's last (done or error)


class InstallTracker:
    """One install attempt, followed line by line. `snapshot()` is its `ClientInstall`."""

    def __init__(self, started_at: datetime) -> None:
        self.state: Literal["installing", "installed", "failed"] = "installing"
        self.phase: Phase | None = None
        self.progress: float | None = 0.0
        self.bytes_done: int | None = None
        self.bytes_total: int | None = None
        self.version: str | None = None
        self.previous_version: str | None = None
        self.error: ClientInstallError | None = None
        self.log_tail: list[str] = []
        self.started_at = started_at
        self.finished_at: datetime | None = None

    @property
    def finished(self) -> bool:
        return self.state != "installing"

    def apply(self, line: InstallProgress, now: datetime) -> InstallUpdate:
        """Takes in one line. Lines after the last one (done or error) are ignored."""
        if self.finished:
            return InstallUpdate(phase_changed=False, log_line=None, finished=False)
        old_phase = self.phase
        message = line.message.strip()
        log_line = self._log(message)
        if line.version:
            self.version = line.version

        if line.stage == "done":
            self.state = "installed"
            self.phase = None
            self.previous_version = line.previous or None
            self._finish(now)
        elif line.stage == "error":
            self.state = "failed"
            self.phase = STEP_PHASES.get(line.step or "", self.phase)
            self.error = ClientInstallError(
                code=error_code(line.step, message), message=message or "The install failed."
            )
            self._finish(now)
        elif line.stage in STAGE_PHASES:
            self.phase = STAGE_PHASES[line.stage]
            self.progress = overall_progress(line.stage, line.percent)
            if line.stage == "download" and line.total is not None:
                self.bytes_done = line.bytes
                self.bytes_total = line.total
        # Any other stage (a line of stderr, `check`) only adds to the log.

        return InstallUpdate(
            phase_changed=self.phase != old_phase, log_line=log_line, finished=self.finished
        )

    def fail(self, code: ErrorCode, message: str, now: datetime) -> str | None:
        """Ends the attempt as failed without an error line from the script (it was stopped, or
        it exited without one). Returns the new log line, if any."""
        if self.finished:
            return None
        log_line = self._log(message)
        self.state = "failed"
        self.error = ClientInstallError(code=code, message=message)
        self._finish(now)
        return log_line

    def snapshot(self) -> ClientInstall:
        return ClientInstall(
            state=self.state,
            phase=self.phase,
            progress=self.progress,
            bytes_done=self.bytes_done,
            bytes_total=self.bytes_total,
            version=self.version,
            previous_version=self.previous_version,
            error=self.error,
            log_tail=list(self.log_tail),
            started_at=self.started_at,
            finished_at=self.finished_at,
        )

    def _log(self, message: str) -> str | None:
        # Download progress repeats its message every second: keep it once.
        if not message or (self.log_tail and self.log_tail[-1] == message):
            return None
        self.log_tail.append(message)
        del self.log_tail[:-LOG_TAIL_MAX]
        return message

    def _finish(self, now: datetime) -> None:
        self.progress = None
        self.bytes_done = None
        self.bytes_total = None
        self.finished_at = now


def not_started() -> ClientInstall:
    """No install attempt yet."""
    return ClientInstall(
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
    )


def installed_outside(version: str) -> ClientInstall:
    """The client is installed, but no attempt is recorded (installed by hand with docker exec,
    or before the controller kept the table)."""
    return not_started().model_copy(update={"state": "installed", "version": version})


# --- The client_install table ---------------------------------------------------------------------


async def insert_attempt(store: Store, started_at: datetime) -> int:
    """A new row for an attempt that starts now. Returns its id."""
    result = await store.execute(
        "INSERT INTO client_install (started_at, state) VALUES (?, 'installing')",
        (iso_ms(started_at),),
    )
    assert result.lastrowid is not None
    return result.lastrowid


async def save_phase(store: Store, attempt_id: int, phase: Phase | None) -> None:
    await store.execute("UPDATE client_install SET phase = ? WHERE id = ?", (phase, attempt_id))


async def save_finished(store: Store, attempt_id: int, tracker: InstallTracker) -> None:
    """Stores the attempt's outcome. A successful one becomes the `current` install."""
    finished_at = iso_ms(tracker.finished_at) if tracker.finished_at else None
    code = tracker.error.code if tracker.error else None
    message = tracker.error.message if tracker.error else None
    installed = tracker.state == "installed"

    def write(conn: sqlite3.Connection) -> None:
        if installed:
            conn.execute("UPDATE client_install SET is_current = 0 WHERE is_current = 1")
        conn.execute(
            "UPDATE client_install SET state = ?, phase = ?, finished_at = ?, version = ?,"
            " error_code = ?, error_message = ?, is_current = ? WHERE id = ?",
            (
                tracker.state,
                tracker.phase,
                finished_at,
                tracker.version,
                code,
                message,
                1 if installed else 0,
                attempt_id,
            ),
        )

    await store.transaction(write)


async def fail_interrupted(store: Store, now: datetime) -> int:
    """Rows still `installing` at start-up are from a controller that stopped mid-install: they
    become failed. Returns how many."""
    result = await store.execute(
        "UPDATE client_install SET state = 'failed', finished_at = ?, error_code = 'unknown',"
        " error_message = ? WHERE state = 'installing'",
        (iso_ms(now), "The controller stopped during the install."),
    )
    return result.rowcount


async def load_latest(store: Store) -> ClientInstall | None:
    """The latest attempt as a `ClientInstall` (without its log tail), or None if there's none."""
    row = await store.fetchone(
        "SELECT state, phase, version, error_code, error_message, started_at, finished_at"
        " FROM client_install ORDER BY id DESC LIMIT 1"
    )
    if row is None:
        return None
    error = None
    if row["error_code"] is not None:
        error = ClientInstallError(
            code=row["error_code"], message=row["error_message"] or "The install failed."
        )
    return ClientInstall(
        state=row["state"],
        phase=row["phase"],
        progress=None,
        bytes_done=None,
        bytes_total=None,
        version=row["version"],
        previous_version=None,
        error=error,
        log_tail=[],
        started_at=parse_iso(row["started_at"]),
        finished_at=parse_iso(row["finished_at"]) if row["finished_at"] else None,
    )
