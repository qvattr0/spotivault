"""recorder/protocol.py and the fake recorder against Spytify 2.0.2's own protocol schema.

tests/spytify/proto-2.0.2.schema.json is `pkg/proto/schema.json` from Spytify at tag 2.0.2
(commit fef3f4e, MIT licence), unchanged. Validation here is stricter than the schema: an object
may hold only the properties the schema lists (Go marshals nothing else), so a payload with a
made-up field fails. Every notification the fake sends in a few FINDINGS scenarios, and every RPC
result, must pass, so the fake speaks exactly what the real spytifyd speaks.
"""

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from fake_helpers import Notes, make_world, recorder_spec
from spotivault.config import Config
from spotivault.fake import FakeWorld
from spotivault.fake.clock import FakeClock
from spotivault.ports import RecorderNotification, RecorderRpcError
from spotivault.recorder import protocol as sp

SCHEMA_FILE = Path(__file__).parent / "spytify" / "proto-2.0.2.schema.json"
SCHEMA: dict[str, Any] = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def _strict(node: Any) -> Any:
    """The schema with `additionalProperties: false` on every object that lists properties."""
    if isinstance(node, dict):
        out = {key: _strict(value) for key, value in node.items()}
        if out.get("type") == "object" and "properties" in out:
            out.setdefault("additionalProperties", False)
        return out
    if isinstance(node, list):
        return [_strict(value) for value in node]
    return node


STRICT_DEFS = _strict(copy.deepcopy(SCHEMA["$defs"]))


def validate(ref: dict[str, Any], value: Any) -> None:
    schema = {"$defs": STRICT_DEFS, **ref}
    Draft202012Validator(schema).validate(value)


def validate_event(method: str, params: Any) -> None:
    validate(SCHEMA["events"][method]["params"], params)


def validate_result(method: str, result: Any) -> None:
    validate(SCHEMA["methods"][method]["result"], result)


# --- protocol.py itself ------------------------------------------------------------------------


def test_the_method_and_event_names_are_the_schemas() -> None:
    assert SCHEMA["protocol"] == sp.PROTOCOL
    assert set(sp.METHODS) == set(SCHEMA["methods"])
    assert set(sp.EVENTS) == set(SCHEMA["events"])


SAMPLES: list[tuple[str, Any]] = [
    (
        "track.started",
        sp.TrackStarted(
            id="20261115-000000-001",
            artist="fakename",
            title="Passage",
            length_ms=87_000,
            album="Elsewhere",
            cover_url="https://i.scdn.co/image/x",
            source=sp.AudioSource(44_100, 2),
            cut=sp.TrackCut("first", "first_sound", 0),
        ),
    ),
    ("track.started", sp.TrackStarted(id="t", artist="", title="", length_ms=0)),
    (
        "track.finished",
        sp.TrackFinished(
            id="t",
            path="/music/a.m4a",
            duration_ms=1,
            bytes=2,
            tagged=True,
            counter=4,
            tagged_by="player",
            timings=sp.FinishTimings("aac", 1, 2, 3, 4, 10),
            partial=True,
            pause_fade=True,
            low_volume=True,
        ),
    ),
    ("track.finished", sp.TrackFinished(id="t", path="/m", duration_ms=0, bytes=0, tagged=False)),
    ("track.skipped", sp.TrackSkipped(id="t", reason="duplicate", path="/m/a.m4a")),
    ("track.skipped", sp.TrackSkipped(id="t", reason="duplicate", of="t0")),
    ("track.skipped", sp.TrackSkipped(id="t", reason="incomplete")),
    ("track.keepable", sp.TrackKeepable(id="t", keepable=False)),
    ("session.state", sp.SessionStateChanged(state="recording")),
    (
        "level",
        sp.Level(-3.1, -17.4, (sp.ChannelLevel(-3.1, -17.2), sp.ChannelLevel(-3.4, -17.6))),
    ),
    ("log", sp.LogLine(level="info", msg="hello", ts="2026-11-15T00:00:00.5Z")),
    ("error", sp.SpytifyError(code="capture_silent", msg="", fatal=False)),
    (
        "error",
        sp.SpytifyError(code="disk_full", msg="only 3 MB", fatal=True, free_mb=0, facts={"a": "b"}),
    ),
    ("error", sp.SpytifyError(code="capture_low_quality", msg="x", source=sp.AudioSource(8000, 1))),
    ("settings.changed", sp.SettingsChanged(values={"output.counter_next": 3})),
    ("target.state", sp.TargetState(running=True, pid=12)),
]


@pytest.mark.parametrize(("method", "payload"), SAMPLES)
def test_each_payload_type_round_trips_and_fits_the_schema(method: str, payload: Any) -> None:
    params = payload.to_params()
    validate_event(method, params)
    assert sp.parse_notification(method, params) == payload


def test_omitempty_leaves_empty_fields_out() -> None:
    assert sp.TrackSkipped(id="t", reason="incomplete").to_params() == {
        "id": "t",
        "reason": "incomplete",
    }
    finished = sp.TrackFinished(id="t", path="/p", duration_ms=5, bytes=6, tagged=True)
    assert finished.to_params() == {
        "id": "t",
        "path": "/p",
        "duration_ms": 5,
        "bytes": 6,
        "tagged": True,
    }
    assert finished.counted
    assert not sp.TrackFinished(
        id="t", path="/p", duration_ms=5, bytes=6, tagged=True, low_volume=True
    ).counted
    # Pointers in Go: a zero is still sent.
    assert sp.SpytifyError(code="disk_full", msg="m", free_mb=0).to_params()["free_mb"] == 0


def test_a_withdrawal_is_an_empty_msg_on_a_withdrawable_code() -> None:
    assert sp.SpytifyError(code="capture_silent", msg="").withdrawn
    assert not sp.SpytifyError(code="capture_silent", msg="only silence").withdrawn
    assert not sp.SpytifyError(code="disk_full", msg="").withdrawn


def test_unknown_notifications_parse_to_none() -> None:
    assert sp.parse_notification("track.new_thing", {"x": 1}) is None


def test_results_round_trip_and_fit_the_schema() -> None:
    info = sp.CoreInfo(
        version="v2.0.2",
        protocol=1,
        target=sp.TargetInfo(process="spotify", mpris="org.mpris.MediaPlayer2.spotify"),
        platform="linux/amd64",
        checks=(
            sp.Check(name="target configured", ok=True, id="target", args=("spotify",)),
            sp.Check(name="sample rates", ok=False, id="sample_rates", advice=True),
            sp.Check(name="player heard", ok=False, id="player_heard", facts={"k": "v"}),
        ),
        warnings=("turn crossfade and gapless playback off in the player",),
    )
    validate_result("core.info", info.to_params())
    assert sp.CoreInfo.from_params(info.to_params()) == info
    assert [check.id for check in info.failed_checks()] == ["player_heard"]
    status = sp.SessionStatus(
        state="recording",
        counters=sp.Counters(recorded=1),
        session_id="20261115-000000",
        track=sp.Track(id="t", artist="a", title="b", length_ms=3),
    )
    validate_result("session.status", status.to_params())
    assert sp.SessionStatus.from_params(status.to_params()) == status
    stop = sp.SessionStopResult(recorded=1, skipped=2, stopping=True)
    validate_result("session.stop", stop.to_params())
    assert sp.SessionStopResult.from_params(stop.to_params()) == stop
    applied = sp.SettingsSetResult(applied=("a",), rejected={"b": "unknown setting"})
    validate_result("settings.set", applied.to_params())
    assert sp.SettingsSetResult.from_params(applied.to_params()) == applied


@pytest.mark.parametrize(
    ("code", "tail", "cause", "action"),
    [
        (0, [], "ok", "none"),
        (2, ["spytifyd: --set x: unknown setting"], "bad_setting", "fail_run"),
        (
            1,
            ["T error socket /r/s.sock: another spytifyd is listening on /r/s.sock"],
            "socket_in_use",
            "retry_once",
        ),
        (
            1,
            ["T error session.start: the output folder cannot be written to: x (code -32007)"],
            "output_dir",
            "fail_run",
        ),
        (1, ["T error session.start: ffmpeg not found (code -32002)"], "ffmpeg", "fail_run"),
        (
            1,
            ["T error session.start: spotify is not running (code -32001)"],
            "no_player",
            "fail_item",
        ),
        (1, ["T error --events: open x: permission denied"], "files", "fail_run"),
        (1, ["something else"], "other", "fail_item"),
        (-9, [], "killed", "fail_item"),
        (None, [], "killed", "fail_item"),
    ],
)
def test_classify_exit(code: int | None, tail: list[str], cause: str, action: str) -> None:
    verdict = sp.classify_exit(code, tail)
    assert (verdict.cause, verdict.action) == (cause, action)


# --- The fake recorder speaks it -----------------------------------------------------------------

ELSEWHERE = [("Passage", 87_000), ("Distant Peak", 90_000), ("Last Hours", 88_000)]


@pytest.fixture
def world(config: Config, fake_clock: FakeClock) -> FakeWorld:
    world = make_world(config, fake_clock)
    world.recorder.level_interval_s = 0.5  # some level events, not too many
    return world


def check_all(notes: list[RecorderNotification]) -> None:
    assert notes
    for note in notes:
        assert note.method in SCHEMA["events"], note.method
        validate_event(note.method, dict(note.params))


async def _play(world: FakeWorld, index: int) -> None:
    album = next(iter(world.catalog.albums.values()))
    track = album.entries[index].track
    assert track is not None
    await world.webapi.play(
        device_id=world.catalog.our_device.id, context_uri=album.album.uri, offset_uri=track.uri
    )


async def test_every_notification_of_a_whole_album_fits_the_schema(
    world: FakeWorld, fake_clock: FakeClock, tmp_path: Path
) -> None:
    world.catalog.add_album("Elsewhere", artist="fakename", tracks=ELSEWHERE)
    spec = recorder_spec(tmp_path, world, settings=[("output.prefix", "counter")])
    session = await world.recorder.start(spec)
    notes = Notes(session)
    await _play(world, 0)
    await fake_clock.advance_until(lambda: session.returncode is not None, within=900)
    await notes.done()
    check_all(notes.items)
    check_all(await session.events_file())
    assert {"track.started", "track.finished", "track.skipped", "level", "log"} <= {
        n.method for n in notes.items
    }


async def test_problem_notifications_fit_the_schema(
    world: FakeWorld, fake_clock: FakeClock, tmp_path: Path
) -> None:
    """Low volume, silent and stalled capture, a takeover's incomplete take, stop now, keep."""
    world.catalog.add_album("Elsewhere", artist="fakename", tracks=ELSEWHERE)
    world.player.set_volume(50)
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    notes = Notes(session)
    await _play(world, 0)
    await fake_clock.advance(1)
    await session.call("player.control", {"cmd": "full_volume"})
    world.recorder.set_capture("silent")
    await fake_clock.advance(11)
    world.recorder.set_capture("ok")
    await fake_clock.advance(80)  # Passage ends (skipped silent); Distant Peak starts
    world.recorder.set_capture("stalled")
    await fake_clock.advance(11)
    world.recorder.set_capture("ok")
    world.player.take_over("Pixel 9")
    await fake_clock.advance(1)
    stop = await session.call("session.stop", {"now": True})
    validate_result("session.stop", stop)
    keepable = [n for n in notes.items if n.method == "track.keepable"]
    if keepable:
        await session.call("track.keep", {"id": keepable[-1].params["id"]})
    await fake_clock.advance_until(lambda: session.returncode is not None, within=60)
    await notes.done()
    check_all(notes.items)
    assert {"error", "track.keepable"} <= {n.method for n in notes.items}


async def test_every_rpc_result_fits_the_schema(
    world: FakeWorld, fake_clock: FakeClock, tmp_path: Path
) -> None:
    world.catalog.add_album("Elsewhere", artist="fakename", tracks=ELSEWHERE)
    session = await world.recorder.start(recorder_spec(tmp_path, world))
    await _play(world, 0)
    await fake_clock.advance(2)
    calls: list[tuple[str, dict[str, Any] | None]] = [
        ("core.info", None),
        ("session.status", None),
        ("settings.get", {"keys": ["encode.format"]}),
        ("settings.get", None),
        ("settings.set", {"values": {"recorder.silence_db": -55, "nope": 1}}),
        ("settings.reset", {"prefix": "recorder"}),
        ("player.control", {"cmd": "full_volume"}),
        ("player.launch", None),
        ("log.tail", {"lines": 5}),
        ("events.recent", None),
        ("session.stop", {"now": False}),
    ]
    for method, params in calls:
        result = await session.call(method, params)
        validate_result(method, result)
    with pytest.raises(RecorderRpcError):
        await session.call("track.keep", {"id": "nothing-held"})
    validate_result("core.shutdown", await session.call("core.shutdown"))
    await fake_clock.advance_until(lambda: session.returncode is not None, within=200)
    assert await asyncio.wait_for(session.wait(), 1) == 0
