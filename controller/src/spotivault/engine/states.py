"""The item and run state machines, as tables (plan § Item states and § Run states; openapi.yaml
`ItemState`, `RunState`, `Outcome`, `ItemBadge`; contracts/schema.sql `run_items.state`,
`runs.state`).

**Frozen (S6 foundation).** The item engine, the run engine and History all read these. Every
state change goes through `check_item_transition` or `check_run_transition`, so a move the tables
don't list is a bug that fails loudly (InvalidTransition) instead of a row in a strange state.

How an item moves (one row of `run_items`):

    up_next ──► planning ─► preflight ─► preparing ─► starting ─► playing ─► finishing ─► outcome
       ▲  │        │           │            │            │                       │
       │  │        └───────────┴────────────┴────────────┴──► outcome            ├──► interrupted
       │  └──► removed | stopped                                                 │      (waits)
       └────── preflight (D6: another device is playing; the run pauses)        ▼
                                                                    interrupted ─► planning (retry)

- **The current item** is in one of ACTIVE_STATES. The item engine moves it from `planning` to
  `finishing`; it reaches an outcome from any phase before `playing` (nothing was started yet),
  and only through `finishing` once the recorder ran (its events must be drained).
- **Waiting** items are `up_next` or `interrupted` (re-queued once, "Interrupted · will retry").
- **Outcomes** are final for the run. The run engine sets them from the item engine's
  ItemReport (engine/types.py): `interrupted` on the second attempt becomes `partial`.
- **When a run ends** with items still waiting: a stop makes them `stopped`; the end of a window
  makes `up_next` ones `stopped` and `interrupted` ones `carried_over` (they were cut off too).

How a run moves (`runs.state`; the API adds `idle` for "no run"):

    starting ─► running ⇄ finishing ─► ended
       │          │  ▲        │
       │          ▼  │        │
       ├──────► paused ◄──────┘
       └─► stopping ◄── running | finishing | paused        stopping ─► ended

- `starting`: the pre-run check and the catalog refresh. `finishing`: the current item is in its
  `finishing` phase (the ~25–30 s while the recorder saves the last track). `stopping`: a stop was
  asked for (Stop after this track, Stop now, or the end of a window) and is being carried out.
- `paused`: a takeover (`device_moved`) or D6 at the start (`device_busy`). Only Resume or Stop
  leave it.
"""

from collections.abc import Iterable
from typing import Literal

# --- Items -------------------------------------------------------------------------------------

type ItemState = Literal[
    "up_next",
    "planning",
    "preflight",
    "preparing",
    "starting",
    "playing",
    "finishing",
    "interrupted",
    "done",
    "up_to_date",
    "partial",
    "stopped",
    "carried_over",
    "failed",
    "unavailable",
    "removed",
]

# The current item's phases, in order (QueueItem.state while it runs).
ACTIVE_STATES: tuple[ItemState, ...] = (
    "planning",
    "preflight",
    "preparing",
    "starting",
    "playing",
    "finishing",
)
WAITING_STATES: tuple[ItemState, ...] = ("up_next", "interrupted")
OUTCOME_STATES: tuple[ItemState, ...] = (
    "done",
    "up_to_date",
    "partial",
    "stopped",
    "carried_over",
    "failed",
    "unavailable",
    "removed",
)

# Outcomes an item can reach before its recorder started: nothing to drain yet.
_BEFORE_RECORDER: frozenset[ItemState] = frozenset(
    {"stopped", "carried_over", "failed", "interrupted"}
)

ITEM_TRANSITIONS: dict[ItemState, frozenset[ItemState]] = {
    # Waiting.
    "up_next": frozenset({"planning", "removed", "stopped"}),
    "interrupted": frozenset({"planning", "removed", "stopped", "carried_over"}),
    # The current item.
    "planning": frozenset({"preflight", "up_to_date", "unavailable"}) | _BEFORE_RECORDER,
    "preflight": frozenset({"preparing", "up_next"}) | _BEFORE_RECORDER,  # up_next: D6
    "preparing": frozenset({"starting"}) | _BEFORE_RECORDER,
    "starting": frozenset({"playing"}) | _BEFORE_RECORDER,
    "playing": frozenset({"finishing"}),  # the recorder ran: always drain it first
    "finishing": frozenset(
        {"done", "partial", "stopped", "carried_over", "failed", "interrupted", "unavailable"}
    ),
    # Final.
    "done": frozenset(),
    "up_to_date": frozenset(),
    "partial": frozenset(),
    "stopped": frozenset(),
    "carried_over": frozenset(),
    "failed": frozenset(),
    "unavailable": frozenset(),
    "removed": frozenset(),
}


class InvalidTransition(RuntimeError):
    """A state change the tables don't allow: a bug in the engine, never a user error."""


def check_item_transition(old: ItemState, new: ItemState) -> None:
    """Raises InvalidTransition unless ITEM_TRANSITIONS allows `old` → `new`."""
    if new not in ITEM_TRANSITIONS[old]:
        raise InvalidTransition(f"item: {old} → {new} isn't allowed")


def is_final(state: ItemState) -> bool:
    return state in OUTCOME_STATES


# --- Runs --------------------------------------------------------------------------------------

type RunState = Literal["idle", "starting", "running", "paused", "stopping", "finishing"]
type StoredRunState = Literal["starting", "running", "paused", "stopping", "finishing", "ended"]

RUN_TRANSITIONS: dict[StoredRunState, frozenset[StoredRunState]] = {
    "starting": frozenset({"running", "paused", "stopping", "ended"}),
    "running": frozenset({"finishing", "paused", "stopping", "ended"}),
    "finishing": frozenset({"running", "paused", "stopping", "ended"}),
    "paused": frozenset({"running", "stopping"}),
    "stopping": frozenset({"ended"}),
    "ended": frozenset(),
}


def check_run_transition(old: StoredRunState, new: StoredRunState) -> None:
    """Raises InvalidTransition unless RUN_TRANSITIONS allows `old` → `new`."""
    if new not in RUN_TRANSITIONS[old]:
        raise InvalidTransition(f"run: {old} → {new} isn't allowed")


def api_run_state(state: StoredRunState) -> RunState:
    """`runs.state` as the API's RunState: an ended run is `idle` (events.md: the last
    `run.state` of a run says idle)."""
    return "idle" if state == "ended" else state


# --- How a run ends ----------------------------------------------------------------------------

type Outcome = Literal["completed", "completed_with_issues", "window_ended", "stopped", "failed"]

# Why the run engine ends a run.
type RunEnd = Literal[
    "queue_done",  # every item reached an outcome
    "stopped",  # Stop after this track or Stop now from the UI
    "window_ended",  # the scheduler: the window's last hour is over (or was turned off)
    "failed",  # the pre-run check failed, a fatal recorder exit, or the controller stopping
]

# Outcomes that are issues on the Dashboard ("Completed with issues").
ISSUE_STATES: frozenset[ItemState] = frozenset({"partial", "failed", "unavailable"})


def run_outcome(end: RunEnd, item_states: Iterable[ItemState], failed_tracks: int) -> Outcome:
    """The run's outcome (openapi.yaml `Outcome`, web-ui.md § Last run):
    - failed, stopped and window_ended follow `end`, whatever the items did;
    - queue_done is `completed_with_issues` when an item ended partial, failed or unavailable, or
      any track failed; else `completed`."""
    if end == "failed":
        return "failed"
    if end == "stopped":
        return "stopped"
    if end == "window_ended":
        return "window_ended"
    if failed_tracks > 0 or any(state in ISSUE_STATES for state in item_states):
        return "completed_with_issues"
    return "completed"


# What's left waiting when a run ends (module docstring).
def waiting_item_outcome(end: RunEnd, state: ItemState) -> ItemState:
    """The final state of an item still waiting (`up_next` or `interrupted`) when the run ends."""
    if state not in WAITING_STATES:
        raise ValueError(f"{state} isn't a waiting state")
    if end == "window_ended" and state == "interrupted":
        return "carried_over"
    return "stopped"


# --- Badges (openapi.yaml ItemBadge, web-ui.md § Run page) -------------------------------------

type Badge = Literal[
    "up_to_date",
    "interrupted_retried",
    "interrupted_twice",
    "carried_over_in",
    "carried_over_out",
    "removed",
    "stopped",
]


def item_badges(
    state: ItemState,
    *,
    interrupted_count: int,
    carried_over_in: bool,
    carried_over_out: bool,
) -> list[Badge]:
    """A run item's badges, in the contract's order, from its `run_items` row."""
    badges: list[Badge] = []
    if state == "up_to_date":
        badges.append("up_to_date")
    if interrupted_count >= 2:
        badges.append("interrupted_twice")
    elif interrupted_count == 1 and state != "interrupted":
        badges.append("interrupted_retried")
    if carried_over_in:
        badges.append("carried_over_in")
    if carried_over_out or state == "carried_over":
        badges.append("carried_over_out")
    if state == "removed":
        badges.append("removed")
    if state == "stopped":
        badges.append("stopped")
    return badges
