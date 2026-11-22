"""Steering one item: on each track start, stay, jump or pause (design.md § Run flow step 5).

Owner: **engine-item**. Pure decisions, no I/O, so each case is a plain unit test; item.py does
the calls (it identifies the track first, then asks here what to do). probe.py's `steer` and
`loaded_positions` are the tested starting point.

- **Identify** (item.py): the loaded track by MPRIS `mpris:trackid` (D10, S0 row 18), once
  MPRIS's title agrees with track.started's. GET /me/player can report a relinked id, so it's only
  the fallback. Here, an id that names no entry falls back to the title.
- **missing_only:** a planned track not yet started plays. Otherwise jump to the next planned
  track not started and not jumped to, or pause when none is left. Never jump while paused
  (probe.py: "loaded while Paused: not jumping"): that's the phantom take at the idle exit, or
  Spotify's end of a context. A planned track starting a second time while playing means the
  player is going round (repeat, or something steering didn't expect): pause, `steering_guard`.
- **whole:** everything plays, and skip-forward is on. Tracks are told apart by Spytify's key
  (first artist and title), each numbered in the order first heard. The loop guard (Spytify bug 1:
  skip-forward's Next restarts a paused player at the end of a context, which then plays again
  from its first track, every track a duplicate) reads each track started while playing:

  - not heard yet → stay; a run of repeats ends;
  - a repeat, the first in a row → stay: a playlist can list a track twice, or two tracks with
    the same key (Spytify skips it, and skip-forward moves on);
  - a repeat numbered the previous repeat's number + 1 → `loop_guard`: pause (going round);
  - any other repeat → stay; a new run of repeats starts at it.

  A playlist that lists a run of two or more tracks again in the same order still trips the guard
  (web-ui.md Open question 19). **`wrapped`** (the pass was heard to its end) is set only by
  Spotify's end of the context: the item engine sees the player paused at the start of the first
  track heard (`context_ended`), or the phantom take at the idle exit is that first track. A
  guard that fired never sets it: a run of repeats can also be a listed-twice run.
- **The context** (ContextCheck): GET /me/player's `context_uri` must be the item's. Liked Songs
  is reported by a playlist alias (`spotify:playlist:37i9dQZF1F…`, S0 row 17): the first such
  alias seen after the play is remembered and counts as the item's context from then on. Right
  after the play, GET /me/player can still report the context from before it (item.py, "GET
  /me/player lags a play"), and Spotify's own playlists share the alias's prefix, so the context
  that was playing before the play is learned only from a read that can't be stale any more.
"""

from dataclasses import dataclass
from typing import Literal

from spotivault.engine.planning import ItemPlan, PlannedTrack
from spotivault.matching import go_lower, go_trim, track_key

type SteerAction = Literal["stay", "jump", "pause", "loop_guard", "steering_guard"]

LIKED_ALIAS_PREFIX = "spotify:playlist:37i9dQZF1F"  # how GET /me/player names Liked Songs


@dataclass(frozen=True, slots=True)
class SteerDecision:
    action: SteerAction
    position: int | None = None  # the loaded track's position in the item, when identified
    planned: bool = False  # it's a planned track (events.md track.started.planned)
    jump_to: PlannedTrack | None = None  # with action "jump"
    track: PlannedTrack | None = None  # the item's entry the loaded track was matched to
    repeat: bool = False  # whole items: this track was already seen in this attempt


class Steering:
    """The steering state of one attempt: what started, what was jumped to, what was seen."""

    def __init__(self, plan: ItemPlan) -> None:
        self.plan = plan
        self.started: set[int] = set()  # planned positions that started
        self.jumped: set[int] = set()  # planned positions played at (the first play counts)
        self._planned_positions = {track.position for track in plan.missing}
        self._seen: dict[str, int] = {}  # whole: Spytify's key → the order first heard in (from 1)
        self._last_repeat: int | None = None  # whole: the previous take's number, if a repeat
        self.wrapped = False  # whole: the context ended at its first track (the pass was heard)
        self.guarded = False  # a guard paused the player

    # --- The play --------------------------------------------------------------------------------

    def first_offset(self) -> PlannedTrack | None:
        """Where the play starts: the first missing track (by URI), or None to play the context
        from its start (a whole item)."""
        if self.plan.mode == "whole" or not self.plan.missing:
            return None
        first = self.plan.missing[0]
        self.jumped.add(first.position)
        return first

    # --- A track started -----------------------------------------------------------------------

    def on_track_started(
        self, *, track_id: str | None, title: str, playing: bool, artist: str = ""
    ) -> SteerDecision:
        """The decision for a track that just started. `track_id` comes from MPRIS (or GET
        /me/player as the fallback), None when unknown; `playing`: Spytify wasn't paused."""
        if self.plan.mode == "whole":
            return self._whole(title=title, artist=artist, playing=playing)
        return self._missing_only(track_id=track_id, title=title, playing=playing)

    def on_planned_duplicate(self) -> SteerDecision:
        """missing_only: Spytify skipped a planned track as a duplicate (the track is listed
        twice, or the controller's key differs from Spytify's). With skip-forward off nothing
        moves on, so steer as for a track that isn't planned: jump to the next planned track, or
        pause when none is left (FINDINGS § Matching: "the controller jumps on")."""
        following = self.next_planned()
        if following is None:
            return SteerDecision("pause")
        self.jumped.add(following.position)
        return SteerDecision("jump", jump_to=following)

    # --- The end of the context ------------------------------------------------------------------

    def is_first_track(self, *, track_id: str | None, title: str, artist: str) -> bool:
        """Whether the loaded track is where Spotify goes at the end of the context, its first
        track: missing_only, the item's first playable entry (by id, else by title); whole, the
        first track heard in this attempt (by Spytify's key)."""
        if self.plan.mode == "whole":
            return self._seen.get(track_key(artist, title)) == 1
        if not self.plan.tracks:
            return False
        return self.plan.tracks[0] in self.loaded_tracks(track_id=track_id, title=title)

    def context_ended(self) -> None:
        """The item engine saw Spotify's end of the context (paused at the start of its first
        track): a whole item's pass was heard to its end."""
        self.wrapped = True

    def _missing_only(self, *, track_id: str | None, title: str, playing: bool) -> SteerDecision:
        hits = self.loaded_tracks(track_id=track_id, title=title)
        for track in hits:
            if track.position in self._planned_positions and track.position not in self.started:
                self.started.add(track.position)
                return SteerDecision("stay", track.position, planned=True, track=track)
        loaded = hits[0] if hits else None
        position = loaded.position if loaded else None
        if not playing:
            # The phantom take at the idle exit, or Spotify's end of the context: never jump.
            return SteerDecision("stay", position, track=loaded)
        if loaded is not None and loaded.position in self.started:
            # A planned track going round again: something plays that steering didn't ask for.
            self.guarded = True
            return SteerDecision("steering_guard", position, track=loaded)
        following = self.next_planned()
        if following is None:
            return SteerDecision("pause", position, track=loaded)
        self.jumped.add(following.position)
        return SteerDecision("jump", position, jump_to=following, track=loaded)

    def _whole(self, *, title: str, artist: str, playing: bool) -> SteerDecision:
        """The loop guard's table (module docstring)."""
        key = track_key(artist, title)  # Spytify's own key: the same however identified
        number = self._seen.get(key)
        if not playing:
            # The phantom take at the idle exit: Spotify's end of the context, forced. When it's
            # the first track heard, the context went back to its start: the pass was heard.
            if number == 1:
                self.wrapped = True
            return SteerDecision("stay", repeat=number is not None)
        if number is None:
            self._seen[key] = len(self._seen) + 1
            self._last_repeat = None
            return SteerDecision("stay", planned=True)
        previous, self._last_repeat = self._last_repeat, number
        if previous is not None and number == previous + 1:
            self.guarded = True  # two repeats in a row, in the order first heard: going round
            return SteerDecision("loop_guard", repeat=True)
        return SteerDecision("stay", repeat=True)  # one repeat alone: a track listed twice

    # --- Helpers -------------------------------------------------------------------------------

    def loaded_tracks(self, *, track_id: str | None, title: str) -> list[PlannedTrack]:
        """The item's entries the loaded track can be: those with its id, else those with its
        title (probe.py `loaded_positions`)."""
        if track_id:
            by_id = [track for track in self.plan.tracks if track.track_id == track_id]
            if by_id:
                return by_id
        wanted = go_lower(go_trim(title))
        return [track for track in self.plan.tracks if go_lower(go_trim(track.title)) == wanted]

    def next_planned(self) -> PlannedTrack | None:
        """The next planned track that hasn't started and wasn't jumped to."""
        for track in self.plan.missing:
            if track.position not in self.started and track.position not in self.jumped:
                return track
        return None


def same_context(reported_uri: str | None, item_uri: str, *, liked_alias: str | None) -> bool:
    """GET /me/player's context is the item's (Liked Songs: also its playlist alias). An unknown
    context (none reported) counts as the item's: a session is never stopped on missing facts."""
    if reported_uri is None or reported_uri == item_uri:
        return True
    return liked_alias is not None and reported_uri == liked_alias


class ContextCheck:
    """Whether GET /me/player still reports the item's context, learning Liked Songs' alias."""

    def __init__(self, item_uri: str, *, liked: bool) -> None:
        self.item_uri = item_uri
        self.liked = liked
        self.liked_alias: str | None = None
        self.before_play: str | None = None  # the context GET /me/player reported before the play

    def matches(self, reported_uri: str | None, *, settled: bool = True) -> bool:
        """`settled`: the read can't be the state from before the play any more. Until then,
        the context that was playing before the play isn't learned as Liked Songs' alias."""
        if (
            self.liked
            and self.liked_alias is None
            and reported_uri is not None
            and reported_uri.startswith(LIKED_ALIAS_PREFIX)
            and (settled or reported_uri != self.before_play)
        ):
            self.liked_alias = reported_uri  # S0 row 17: remember the alias after the first play
        return same_context(reported_uri, self.item_uri, liked_alias=self.liked_alias)
