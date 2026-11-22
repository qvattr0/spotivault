"""How one item attempt ends: the outcome rules, in order (plan § Item states; design.md § Run
flow step 6). Pure: engine/item.py collects the facts while the item plays, then asks here.

Owner: **engine-item**.

The rules, first match wins:

| # | When | Outcome |
|---|---|---|
| 1 | the play failed (404 → unavailable, refused → failed), or no track ever started | that |
| 2 | nothing planned is missing any more (missing_only) | done |
| 3 | the recorder exited with an error nobody here caused | failed `recorder_exit` |
| 4 | the run engine stopped it (user, end of window, shutdown) | stopped, carried_over, … |
| 5 | another device took playback | interrupted (takeover) |
| 6 | the idle exit ended a pause mid-item, or the client went away | interrupted (stall) |
| 7 | anything in `partial_reason` | partial |
| 8 | otherwise | done |

Rule 4's shutdown is interrupted (shutdown). Rule 7: a capture problem, a fatal Spytify error,
the time limit, failed takes, tracks still missing; for a whole item also the context moving on,
or a guard pausing before the context went round (it can't be trusted as a whole pass).

A take Stop now or a shutdown cut is skipped `discarded`, not failed (item_takes.py), so it's
never in `failed_reasons`, and an item stopped with only such a take has no failure.
"""

from collections import Counter
from dataclasses import dataclass, field

from spotivault.engine.types import (
    ControllerErrorCode,
    InterruptedBy,
    ItemOutcome,
    PlayMode,
    RunFailure,
    StopRequest,
    Takeover,
)


@dataclass(frozen=True, slots=True)
class Ending:
    """How the attempt ends, before it becomes an ItemReport."""

    outcome: ItemOutcome
    reason: str | None = None  # English, for QueueItem.reason
    error_code: ControllerErrorCode | None = None
    run_failure: RunFailure | None = None
    interrupted_by: InterruptedBy | None = None


@dataclass(slots=True)
class AttemptFacts:
    """What happened in one attempt, as the item engine saw it."""

    mode: PlayMode = "missing_only"
    failure: Ending | None = None  # rule 1: failed or unavailable during the play
    still_missing: int | None = None  # missing_only: planned tracks not in the index afterwards
    crashed: str | None = None  # rule 3: why the recorder exited
    stop: StopRequest | None = None  # rule 4
    takeover: Takeover | None = None  # rule 5
    stalled: bool = False  # rule 6
    client_gone: bool = False  # rule 6
    capture_problem: str | None = None  # rule 7: Spytify's capture_silent / capture_stalled
    spytify_fatal: str | None = None  # rule 7: another error with fatal true
    hit_item_max: bool = False  # rule 7
    context_moved: bool = False  # rule 7 (whole items)
    guard_cut_pass: bool = False  # rule 7 (whole items): paused before the context went round
    failed_reasons: Counter[str] = field(default_factory=Counter)  # counted tracks that failed


def decide(facts: AttemptFacts) -> Ending:
    """The outcome, by the rules in the module docstring."""
    if facts.failure is not None:
        return facts.failure
    if facts.still_missing == 0:
        return Ending("done")
    if facts.crashed is not None:
        return Ending("failed", facts.crashed, error_code="recorder_exit")
    if facts.stop is not None:
        return stop_ending(facts.stop)
    if facts.takeover is not None:
        name = facts.takeover.device.name
        return Ending("interrupted", f"Playback moved to {name}.", interrupted_by="takeover")
    if facts.client_gone:
        return Ending("interrupted", "The Spotify client went away.", interrupted_by="stall")
    if facts.stalled:
        return Ending("interrupted", "Playback paused for more than 20 s.", interrupted_by="stall")
    problem = partial_reason(facts)
    if problem is not None:
        return Ending("partial", problem)
    return Ending("done")


def stop_ending(stop: StopRequest) -> Ending:
    """A stop from the run engine (ItemControl): by its cause."""
    if stop.cause == "user":
        return Ending("stopped")
    if stop.cause == "window_end":
        return Ending("carried_over")
    return Ending("interrupted", "The controller was stopping.", interrupted_by="shutdown")


def partial_reason(facts: AttemptFacts) -> str | None:
    """Why the item is partial (rule 7), or None when it isn't."""
    if facts.capture_problem is not None:
        return facts.capture_problem
    if facts.spytify_fatal is not None:
        return facts.spytify_fatal
    if facts.hit_item_max:
        return "Stopped at the item's time limit."
    if facts.mode == "whole":
        if facts.context_moved:
            return "Playback moved on to another context before the playlist ended."
        if facts.guard_cut_pass:
            return "The loop guard paused the player before the playlist ended."
    if facts.failed_reasons:
        return failed_text(facts.failed_reasons)
    if facts.still_missing:
        return f"{facts.still_missing} {_tracks(facts.still_missing)} still missing."
    return None


def failed_text(reasons: Counter[str]) -> str:
    """ "2 tracks failed: low volume" (QueueItem.reason)."""
    total = sum(reasons.values())
    words = ", ".join(reason.replace("_", " ") for reason, _ in reasons.most_common())
    return f"{total} {_tracks(total)} failed: {words}"


def _tracks(count: int) -> str:
    return "track" if count == 1 else "tracks"
