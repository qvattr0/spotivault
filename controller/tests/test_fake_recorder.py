"""fake/recorder.py: the simulated spytifyd behaves as FINDINGS.md and the bug log describe.

S6's simulator tests rely on these behaviours, so each one is pinned here: takes and their ids,
duplicates, the idle exit with its phantom take, already-playing tracks (bug 2), skip-forward
(bug 1), takeovers, pauses, low volume, SIGTERM and SIGKILL, capture problems, start errors,
the RPC methods, the naming settings and the files.
"""

import asyncio
import json
import stat
from pathlib import Path

import pytest

from fake_helpers import Notes, make_world, recorder_spec
from portcheck import assert_implements
from spotivault import ports
from spotivault.config import Config
from spotivault.fake import FakeWorld
from spotivault.fake.catalog import CatalogAlbum
from spotivault.fake.clock import FakeClock
from spotivault.fake.recorder import SimRecorder, SimRecorderSession, read_index
from spotivault.matching import track_key
from spotivault.ports import (
    RecorderGone,
    RecorderNotification,
    RecorderRpcError,
    RecorderStartError,
)
from spotivault.recorder.protocol import classify_exit

ZERO_COUNTERS = {"recorded": 0, "skipped": 0, "ads": 0, "bytes": 0, "overruns": 0}

ELSEWHERE = [
    ("Passage", 87_000),
    ("Distant Peak", 90_000),
    ("Now And Then", 102_000),
    ("Seaside Stillness", 93_000),
    ("Last Hours", 88_000),
]


@pytest.fixture
def world(config: Config, fake_clock: FakeClock) -> FakeWorld:
    return make_world(config, fake_clock)


@pytest.fixture
def album(world: FakeWorld) -> CatalogAlbum:
    return world.catalog.add_album("Elsewhere", artist="fakename", tracks=ELSEWHERE)


async def play(world: FakeWorld, album: CatalogAlbum, index: int) -> None:
    """PUT /me/player/play with the album and an offset by URI, as the engine does."""
    track = album.entries[index].track
    assert track is not None
    await world.webapi.play(
        device_id=world.catalog.our_device.id, context_uri=album.album.uri, offset_uri=track.uri
    )


def prerecord(world: FakeWorld, album: CatalogAlbum, positions: list[int]) -> None:
    """Puts these tracks in the music folder and Spytify's index, as an earlier run would."""
    music = world.config.music_dir
    index = music / ".spytify" / "recorded.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    with index.open("a", encoding="utf-8") as fh:
        for position in positions:
            title = ELSEWHERE[position][0]
            path = music / "fakename" / "Elsewhere" / f"{position + 1:02d} - {title}.m4a"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"recorded")
            key = track_key("fakename", title)
            fh.write(json.dumps({"Key": key, "Path": str(path)}) + "\n")


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


async def run_out(session: SimRecorderSession, clock: FakeClock, within: float = 900) -> int:
    await clock.advance_until(lambda: session.returncode is not None, within=within)
    return await session.wait()


def test_it_implements_the_ports() -> None:
    assert_implements(SimRecorder, ports.Recorder)
    assert_implements(SimRecorderSession, ports.RecorderSession)


async def test_an_album_records_and_the_last_take_finishes_at_the_idle_exit(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    spec = recorder_spec(tmp_path, world)
    session = await world.recorder.start(spec)
    notes = Notes(session)
    await play(world, album, 0)
    await fake_clock.advance_until(lambda: world.player.status == "Paused", within=600)
    paused_at = fake_clock.monotonic()
    assert await run_out(session, fake_clock) == 0
    exit_after = fake_clock.monotonic() - paused_at
    await notes.done()

    titles = [n["title"] for n in notes.of("track.started")]
    assert titles == [title for title, _ in ELSEWHERE] + ["Passage"]  # + the phantom
    phantom = notes.of("track.started")[-1]["id"]
    assert notes.of("track.skipped") == [
        {"id": phantom, "reason": "duplicate", "path": notes.of("track.finished")[0]["path"]}
    ]
    # track.finished has no title: it's matched to track.started by take id.
    started = {n["id"]: n["title"] for n in notes.of("track.started")}
    finished = notes.of("track.finished")
    assert [started[n["id"]] for n in finished] == [title for title, _ in ELSEWHERE]
    assert all("title" not in n for n in finished)
    assert finished[-1]["duration_ms"] == 88_000 - 1_100
    # Go's omitempty: the flags are left out when false.
    assert not any("low_volume" in n or "pause_fade" in n or "partial" in n for n in finished)
    assert all(n["tagged"] is True for n in finished)
    # The S0 run: the last take is saved and the process exits 20–27 s after the pause.
    assert 20 <= exit_after <= 30
    assert notes.summary()[-5:] == [
        ("session.state", "paused"),
        ("track.started", "Passage"),
        ("track.skipped", "duplicate"),
        ("session.state", "idle"),
        ("track.finished", "05 - Last Hours.m4a"),
    ]

    music = world.config.music_dir
    files = sorted(p.name for p in (music / "fakename" / "Elsewhere").iterdir())
    assert files == [f"{n:02d} - {title}.m4a" for n, (title, _) in enumerate(ELSEWHERE, 1)]
    first = music / "fakename" / "Elsewhere" / "01 - Passage.m4a"
    assert first.stat().st_size == finished[0]["bytes"] == (87_000 - 1_100) * 256 // 8
    assert set(read_index(music)) == {track_key("fakename", title) for title, _ in ELSEWHERE}
    # The --events file holds everything, the last track.finished included.
    lines = [json.loads(line) for line in spec.events_file.read_text().splitlines()]
    assert lines[-1]["method"] in ("track.finished", "log")
    assert sum(1 for line in lines if line["method"] == "track.finished") == 5
    assert [n.method for n in await session.events_file()] == [n.method for n in notes.items]
    assert "player idle for 20s, ending the session" in spec.log_file.read_text()
    assert world.mpris.calls == []  # Spytify pressed nothing: skip-forward is off


async def test_a_missing_tracks_run_as_findings_shows_it(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    """FINDINGS § Playing only the missing tracks, the "3, 5" run, steered as the engine does:
    play from the first missing track, jump over a recorded one, and let the album end."""
    prerecord(world, album, [0, 1, 3])
    session = await world.recorder.start(recorder_spec(tmp_path, world))

    async def steer(note: RecorderNotification) -> None:
        if note.method == "track.started" and note.params["title"] == "Seaside Stillness":
            await fake_clock.sleep(2)  # the engine looks the track up first
            await play(world, album, 4)

    notes = Notes(session, steer)
    await play(world, album, 2)
    assert await run_out(session, fake_clock) == 0
    await notes.done()

    assert notes.summary() == [
        ("session.state", "waiting"),
        ("track.started", "Now And Then"),
        ("session.state", "recording"),
        ("track.started", "Seaside Stillness"),
        ("track.skipped", "duplicate"),
        ("session.state", "waiting"),
        ("track.finished", "03 - Now And Then.m4a"),
        ("track.started", "Last Hours"),
        ("session.state", "recording"),
        ("session.state", "paused"),
        ("track.started", "Passage"),  # the album ended: the phantom at the idle exit
        ("track.skipped", "duplicate"),
        ("session.state", "idle"),
        ("track.finished", "05 - Last Hours.m4a"),
    ]
    assert world.mpris.calls == []  # 0 MPRIS calls from Spytify, as dbus-monitor saw
    assert world.player.status == "Paused" and world.player.index == 0


async def test_a_duplicate_with_skip_forward_presses_next(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    prerecord(world, album, [0])
    session = await world.recorder.start(recorder_spec(tmp_path, world, skip_forward=True))
    notes = Notes(session)
    await play(world, album, 0)
    await fake_clock.advance(0.4)
    assert world.player.index == 0
    await fake_clock.advance(0.2)
    assert world.player.index == 1 and world.player.status == "Playing"
    assert notes.summary()[1:4] == [
        ("track.started", "Passage"),
        ("track.skipped", "duplicate"),
        ("track.started", "Distant Peak"),
    ]
    await session.kill()


async def test_skip_forward_at_the_idle_exit_restarts_the_player(
    world: FakeWorld, fake_clock: FakeClock, tmp_path: Path
) -> None:
    """Bug 1, path 2: the phantom duplicate's Next lands as the recorder ends, so the player
    plays again after the item ended. The controller must pause it."""
    short = world.catalog.add_album(
        "Pair", artist="fakename", tracks=[("A", 30_000), ("B", 30_000)]
    )
    session = await world.recorder.start(recorder_spec(tmp_path, world, skip_forward=True))
    notes = Notes(session)
    await play(world, short, 0)
    assert await run_out(session, fake_clock) == 0
    await notes.done()
    assert ("track.skipped", "duplicate") in notes.summary()
    assert world.player.status == "Playing" and world.player.index == 1


async def test_the_live_album_end_race_replays_the_album(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    """Bug 1, live: track 1's metadata comes while Playing, so its duplicate is skipped forward
    and the whole album plays again, every track a duplicate (a whole item's loop guard)."""
    world.recorder.album_end_race = True
    prerecord(world, album, [0, 1, 2, 3])
    session = await world.recorder.start(recorder_spec(tmp_path, world, skip_forward=True))
    notes = Notes(session)
    await play(world, album, 4)
    await fake_clock.advance(88 + 6)
    titles = [n["title"] for n in notes.of("track.started")]
    assert titles[:2] == ["Last Hours", "Passage"]
    assert titles.count("Passage") >= 2  # round again: it could loop
    assert world.player.status == "Playing"
    await session.kill()


@pytest.mark.parametrize(
    ("paused_at_ms", "recorded"),
    [
        (0, True),  # the engine's seek to 0: it waits for Play, then records
        (200, True),  # within freshStartMs
        (980, False),  # bug 2: the restart lands within 2 s of where it paused, so it's missed
        (5_900, True),  # "started over"
    ],
)
async def test_a_track_the_player_is_paused_on(
    paused_at_ms: int,
    recorded: bool,
    world: FakeWorld,
    album: CatalogAlbum,
    fake_clock: FakeClock,
    tmp_path: Path,
) -> None:
    world.player.load(album.album.uri, index=4, position_ms=paused_at_ms)
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 4)  # the retry: an offset play of that same track
    assert await run_out(session, fake_clock) == 0
    await notes.done()
    titles = [n["title"] for n in notes.of("track.started")]
    assert ("Last Hours" in titles) is recorded
    already = [n for n in notes.of("log") if "already playing" in n["msg"]]
    assert bool(already) is (paused_at_ms > 300)


async def test_a_takeover_ends_the_session_with_the_take_incomplete(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 0)
    await fake_clock.advance(30)
    world.player.take_over("Pixel 9")
    took = await fake_clock.advance_until(lambda: session.returncode is not None, within=60)
    await notes.done()
    assert 20 <= took <= 21
    take = notes.of("track.started")[0]["id"]
    assert notes.of("track.skipped") == [{"id": take, "reason": "incomplete"}]
    assert notes.of("track.keepable") == [{"id": take, "keepable": True}]  # held for track.keep
    assert notes.of("track.finished") == []
    assert read_index(world.config.music_dir) == {}
    assert (world.config.music_dir / ".spytify" / f"{take}.wav").exists()  # bug 4


async def test_a_pause_inside_a_take_saves_it_with_pause_fade(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 4)
    await fake_clock.advance(30)
    await world.mpris.pause()
    await fake_clock.advance(10)  # under the 20 s idle exit
    await world.mpris.play()
    assert await run_out(session, fake_clock) == 0
    await notes.done()
    (finished,) = notes.of("track.finished")
    assert finished["pause_fade"] is True
    assert read_index(world.config.music_dir) == {}  # it doesn't count: the track stays missing


async def test_a_take_below_full_volume(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    world.player.set_volume(40)
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 4)
    await fake_clock.advance(1)
    assert notes.of("error")[0]["code"] == "player_volume_low"
    assert await session.call("player.control", {"cmd": "full_volume"}) == {}
    assert world.player.volume == 100
    await fake_clock.settle()
    assert notes.of("error")[0]["volume"] == 40
    assert notes.of("error")[-1] == {"code": "player_volume_low", "msg": "", "fatal": False}
    assert await run_out(session, fake_clock) == 0
    await notes.done()
    (finished,) = notes.of("track.finished")
    assert finished["low_volume"] is True
    assert finished["path"].endswith("05 - Last Hours (low volume).m4a")
    assert read_index(world.config.music_dir) == {}


async def test_sigterm_finishes_the_current_take_then_exits(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 0)
    await fake_clock.advance(70)
    stopping = asyncio.ensure_future(session.terminate())
    took = await fake_clock.advance_until(stopping.done, within=60)
    assert await stopping == 0 and took < 45
    await notes.done()
    assert [n["title"] for n in notes.of("track.started")] == ["Passage"]  # no next take
    assert len(notes.of("track.finished")) == 1
    assert ("session.state", "stopping") in notes.summary()


async def test_a_second_sigterm_holds_the_take_and_leaves_its_wav(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 0)
    await fake_clock.advance(10)
    stopping = asyncio.ensure_future(session.terminate(first_grace_s=5, second_grace_s=5))
    await fake_clock.advance_until(stopping.done, within=20)
    assert await stopping == 0 and session.sigterms == 2
    await notes.done()
    (held,) = notes.of("track.keepable")
    assert held == {"id": notes.of("track.started")[0]["id"], "keepable": True}
    assert notes.of("track.skipped") == [{"id": held["id"], "reason": "incomplete"}]
    wav = world.config.music_dir / ".spytify" / f"{held['id']}.wav"
    assert wav.exists()  # bug 4
    assert notes.of("track.finished") == []


async def test_track_keep_saves_a_held_take_as_partial(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 0)
    await fake_clock.advance(10)
    assert await session.call("session.stop", {"now": True}) == {"recorded": 0, "skipped": 0}
    take = notes.of("track.started")[0]["id"]
    await fake_clock.settle()
    assert await session.call("track.keep", {"id": take}) == {}
    with pytest.raises(RecorderRpcError) as gone:
        await session.call("track.keep", {"id": take})  # claimed already
    assert gone.value.code == -32006
    assert await run_out(session, fake_clock) == 0
    await notes.done()
    (finished,) = notes.of("track.finished")
    assert finished["partial"] is True and finished["path"].endswith("01 - Passage (partial).m4a")
    assert read_index(world.config.music_dir) == {}


async def test_sigterm_ignored_ends_in_sigkill(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    world.recorder.ignore_sigterm = True
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    await play(world, album, 0)
    stopping = asyncio.ensure_future(session.terminate(first_grace_s=1, second_grace_s=1))
    await fake_clock.advance_until(stopping.done, within=5)
    assert await stopping == -9 and session.returncode == -9


async def test_a_kill_while_encoding_leaves_a_part_file(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 0)
    await fake_clock.advance(88)  # Passage ended 1 s ago: it's being encoded
    assert await session.kill() == -9
    await notes.done()
    assert notes.of("track.finished") == []
    part = world.config.music_dir / "fakename" / "Elsewhere" / "01 - Passage.m4a.part"
    assert part.exists()  # bug 5
    with pytest.raises(RecorderGone):
        await session.call("core.info")


async def test_silent_capture_is_reported_and_withdrawn(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 0)
    world.recorder.set_capture("silent")
    await fake_clock.advance(9.9)
    assert notes.of("error") == []
    await fake_clock.advance(0.2)
    (error,) = notes.of("error")
    assert (error["code"], error["fatal"]) == ("capture_silent", False) and error["msg"]
    assert all(isinstance(value, str) for value in error["facts"].values())
    world.recorder.set_capture("ok")
    await fake_clock.settle()
    assert notes.of("error")[-1] == {"code": "capture_silent", "msg": "", "fatal": False}
    await fake_clock.advance(80)
    assert notes.of("track.skipped")[0]["reason"] == "silent"
    await session.kill()


async def test_a_stalled_capture_is_reported_and_the_session_carries_on(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    """2.0.2 reports capture_stalled (not fatal) and keeps the session: the controller ends the
    item (plan § Item states: capture_silent / capture_stalled → partial)."""
    world.recorder.set_capture("stalled")
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 0)
    await fake_clock.advance(10.1)
    (error,) = notes.of("error")
    assert (error["code"], error["fatal"]) == ("capture_stalled", False)
    await fake_clock.advance(80)  # Passage ends; Distant Peak starts
    assert session.returncode is None
    assert notes.of("track.skipped")[0]["reason"] == "incomplete"
    assert len(notes.of("error")) == 1  # reported once while it lasts
    await session.kill()


async def test_the_player_quitting_ends_the_session(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 0)
    await fake_clock.advance(5)
    world.client.crash()
    assert await run_out(session, fake_clock, within=5) == 0
    await notes.done()
    assert notes.of("track.skipped")[0]["reason"] == "incomplete"


@pytest.mark.parametrize(
    ("settings", "code"),
    [
        ([("encode.format", "ogg")], 2),
        ([("output.nonsense", "1")], 2),
        ([("output.template", "{nope}")], 2),  # unknown placeholders are dropped: none left
        ([("output.template", "a\\{title}")], 2),
        ([("encode.bitrate_kbps", "192")], 2),
        ([("recorder.duplicates", "keep")], 2),
    ],
)
async def test_a_bad_setting_exits_2(
    settings: list[tuple[str, str]], code: int, world: FakeWorld, tmp_path: Path
) -> None:
    with pytest.raises(RecorderStartError) as failed:
        await world.recorder.start(recorder_spec(tmp_path, world, settings=settings))
    assert failed.value.exit_code == code and failed.value.log_tail
    assert classify_exit(code, failed.value.log_tail).action == "fail_run"


async def test_an_output_folder_it_cant_write_exits_1(world: FakeWorld, tmp_path: Path) -> None:
    world.storage.set_state(world.config.music_dir, writable=False)
    with pytest.raises(RecorderStartError) as failed:
        await world.recorder.start(recorder_spec(tmp_path, world))
    assert failed.value.exit_code == 1
    verdict = classify_exit(1, failed.value.log_tail)
    assert (verdict.cause, verdict.action) == ("output_dir", "fail_run")


async def test_a_socket_in_use_exits_1(world: FakeWorld, tmp_path: Path) -> None:
    first = await world.recorder.start(recorder_spec(tmp_path, world))
    with pytest.raises(RecorderStartError) as failed:
        await world.recorder.start(recorder_spec(tmp_path, world))
    assert failed.value.exit_code == 1
    verdict = classify_exit(1, failed.value.log_tail)
    assert (verdict.cause, verdict.action) == ("socket_in_use", "retry_once")
    await first.kill()
    second = await world.recorder.start(recorder_spec(tmp_path, world))  # free again
    await second.kill()


async def test_a_start_failure_can_be_injected(world: FakeWorld, tmp_path: Path) -> None:
    world.recorder.start_failure = RecorderStartError("ffmpeg missing", exit_code=1)
    with pytest.raises(RecorderStartError):
        await world.recorder.start(recorder_spec(tmp_path, world))
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    await session.kill()
    assert len(world.recorder.started) == 2


async def test_with_no_player_it_waits_for_the_target_then_exits_1(
    world: FakeWorld, fake_clock: FakeClock, tmp_path: Path
) -> None:
    world.client.stop()
    starting = asyncio.ensure_future(world.recorder.start(recorder_spec(tmp_path, world)))
    took = await fake_clock.advance_until(starting.done, within=120)
    with pytest.raises(RecorderStartError) as failed:
        await starting
    assert failed.value.exit_code == 1 and took == 60
    verdict = classify_exit(1, failed.value.log_tail)
    assert (verdict.cause, verdict.action) == ("no_player", "fail_item")
    assert world.recorder.sessions[-1].returncode == 1


async def test_start_waits_for_the_player_within_wait_target(
    world: FakeWorld, fake_clock: FakeClock, tmp_path: Path
) -> None:
    world.client.stop()
    starting = asyncio.ensure_future(world.recorder.start(recorder_spec(tmp_path, world)))
    await fake_clock.advance(5)
    assert not starting.done()
    status = await world.recorder.sessions[-1].call("session.status")
    assert status == {"state": "idle", "counters": ZERO_COUNTERS}  # no session yet
    world.client.start()
    await fake_clock.settle()
    session = await starting
    status = await session.call("session.status")
    assert status["state"] == "waiting" and status["session_id"]
    await session.kill()


async def test_the_rpc_methods(world: FakeWorld, fake_clock: FakeClock, tmp_path: Path) -> None:
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    info = await session.call("core.info")
    assert info["version"] == "v2.0.2" and info["protocol"] == 1
    assert info["target"] == {"process": "spotify", "mpris": "org.mpris.MediaPlayer2.spotify"}
    assert [check["id"] for check in info["checks"]] == [
        "target",
        "player_running",
        "ffmpeg",
        "encoder",
        "capture",
        "session_bus",
        "player_heard",
        "output_writable",
    ]  # FINDINGS row 5: all 8 pass
    assert all(check["ok"] for check in info["checks"])
    with pytest.raises(RecorderRpcError) as refused:
        await session.call("player.control", {"cmd": "pause"})  # nothing loaded
    assert refused.value.code == -32005
    with pytest.raises(RecorderRpcError) as bad_cmd:
        await session.call("player.control", {"cmd": "stop"})
    assert bad_cmd.value.code == -32602
    with pytest.raises(RecorderRpcError) as unknown:
        await session.call("nope")
    assert unknown.value.code == -32601
    with pytest.raises(RecorderRpcError) as active:
        await session.call("session.start")
    assert active.value.code == -32003
    result = await session.call(
        "settings.set", {"values": {"recorder.silence_db": -55, "encode.format": "ogg"}}
    )
    assert result == {
        "applied": ["recorder.silence_db"],
        "rejected": {"encode.format": "expected one of mp3, aac, flac, wav"},
    }
    assert world.recorder.persisted_settings == {"recorder.silence_db": -55.0}
    values = (await session.call("settings.get", {"keys": ["encode.format", "output.playlist"]}))[
        "values"
    ]
    assert values == {"encode.format": "aac", "output.playlist": False}  # typed, as Spytify's
    with pytest.raises(RecorderRpcError) as unknown_key:
        await session.call("settings.get", {"keys": ["nope"]})
    assert unknown_key.value.code == -32602
    status = await session.call("session.status")
    assert status == {
        "state": "waiting",
        "session_id": session.session_id,
        "counters": ZERO_COUNTERS,
    }
    log = await session.call("log.tail", {"lines": 1})
    assert len(log["lines"]) == 1 and set(log["lines"][0]) == {"level", "msg", "ts"}
    recent = await session.call("events.recent")
    assert all(set(event) == {"method", "params"} for event in recent["events"])
    world.recorder.hang_methods = {"core.info"}
    answer = asyncio.ensure_future(session.call("core.info", timeout_s=3))
    await fake_clock.settle()
    await fake_clock.advance(3)
    with pytest.raises(TimeoutError):
        await answer
    world.recorder.hang_methods = set()
    assert await session.call("core.shutdown") == {}
    assert await run_out(session, fake_clock, within=5) == 0
    with pytest.raises(RecorderGone):
        await session.call("session.status")
    await notes.done()
    assert notes.of("settings.changed") == [{"values": {"recorder.silence_db": -55.0}}]
    assert world.recorder.live() is None


async def test_the_events_file_is_spytifyds_format(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    spec = recorder_spec(tmp_path, world)
    session = await world.recorder.start(spec)
    await play(world, album, 4)
    await run_out(session, fake_clock)
    lines = [json.loads(line) for line in spec.events_file.read_text().splitlines()]
    assert lines and all(set(line) == {"method", "params"} for line in lines)  # proto.Event
    levels = {line["params"]["level"] for line in lines if line["method"] == "log"}
    assert levels <= {"error", "info", "debug"}
    for text in spec.log_file.read_text().splitlines():
        stamp, level, _ = text.split(" ", 2)
        assert stamp.endswith("Z") and level in ("error", "info", "debug")


async def test_the_counter_prefix_moves_on_and_is_saved(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    settings = [("output.template", "{title}"), ("output.prefix", "counter")]
    session = await world.recorder.start(recorder_spec(tmp_path, world, settings=settings))
    notes = Notes(session)
    await play(world, album, 3)
    await run_out(session, fake_clock)
    await notes.done()
    assert [Path(n["path"]).name for n in notes.of("track.finished")] == [
        "001 Seaside Stillness.m4a",
        "002 Last Hours.m4a",
    ]
    assert [n["counter"] for n in notes.of("track.finished")] == [1, 2]
    assert notes.of("settings.changed")[-1] == {"values": {"output.counter_next": 3}}
    assert world.recorder.counter_next == 3  # in $SPYTIFY_CONFIG: the next item goes on


async def test_level_notifications_only_while_recording(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    world.recorder.level_interval_s = 0.1
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 0)
    await fake_clock.advance(1.05)
    levels = notes.of("level")
    assert len(levels) == 10
    assert levels[0]["peak_dbfs"] < 0 and len(levels[0]["channels"]) == 2
    await world.mpris.pause()
    await fake_clock.advance(2)
    assert len(notes.of("level")) == 10
    await session.kill()


async def test_level_notifications_are_sent_but_not_kept(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    """The meter goes to the socket only. Kept, a 3-hour item's 100,000 level records were
    written in place at the exit and blocked the loop for 0.5 s in fake mode; the real port's
    events_file() leaves them out too."""
    world.recorder.level_interval_s = 0.1
    spec = recorder_spec(tmp_path, world)
    session = await world.recorder.start(spec)
    notes = Notes(session)
    await play(world, album, 4)  # Last Hours: 88 s
    assert await run_out(session, fake_clock) == 0
    await notes.done()
    assert len(notes.of("level")) > 800
    assert session.levels_sent == len(notes.of("level"))
    kept = [n.method for n in await session.events_file()]
    assert "level" not in kept and "track.finished" in kept
    lines = [json.loads(line) for line in spec.events_file.read_text().splitlines()]
    assert [line["method"] for line in lines] == kept


async def test_the_socket_can_lose_the_last_notifications(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    world.recorder.lose_final_notifications = True
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 4)
    assert await run_out(session, fake_clock) == 0
    await notes.done()
    assert notes.of("track.finished") == []
    assert [n.method for n in await session.events_file()].count("track.finished") == 1


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ([], "fakename/Elsewhere/05 - Last Hours.m4a"),
        (
            [("output.group_by", "none"), ("output.template", "{artists} - {title}")],
            "fakename - Last Hours.m4a",
        ),
        (
            [("output.group_by", "artist"), ("output.template", "{title}")]
            + [("output.prefix", "counter")],
            "fakename/001 Last Hours.m4a",
        ),
        (
            [("output.template", "{title}"), ("output.prefix", "album_track")],
            "fakename/Elsewhere/05 Last Hours.m4a",
        ),
        ([("output.underscores", "true")], "fakename/Elsewhere/05_-_Last_Hours.m4a"),
        (
            [("encode.format", "mp3"), ("encode.bitrate_kbps", "320")],
            "fakename/Elsewhere/05 - Last Hours.mp3",
        ),
    ],
)
async def test_files_are_named_by_the_layout_settings(
    settings: list[tuple[str, str]],
    expected: str,
    world: FakeWorld,
    album: CatalogAlbum,
    fake_clock: FakeClock,
    tmp_path: Path,
) -> None:
    session = await world.recorder.start(recorder_spec(tmp_path, world, settings=settings))
    notes = Notes(session)
    await play(world, album, 4)
    await run_out(session, fake_clock)
    await notes.done()
    (finished,) = notes.of("track.finished")
    assert Path(finished["path"]).relative_to(world.config.music_dir).as_posix() == expected


async def test_accents_can_be_stripped_and_umask_applies(
    world: FakeWorld, fake_clock: FakeClock, tmp_path: Path
) -> None:
    single = world.catalog.add_album(
        "Été", artist="Erik Satie", tracks=[("Gymnopédie: No. 1", 30_000)]
    )
    spec = recorder_spec(
        tmp_path, world, settings=[("output.ascii_filenames", "true")], umask=0o027
    )
    session = await world.recorder.start(spec)
    notes = Notes(session)
    await play(world, single, 0)
    await run_out(session, fake_clock)
    await notes.done()
    path = Path(notes.of("track.finished")[0]["path"])
    assert (
        path.relative_to(world.config.music_dir).as_posix()
        == "Erik Satie/Ete/01 - Gymnopedie No. 1.m4a"
    )
    assert mode(path) == 0o640
    assert mode(path.parent) == 0o750


async def test_kill_orphans(world: FakeWorld) -> None:
    world.recorder.orphans = 2
    assert await world.recorder.kill_orphans() == 2
    assert await world.recorder.kill_orphans() == 0
    assert await world.recorder.version() == "2.0.2"


async def test_a_one_track_album_is_saved_at_the_idle_exit_with_no_phantom(
    world: FakeWorld, fake_clock: FakeClock, tmp_path: Path
) -> None:
    """FINDINGS row 11, "Panspermia": paused at the end, saved 20 s later, then the exit."""
    single = world.catalog.add_album("Panspermia", artist="Ozoyo", tracks=[("Panspermia", 188_000)])
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, single, 0)
    assert await run_out(session, fake_clock) == 0
    await notes.done()
    assert notes.summary() == [
        ("session.state", "waiting"),
        ("track.started", "Panspermia"),
        ("session.state", "recording"),
        ("session.state", "paused"),
        ("session.state", "idle"),
        ("track.finished", "01 - Panspermia.m4a"),
    ]


async def test_a_jump_inside_a_take_spoils_it(
    world: FakeWorld, album: CatalogAlbum, fake_clock: FakeClock, tmp_path: Path
) -> None:
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await play(world, album, 0)
    await fake_clock.advance(10)
    world.player.seek_to(50_000)  # the user drags the slider forward
    await fake_clock.advance(40)
    await fake_clock.settle()
    assert notes.of("track.skipped")[0]["reason"] == "seeked"
    await session.kill()
