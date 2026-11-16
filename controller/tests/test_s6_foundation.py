"""S6's shared pieces: the state tables, the types between the engines, and the wiring."""

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI

from portcheck import assert_implements
from spotivault import ports
from spotivault.engine import states
from spotivault.engine.states import (
    ACTIVE_STATES,
    ITEM_TRANSITIONS,
    OUTCOME_STATES,
    RUN_TRANSITIONS,
    WAITING_STATES,
    InvalidTransition,
    check_item_transition,
    check_run_transition,
    item_badges,
    run_outcome,
    waiting_item_outcome,
)
from spotivault.engine.types import ItemControl, ItemTimings, StopRequest, TrackCounts
from spotivault.recorder import SpytifyRecorder, SpytifySession
from spotivault.services import Services

CONTRACT_ITEM_STATES = {
    "up_next", "planning", "preflight", "preparing", "starting", "playing", "finishing",
    "interrupted", "done", "up_to_date", "partial", "stopped", "carried_over", "failed",
    "unavailable", "removed",
}  # fmt: skip


def test_the_item_table_covers_every_contract_state() -> None:
    assert set(ITEM_TRANSITIONS) == CONTRACT_ITEM_STATES
    assert set(ACTIVE_STATES) | set(WAITING_STATES) | set(OUTCOME_STATES) == CONTRACT_ITEM_STATES
    for targets in ITEM_TRANSITIONS.values():
        assert targets <= CONTRACT_ITEM_STATES
    for state in OUTCOME_STATES:
        assert ITEM_TRANSITIONS[state] == frozenset(), state


def test_the_current_item_moves_through_its_phases_in_order() -> None:
    path = ["up_next", *ACTIVE_STATES, "done"]
    for old, new in zip(path, path[1:], strict=False):
        check_item_transition(old, new)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("playing", "done"),  # the recorder ran: finishing comes first
        ("up_next", "playing"),
        ("done", "planning"),
        ("removed", "up_next"),
        ("finishing", "up_next"),
    ],
)
def test_moves_the_table_doesnt_list_raise(old: str, new: str) -> None:
    with pytest.raises(InvalidTransition):
        check_item_transition(old, new)  # type: ignore[arg-type]


def test_d6_and_the_retry_paths() -> None:
    check_item_transition("preflight", "up_next")  # another device playing: wait, run paused
    check_item_transition("finishing", "interrupted")
    check_item_transition("interrupted", "planning")  # the retry, or Resume after a takeover
    check_item_transition("interrupted", "removed")
    check_item_transition("starting", "interrupted")  # SIGTERM before the recorder played


def test_the_run_table() -> None:
    for old, new in [
        ("starting", "running"),
        ("starting", "paused"),
        ("running", "finishing"),
        ("finishing", "running"),
        ("running", "paused"),
        ("paused", "running"),
        ("paused", "stopping"),
        ("stopping", "ended"),
        ("finishing", "ended"),
        ("starting", "ended"),
    ]:
        check_run_transition(old, new)  # type: ignore[arg-type]
    with pytest.raises(InvalidTransition):
        check_run_transition("paused", "ended")  # a stop always goes through stopping
    with pytest.raises(InvalidTransition):
        check_run_transition("ended", "running")
    assert RUN_TRANSITIONS["ended"] == frozenset()
    assert states.api_run_state("ended") == "idle"
    assert states.api_run_state("paused") == "paused"


@pytest.mark.parametrize(
    ("end", "items", "failed_tracks", "outcome"),
    [
        ("queue_done", ["done", "up_to_date"], 0, "completed"),
        ("queue_done", ["done", "partial"], 0, "completed_with_issues"),
        ("queue_done", ["done", "unavailable"], 0, "completed_with_issues"),
        ("queue_done", ["done"], 1, "completed_with_issues"),
        ("stopped", ["done", "failed"], 3, "stopped"),
        ("window_ended", ["carried_over"], 0, "window_ended"),
        ("failed", [], 0, "failed"),
    ],
)
def test_run_outcomes(end: str, items: list[str], failed_tracks: int, outcome: str) -> None:
    assert run_outcome(end, items, failed_tracks) == outcome  # type: ignore[arg-type]


def test_what_waiting_items_become_when_a_run_ends() -> None:
    assert waiting_item_outcome("stopped", "up_next") == "stopped"
    assert waiting_item_outcome("stopped", "interrupted") == "stopped"
    assert waiting_item_outcome("window_ended", "up_next") == "stopped"
    assert waiting_item_outcome("window_ended", "interrupted") == "carried_over"
    with pytest.raises(ValueError):
        waiting_item_outcome("stopped", "playing")


def test_badges() -> None:
    def badges(state: str, interrupted: int = 0, in_: bool = False, out: bool = False) -> list:
        return item_badges(
            state,  # type: ignore[arg-type]
            interrupted_count=interrupted,
            carried_over_in=in_,
            carried_over_out=out,
        )

    assert badges("up_to_date") == ["up_to_date"]
    assert badges("done", interrupted=1) == ["interrupted_retried"]
    assert badges("interrupted", interrupted=1) == []  # still waiting for its retry
    assert badges("partial", interrupted=2) == ["interrupted_twice"]
    assert badges("done", in_=True) == ["carried_over_in"]
    assert badges("carried_over") == ["carried_over_out"]
    assert badges("removed") == ["removed"]
    assert badges("stopped") == ["stopped"]


async def test_item_control_upgrades_and_never_downgrades() -> None:
    control = ItemControl()
    assert control.stop is None
    control.request_stop(StopRequest("after_track", "window_end"))
    assert await control.changed() == StopRequest("after_track", "window_end")
    control.request_stop(StopRequest("now", "user"))
    assert control.stop == StopRequest("now", "window_end")  # the mode goes up, the cause stays
    control.request_stop(StopRequest("after_track", "shutdown"))
    assert control.stop == StopRequest("now", "shutdown")  # shutdown wins: interrupted


def test_track_counts_and_timings() -> None:
    counts = TrackCounts(recorded=2, skipped_duplicate=3, skipped_other=1, failed=1, bytes=10)
    assert counts.skipped == 4
    start = datetime(2026, 11, 15, 1, 0, tzinfo=UTC)
    timings = ItemTimings(
        started_at=start,
        ended_at=start.replace(minute=8),
        phase_s={"planning": 0.25, "playing": 300.0},
        planned_ms=180_000,
    )
    assert timings.to_json() == {
        "started_at": "2026-11-15T01:00:00.000Z",
        "ended_at": "2026-11-15T01:08:00.000Z",
        "phase_s": {"planning": 0.25, "playing": 300.0},
        "recorder_started_at": None,
        "first_track_at": None,
        "finishing_at": None,
        "recorder_exit_at": None,
        "planned_ms": 180_000,
    }


def test_the_real_recorder_implements_its_ports() -> None:
    assert_implements(SpytifyRecorder, ports.Recorder)
    assert_implements(SpytifySession, ports.RecorderSession)


def test_services_hold_s6s_modules(services: Services) -> None:
    for name in ("runs", "schedule", "history", "files", "metrics"):
        assert getattr(services, name) is not None, name


async def test_the_hello_status_is_idle_with_no_run(
    running_app: FastAPI, services: Services
) -> None:
    snapshot = await services.bus.snapshot()
    assert snapshot["status"]["state"] == "idle"
    assert snapshot["status"]["view_only"] is False
    assert services.runs.active() is None and services.runs.recorder_pid() is None
