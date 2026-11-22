"""client/manager.py: `ClientManager` on stand-in client and MPRIS ports (tests/client_stubs.py)
and the fake clock. Each test sets exactly the client it needs."""

import asyncio
import dataclasses
from typing import Any

import pytest

from client_stubs import (
    GOOD_PREFS,
    HAPPY,
    LOGGED_IN,
    StubClient,
    StubMpris,
    eventually,
    progress,
    record_events,
    run_install,
    started,
    use_stubs,
)
from contract import assert_schema
from spotivault.client.manager import STATUS_POLL_S
from spotivault.clock import iso_ms
from spotivault.config import Config
from spotivault.errors import ApiError
from spotivault.fake.clock import FakeClock
from spotivault.ports import InstallInProgress, LoginSignals
from spotivault.services import Services, build_services
from spotivault.store import Store


@pytest.fixture
def stubs(services: Services, fake_clock: FakeClock) -> tuple[StubClient, StubMpris]:
    return use_stubs(services, fake_clock)


# --- Status ---------------------------------------------------------------------------------------


async def test_status_follows_the_client(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    client, mpris = stubs
    events = record_events(services)
    async with started(services, fake_clock):
        status = await services.client.status()
        assert_schema("ClientStatus", status.model_dump(mode="json"))
        assert (status.installed, status.running, status.logged_in) == (False, False, False)
        assert status.install.state == "not_started"
        assert status.device_name == "spotivault-test"
        assert events == []  # the first reading isn't a change

        client.version, client.running, mpris.present = "1.3.4.258", True, True
        client.signals = LoginSignals(user_folder=False, window_title="Spotify")
        await fake_clock.advance(STATUS_POLL_S)
        assert [e.type for e in events] == ["client.status"]
        assert_schema("ClientStatus", events[-1].data)
        assert events[-1].data["login_signals"] == {
            "mpris": True,
            "user_folder": False,
            "window_title": "Spotify",
        }
        assert events[-1].data["logged_in"] is False  # MPRIS is no login signal (Q2)

        client.signals = LoginSignals(user_folder=True, window_title="Spotify")
        await fake_clock.advance(STATUS_POLL_S)
        assert events[-1].data["logged_in"] is False  # still the login screen's title
        assert len(events) == 2  # the user folder appeared: a signal changed

        client.signals = LOGGED_IN
        await fake_clock.advance(STATUS_POLL_S)
        assert events[-1].data["logged_in"] is True
        await fake_clock.advance(STATUS_POLL_S)
        assert len(events) == 3  # nothing changed, nothing sent

        client.signals = LoginSignals(user_folder=True, window_title="Band - Song")
        await fake_clock.advance(STATUS_POLL_S)
        assert len(events) == 3  # the title changes with every track: still logged in


async def test_a_failing_signal_reads_as_its_fallback_and_is_logged_once(
    services: Services,
    fake_clock: FakeClock,
    stubs: tuple[StubClient, StubMpris],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = stubs
    client.version = "1.3.4.258"
    client.fail_running = OSError("no /proc")
    async with started(services, fake_clock):
        await fake_clock.advance(STATUS_POLL_S * 3)
        status = await services.client.status()
        assert (status.installed, status.running) == (True, False)
    failures = [r for r in caplog.records if "reading process failed" in r.getMessage()]
    assert len(failures) == 1


async def test_hello_carries_the_status(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    client, _ = stubs
    client.version, client.running, client.signals = "1.3.4.258", True, LOGGED_IN
    async with started(services, fake_clock):
        hello = await services.bus.snapshot()
    assert_schema("ClientStatus", hello["client"])
    assert hello["client"]["logged_in"] is True


async def test_a_run_makes_the_client_not_restartable(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    client, _ = stubs
    events = record_events(services)
    async with started(services, fake_clock):
        await services.client.set_run_active(True)
        assert [e.data["restartable"] for e in events] == [False]
        with pytest.raises(ApiError) as refused:
            await services.client.restart()
        assert (refused.value.status, refused.value.code) == (409, "run_active")
        with pytest.raises(ApiError) as refused:
            await services.client.start_install()
        assert (refused.value.status, refused.value.code) == (409, "run_active")
        await services.client.set_run_active(False)
        assert [e.data["restartable"] for e in events] == [False, True]
    assert (client.restarts, client.installs) == (0, 0)


async def test_restart_runs_in_the_background(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    client, _ = stubs
    client.version, client.running = "1.3.4.258", True
    async with started(services, fake_clock):
        status = await services.client.restart()
        assert status.running and status.restartable
        await fake_clock.settle()
        assert client.restarts == 1


async def test_listeners_hear_status_changes(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    client, _ = stubs
    heard: list[bool] = []

    async def listener() -> None:
        heard.append((await services.client.status()).logged_in)

    async def broken() -> None:
        raise RuntimeError("a listener's bug")

    services.client.add_listener(broken)
    services.client.add_listener(listener)
    async with started(services, fake_clock):
        # The first checklist reading since start-up notifies too, and the setup module takes one
        # in the background after the status change. It's taken here first, so only the status
        # change is heard, however soon the setup module's reading comes.
        await services.client.checklist()
        heard.clear()
        client.version, client.running, client.signals = "1", True, LOGGED_IN
        await fake_clock.advance(STATUS_POLL_S)
    assert heard == [True]


# --- Install -------------------------------------------------------------------------------------


async def test_an_install_from_start_to_finish(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    client, _ = stubs
    events = record_events(services)
    async with started(services, fake_clock):
        accepted = await services.client.start_install()
        assert accepted.state == "installing"
        assert_schema("ClientInstall", accepted.model_dump(mode="json"))
        assert services.client.installing
        assert [e.type for e in events] == ["client.install", "client.status"]
        assert events[1].data["install"]["state"] == "installing"

        with pytest.raises(ApiError) as refused:
            await services.client.start_install()
        assert (refused.value.status, refused.value.code) == (409, "install_in_progress")

        for line in HAPPY:
            await fake_clock.advance(1)
            await client.send(line)
        await eventually(lambda: not services.client.installing)
        await eventually(lambda: events[-1].type == "client.status")

    installs = [e.data for e in events if e.type == "client.install"]
    for data in installs:
        log_line = data.pop("log_line")
        assert log_line is None or isinstance(log_line, str)
        assert_schema("ClientInstall", data)
    assert [(d["state"], d["phase"]) for d in installs] == [
        ("installing", None),
        ("installing", "release"),
        ("installing", "download"),
        ("installing", "download"),  # 50 %: the same message, but a second later
        ("installing", "download"),  # "Downloaded"
        ("installing", "download"),  # verify
        ("installing", "unpack"),
        ("installing", "libraries"),
        ("installing", "switch"),
        ("installed", None),
    ]
    final = installs[-1]
    assert (final["version"], final["error"], final["finished_at"]) == (
        "1.3.4.258",
        None,
        "2026-11-15T00:00:09Z",
    )
    assert final["log_tail"][-1] == "Installed Spotify 1.3.4.258"

    statuses = [e.data for e in events if e.type == "client.status"]
    assert (statuses[-1]["installed"], statuses[-1]["version"]) == (True, "1.3.4.258")
    assert statuses[-1]["install"]["state"] == "installed"

    row = await _latest_row(services)
    assert (row["state"], row["phase"], row["version"], row["is_current"]) == (
        "installed",
        None,
        "1.3.4.258",
        1,
    )


async def test_the_result_shows_only_once_it_is_saved(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    # events.md: publish after the commit. Between spotify-install's last line and its exit, the
    # status poll and GET /api/health must both still see the install running.
    client, _ = stubs
    client.output_after_result = True
    events = record_events(services)
    async with started(services, fake_clock):
        await services.client.start_install()
        for line in HAPPY:
            await fake_clock.advance(1)
            await client.send(line)
        await fake_clock.advance(1)  # a progress event would be due by now
        await client.send(progress("log", "a line after the result"))
        status = await services.client.refresh()
        assert status.installed  # the client's files are there...
        assert status.install.state == "installing"  # ...but the attempt isn't saved yet
        assert services.client.installing
        assert (await _latest_row(services))["state"] == "installing"
        sent = [e.data for e in events if e.type == "client.install"]
        assert {d["state"] for d in sent} == {"installing"}
        assert "a line after the result" not in {d["log_line"] for d in sent}

        await client.send(None)  # the script exits
        await eventually(lambda: not services.client.installing)
        assert (await _latest_row(services))["state"] == "installed"
        assert (await services.client.status()).install.state == "installed"
        await eventually(lambda: events[-1].type == "client.status")
    installs = [e.data for e in events if e.type == "client.install"]
    assert installs[-1]["state"] == "installed"
    assert installs[-1]["log_line"] == "Installed Spotify 1.3.4.258"
    statuses = [e.data for e in events if e.type == "client.status"]
    assert [s["install"]["state"] for s in statuses] == ["installing", "installing", "installed"]


async def test_download_progress_is_sent_at_most_twice_a_second(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    client, _ = stubs
    lines = [
        progress("download", "Downloading", percent=p, bytes=p, total=100) for p in range(0, 21)
    ] + [progress("error", "download failed: reset", step="download")]
    events = record_events(services)
    async with started(services, fake_clock):
        await services.client.start_install()
        for line in lines:
            await fake_clock.advance(0.125)  # exact in binary, so the clock's sums are too
            await client.send(line)
        await eventually(lambda: not services.client.installing)
    sent = [e.data for e in events if e.type == "client.install"]
    downloads = [d for d in sent if d["state"] == "installing" and d["phase"] == "download"]
    # 2.5 s of downloading: the first line, then one every 0.5 s (every 4th line).
    assert [d["bytes_done"] for d in downloads] == [0, 4, 8, 12, 16, 20]
    assert sent[-1]["state"] == "failed"
    assert sent[-1]["error"] == {"code": "network", "message": "download failed: reset"}


async def test_a_failed_install_is_stored_and_can_be_retried(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    client, _ = stubs
    failing = [
        progress("release", "Checking"),
        progress("error", "InRelease signature check failed", step="release"),
    ]
    async with started(services, fake_clock):
        await services.client.start_install()
        await run_install(services, client, failing)
        status = await services.client.status()
        assert status.install.state == "failed"
        assert status.install.error is not None
        assert status.install.error.code == "signature"
        assert status.install.log_tail == ["Checking", "InRelease signature check failed"]

        await services.client.start_install()
        await run_install(services, client, HAPPY)
        assert (await services.client.status()).install.state == "installed"
    rows = await _rows(services)
    assert [(r["state"], r["error_code"], r["is_current"]) for r in rows] == [
        ("failed", "signature", 0),
        ("installed", None, 1),
    ]


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ("lock", "another spotify-install is running: an install started outside the controller."),
        ("crash", "The install failed: boom"),
        ("no_result", "spotify-install stopped without a result."),
    ],
)
async def test_installs_that_end_badly_are_failed(
    services: Services,
    fake_clock: FakeClock,
    stubs: tuple[StubClient, StubMpris],
    setup: str,
    message: str,
) -> None:
    client, _ = stubs
    if setup == "lock":
        client.raise_at_start = InstallInProgress("another spotify-install is running")
    elif setup == "crash":
        client.raise_at_start = RuntimeError("boom")
    async with started(services, fake_clock):
        await services.client.start_install()
        if setup == "no_result":
            await client.send(progress("release", "Checking"), None)  # then the output ends
        await eventually(lambda: not services.client.installing)
        install = (await services.client.status()).install
    assert install.state == "failed"
    assert install.error is not None
    assert (install.error.code, install.error.message) == ("unknown", message)
    assert not services.client.installing


async def test_shutdown_stops_a_running_install(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    client, _ = stubs
    events = record_events(services)
    async with started(services, fake_clock):
        await services.client.start_install()
        await client.send(*HAPPY[:2])  # in the middle of the download
    assert client.closed_early  # the install generator was closed, so the script is stopped
    last = [e.data for e in events if e.type == "client.install"][-1]
    assert last["state"] == "failed"
    assert last["error"]["message"] == "The install was stopped: the controller shut down."
    assert last["log_line"] == "The install was stopped: the controller shut down."


async def test_an_install_cut_short_by_a_crash_is_failed_at_the_next_start(
    config: Config, fake_clock: FakeClock
) -> None:
    store = Store(config.db_path)
    await store.open()
    await store.execute(
        "INSERT INTO client_install (started_at, state, phase) VALUES (?, 'installing', 'unpack')",
        (iso_ms(fake_clock.now()),),
    )
    await store.close()

    services = await asyncio.to_thread(build_services, config, clock=fake_clock)
    use_stubs(services, fake_clock)
    async with started(services, fake_clock):
        install = (await services.client.status()).install
    assert (install.state, install.phase) == ("failed", "unpack")
    assert install.error is not None
    assert install.error.message == "The controller stopped during the install."


async def test_a_client_installed_by_hand_shows_as_installed(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    client, _ = stubs
    client.version = "1.3.4.258"
    async with started(services, fake_clock):
        install = (await services.client.status()).install
    assert (install.state, install.version, install.started_at) == ("installed", "1.3.4.258", None)


@pytest.fixture
def real_mode_services(config: Config, fake_clock: FakeClock) -> Services:
    """Services as in the container (not fake mode), still on fake ports and the fake clock."""
    services = build_services(config, clock=fake_clock)
    services.client.config = dataclasses.replace(config, fake=False)
    return services


async def test_the_first_start_installs_a_missing_client(
    real_mode_services: Services, fake_clock: FakeClock
) -> None:
    services = real_mode_services
    client, _ = use_stubs(services, fake_clock)
    async with started(services, fake_clock):
        assert services.client.installing
        await run_install(services, client, HAPPY)
        assert (await services.client.refresh()).installed
    assert client.installs == 1


async def test_the_first_start_leaves_an_installed_client_alone(
    real_mode_services: Services, fake_clock: FakeClock
) -> None:
    services = real_mode_services
    client, _ = use_stubs(services, fake_clock)
    client.version = "1.3.4.258"
    async with started(services, fake_clock):
        assert not services.client.installing
    assert client.installs == 0


async def test_fake_mode_installs_only_when_asked(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    client, _ = stubs
    async with started(services, fake_clock):
        await fake_clock.advance(STATUS_POLL_S)
        assert not services.client.installing
    assert client.installs == 0


# --- Checklist ------------------------------------------------------------------------------------


async def test_the_checklist_reads_prefs_and_keeps_ticks(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    client, _ = stubs
    heard: list[str] = []

    async def listener() -> None:
        heard.append("changed")

    services.client.add_listener(listener)
    async with started(services, fake_clock):
        checklist = await services.client.checklist()
        assert_schema("Checklist", checklist.model_dump(mode="json"))
        assert not checklist.ready
        assert {r.state for r in checklist.rows if r.check == "auto"} == {"unknown"}

        client.prefs_values = dict(GOOD_PREFS)
        checklist = await services.client.confirm({"crossfade": True, "gapless": True})
        assert checklist.ready
        assert heard  # a confirm, and `ready` turning true, tell the listeners

        first = await _checklist_rows(services)
        assert first["crossfade"]["confirmed_at"] == "2026-11-15T00:00:00.000Z"
        assert first["automix"]["state"] == "ok"

        await fake_clock.advance(60)
        await services.client.confirm({"crossfade": True, "autoplay": True})
        again = await _checklist_rows(services)
        assert again["crossfade"]["confirmed_at"] == "2026-11-15T00:00:00.000Z"  # the first tick
        assert again["autoplay"]["confirmed_at"] == "2026-11-15T00:01:00.000Z"

        checklist = await services.client.confirm({"gapless": False})
        assert not checklist.ready
        client.prefs_values = {**GOOD_PREFS, "audio.equalizer_v2": "true"}
        assert [r.id for r in await services.client.drifted_rows()] == ["equalizer"]


async def test_the_first_reading_after_a_restart_tells_the_listeners(
    config: Config, fake_clock: FakeClock
) -> None:
    # Ticked before the restart; the last Auto row was fixed while the controller was down.
    before = await asyncio.to_thread(build_services, config, clock=fake_clock)
    use_stubs(before, fake_clock)
    async with started(before, fake_clock):
        await before.client.confirm({"crossfade": True, "gapless": True})

    services = await asyncio.to_thread(build_services, config, clock=fake_clock)
    client, _ = use_stubs(services, fake_clock)
    heard: list[str] = []

    async def listener() -> None:
        heard.append("changed")

    services.client.add_listener(listener)
    async with started(services, fake_clock):
        heard.clear()  # whatever start-up itself reported
        client.prefs_values = dict(GOOD_PREFS)
        assert (await services.client.checklist()).ready
        assert heard == ["changed"]  # the first reading since start-up, and it's ready
        assert (await services.client.checklist()).ready
        assert heard == ["changed"]  # no change since


async def test_only_confirm_rows_can_be_ticked(
    services: Services, fake_clock: FakeClock, stubs: tuple[StubClient, StubMpris]
) -> None:
    async with started(services, fake_clock):
        with pytest.raises(ApiError) as refused:
            await services.client.confirm({"crossfade": True, "equalizer": True})
        assert (refused.value.status, refused.value.code) == (422, "validation_failed")
        assert refused.value.details == {"field": "rows.equalizer"}
        rows = await _checklist_rows(services)
        assert rows["crossfade"]["confirmed_at"] is None  # nothing was changed


async def test_ticks_survive_a_restart(config: Config, fake_clock: FakeClock) -> None:
    for expected in (False, True):
        services = await asyncio.to_thread(build_services, config, clock=fake_clock)
        use_stubs(services, fake_clock)
        async with started(services, fake_clock):
            checklist = await services.client.checklist()
            ticked = {r.id: r.confirmed for r in checklist.rows if r.check == "confirm"}
            assert ticked["crossfade"] is expected
            await services.client.confirm({"crossfade": True})


# --- Helpers -------------------------------------------------------------------------------------


async def _rows(services: Services) -> list[Any]:
    store = Store(services.config.db_path)
    await store.open()
    try:
        return await store.fetchall("SELECT * FROM client_install ORDER BY id")
    finally:
        await store.close()


async def _latest_row(services: Services) -> Any:
    return (await _rows(services))[-1]


async def _checklist_rows(services: Services) -> dict[str, Any]:
    rows = await services.store.fetchall("SELECT * FROM checklist")
    return {row["row_id"]: dict(row) for row in rows}
