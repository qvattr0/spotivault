"""client/install.py: spotify-install's lines → `ClientInstall`, and the client_install table."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contract import assert_schema
from spotivault.client import install
from spotivault.client.control import parse_install_line
from spotivault.client.install import InstallTracker
from spotivault.ports import InstallProgress
from spotivault.store import Store

T0 = datetime(2026, 11, 15, 9, 13, 2, tzinfo=UTC)

# The lines of a real install, as spotify-install prints them (download shortened).
HAPPY = [
    '{"stage":"release","message":"Checking Spotify\'s repository"}',
    '{"stage":"download","message":"Downloading Spotify 1.3.4.258","percent":0,"bytes":0,'
    '"total":179306496}',
    '{"stage":"download","message":"Downloading Spotify 1.3.4.258","percent":41,'
    '"bytes":73400320,"total":179306496}',
    '{"stage":"download","message":"Downloaded Spotify 1.3.4.258","percent":100,'
    '"bytes":179306496,"total":179306496}',
    '{"stage":"verify","message":"Checking the download"}',
    '{"stage":"unpack","message":"Unpacking"}',
    '{"stage":"libraries","message":"Checking the client\'s libraries"}',
    '{"stage":"switch","message":"Switching to Spotify 1.3.4.258"}',
    '{"stage":"done","message":"Installed Spotify 1.3.4.258","version":"1.3.4.258",'
    '"previous":"1.2.0.1","changed":true}',
]


def lines(*texts: str) -> list[InstallProgress]:
    parsed = [parse_install_line(text) for text in texts]
    return [line for line in parsed if line is not None]


def test_a_successful_install() -> None:
    tracker = InstallTracker(T0)
    assert_schema("ClientInstall", tracker.snapshot().model_dump(mode="json"))
    seen = []
    for i, line in enumerate(lines(*HAPPY)):
        update = tracker.apply(line, T0 + timedelta(seconds=i))
        snapshot = tracker.snapshot()
        assert_schema("ClientInstall", snapshot.model_dump(mode="json"))
        seen.append((snapshot.phase, snapshot.progress, update.phase_changed, update.log_line))

    assert seen == [
        ("release", 0.0, True, "Checking Spotify's repository"),
        ("download", 0.05, True, "Downloading Spotify 1.3.4.258"),
        ("download", 0.398, False, None),  # the same message again: no new log line
        ("download", 0.9, False, "Downloaded Spotify 1.3.4.258"),
        ("download", 0.9, False, "Checking the download"),
        ("unpack", 0.9, True, "Unpacking"),
        ("libraries", 0.97, True, "Checking the client's libraries"),
        ("switch", 0.99, True, "Switching to Spotify 1.3.4.258"),
        (None, None, True, "Installed Spotify 1.3.4.258"),
    ]
    final = tracker.snapshot()
    assert final.state == "installed"
    assert (final.version, final.previous_version) == ("1.3.4.258", "1.2.0.1")
    assert (final.bytes_done, final.bytes_total, final.error) == (None, None, None)
    assert final.finished_at == T0 + timedelta(seconds=8)
    assert len(final.log_tail) == 8


def test_download_progress_keeps_the_byte_counts() -> None:
    tracker = InstallTracker(T0)
    for line in lines(*HAPPY[:3]):
        tracker.apply(line, T0)
    snapshot = tracker.snapshot()
    assert (snapshot.bytes_done, snapshot.bytes_total) == (73400320, 179306496)


def test_already_installed_is_installed_without_a_previous_version() -> None:
    tracker = InstallTracker(T0)
    for line in lines(
        '{"stage":"release","message":"Checking Spotify\'s repository"}',
        '{"stage":"done","message":"Spotify 1.3.4.258 is already installed",'
        '"version":"1.3.4.258","previous":"","changed":false}',
    ):
        tracker.apply(line, T0)
    snapshot = tracker.snapshot()
    assert (snapshot.state, snapshot.version, snapshot.previous_version) == (
        "installed",
        "1.3.4.258",
        None,
    )


# (step, spotify-install's message, the phase it failed in, the contract's code)
ERRORS = [
    ("release", "download failed: https://x/InRelease: curl: (6)", "release", "network"),
    ("release", "InRelease signature check failed (BAD signature)", "release", "signature"),
    ("release", "InRelease doesn't list non-free/binary-amd64/Packages", "release", "unknown"),
    ("packages", "Packages: sha256 doesn't match", "packages", "checksum"),
    ("packages", "Packages: wrong size (10 bytes, expected 20)", "packages", "checksum"),
    ("packages", "no spotify-client 9.9 in the repository", "packages", "unknown"),
    ("space", "not enough free space in /config/spotify: 1 MB free", "download", "disk_full"),
    ("download", "download failed: curl: (56) Recv failure", "download", "network"),
    ("verify", "spotify-client_1.3.4.258_amd64.deb: sha256 doesn't match", "download", "checksum"),
    ("unpack", "unpacking failed: dpkg-deb: No space left on device", "unpack", "disk_full"),
    ("unpack", "unpacking failed: dpkg-deb: error: corrupted", "unpack", "unknown"),
    ("libraries", "Spotify 1.4 needs libraries (libfoo.so.1)", "libraries", "missing_libraries"),
    ("start", "run this as the app user, not root", None, "unknown"),
]  # fmt: skip


@pytest.mark.parametrize(("step", "message", "phase", "code"), ERRORS)
def test_errors_map_to_a_phase_and_a_code(
    step: str, message: str, phase: str | None, code: str
) -> None:
    tracker = InstallTracker(T0)
    update = tracker.apply(InstallProgress(stage="error", message=message, step=step), T0)
    snapshot = tracker.snapshot()
    assert update.finished
    assert snapshot.state == "failed"
    assert snapshot.phase == phase
    assert snapshot.error is not None
    assert (snapshot.error.code, snapshot.error.message) == (code, message)
    assert snapshot.log_tail == [message]
    assert_schema("ClientInstall", snapshot.model_dump(mode="json"))


def test_an_error_keeps_the_phase_it_failed_in_when_the_step_has_none() -> None:
    tracker = InstallTracker(T0)
    tracker.apply(InstallProgress(stage="unpack", message="Unpacking"), T0)
    tracker.apply(InstallProgress(stage="error", message="boom", step="mystery"), T0)
    assert tracker.snapshot().phase == "unpack"


def test_lines_after_the_last_are_ignored() -> None:
    tracker = InstallTracker(T0)
    tracker.apply(InstallProgress(stage="error", message="boom", step="release"), T0)
    update = tracker.apply(InstallProgress(stage="done", message="late", version="1"), T0)
    assert not update.finished and update.log_line is None
    assert tracker.snapshot().state == "failed"
    assert tracker.fail("unknown", "again", T0) is None


def test_stderr_lines_only_add_to_the_log() -> None:
    tracker = InstallTracker(T0)
    tracker.apply(InstallProgress(stage="switch", message="Switching"), T0)
    update = tracker.apply(InstallProgress(stage="log", message="mv: cannot move"), T0)
    assert (update.phase_changed, update.log_line, update.finished) == (
        False,
        "mv: cannot move",
        False,
    )
    assert tracker.snapshot().phase == "switch"


def test_the_log_tail_keeps_the_last_50_lines() -> None:
    tracker = InstallTracker(T0)
    for n in range(60):
        tracker.apply(InstallProgress(stage="log", message=f"line {n}"), T0)
    tail = tracker.snapshot().log_tail
    assert len(tail) == 50
    assert (tail[0], tail[-1]) == ("line 10", "line 59")


def test_fail_ends_the_attempt() -> None:
    tracker = InstallTracker(T0)
    tracker.apply(InstallProgress(stage="download", message="Downloading", percent=3), T0)
    assert tracker.fail("unknown", "The install was stopped.", T0) == "The install was stopped."
    snapshot = tracker.snapshot()
    assert (snapshot.state, snapshot.phase, snapshot.progress) == ("failed", "download", None)
    assert snapshot.error is not None and snapshot.error.code == "unknown"


def test_parse_install_line() -> None:
    assert parse_install_line("") is None
    assert parse_install_line("  \n") is None
    assert parse_install_line("mv: cannot move 'a' to 'b'") == InstallProgress(
        stage="log", message="mv: cannot move 'a' to 'b'"
    )
    assert parse_install_line('{"no":"stage"}') == InstallProgress(
        stage="log", message='{"no":"stage"}'
    )
    line = parse_install_line(
        '{"stage":"done","message":"Installed","version":"1.3.4.258","previous":"",'
        '"changed":true,"percent":true}\n'
    )
    assert line is not None
    assert (line.stage, line.version, line.previous, line.changed, line.percent) == (
        "done",
        "1.3.4.258",
        "",
        True,
        None,  # a boolean isn't a number
    )
    assert line.raw["changed"] is True
    error = parse_install_line('{"stage":"error","message":"x","step":"verify"}')
    assert error is not None and error.step == "verify"


# --- The table ----------------------------------------------------------------------------------


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[Store]:
    db = Store(tmp_path / "db" / "spotivault.db")
    await db.open()
    yield db
    await db.close()


async def test_attempts_are_stored_and_the_latest_is_loaded(store: Store) -> None:
    assert await install.load_latest(store) is None

    first = await install.insert_attempt(store, T0)
    tracker = InstallTracker(T0)
    for line in lines(*HAPPY[:2]):
        tracker.apply(line, T0)
    await install.save_phase(store, first, tracker.phase)
    for line in lines(*HAPPY[2:]):
        tracker.apply(line, T0 + timedelta(seconds=17))
    await install.save_finished(store, first, tracker)

    second = await install.insert_attempt(store, T0 + timedelta(hours=1))
    failed = InstallTracker(T0 + timedelta(hours=1))
    failed.apply(
        InstallProgress(stage="error", message="download failed: x", step="download"),
        T0 + timedelta(hours=1, seconds=3),
    )
    await install.save_finished(store, second, failed)

    rows = await store.fetchall(
        "SELECT id, state, phase, version, error_code, is_current FROM client_install ORDER BY id"
    )
    assert [tuple(row) for row in rows] == [
        (first, "installed", None, "1.3.4.258", None, 1),
        (second, "failed", "download", None, "network", 0),
    ]
    latest = await install.load_latest(store)
    assert latest is not None
    assert (latest.state, latest.phase, latest.log_tail) == ("failed", "download", [])
    assert latest.error is not None and latest.error.code == "network"
    assert latest.started_at == T0 + timedelta(hours=1)
    assert latest.finished_at == T0 + timedelta(hours=1, seconds=3)
    assert_schema("ClientInstall", latest.model_dump(mode="json"))


async def test_a_new_successful_install_becomes_the_current_one(store: Store) -> None:
    for version in ("1.3.4.258", "1.3.5.1"):
        attempt = await install.insert_attempt(store, T0)
        tracker = InstallTracker(T0)
        tracker.apply(InstallProgress(stage="done", message="ok", version=version), T0)
        await install.save_finished(store, attempt, tracker)
    current = await store.fetchall("SELECT version FROM client_install WHERE is_current = 1")
    assert [row["version"] for row in current] == ["1.3.5.1"]


async def test_interrupted_attempts_become_failed(store: Store) -> None:
    await install.insert_attempt(store, T0)
    assert await install.fail_interrupted(store, T0 + timedelta(minutes=1)) == 1
    latest = await install.load_latest(store)
    assert latest is not None and latest.state == "failed"
    assert latest.error is not None
    assert latest.error.message == "The controller stopped during the install."
    assert await install.fail_interrupted(store, T0) == 0


def test_installed_outside_and_not_started_match_the_contract() -> None:
    assert_schema("ClientInstall", install.not_started().model_dump(mode="json"))
    outside = install.installed_outside("1.3.4.258")
    assert (outside.state, outside.version) == ("installed", "1.3.4.258")
    assert_schema("ClientInstall", outside.model_dump(mode="json"))
