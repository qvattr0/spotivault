"""The item engine (engine/item.py, planning.py, steering.py, item_takes.py) on the simulator.

One test per case in the plan's Verification list and the item states, plus the pure steering
decisions. Times are on the fake clock: an album of five 90 s tracks takes milliseconds.
"""

import asyncio
import stat
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from engine_sim import ELSEWHERE, RecordingHost, Sim
from spotivault.clock import iso_ms
from spotivault.engine.item import RECHECK_S, RECHECK_TRIES, ItemEngine
from spotivault.engine.item_outcome import AttemptFacts, Ending, decide, partial_reason
from spotivault.engine.planning import ItemPlan, PlannedTrack, plan_item
from spotivault.engine.states import check_item_transition
from spotivault.engine.steering import ContextCheck, Steering, same_context
from spotivault.engine.types import (
    ItemControl,
    ItemJob,
    ItemReport,
    StopRequest,
    Takeover,
    Timeouts,
)
from spotivault.fake.catalog import CatalogAlbum, CatalogPlaylist
from spotivault.fake.recorder import SimRecorderSession
from spotivault.ports import (
    Device,
    NotConnected,
    NotFound,
    RecorderGone,
    RecorderStartError,
    SpotifyUnavailable,
)
from spotivault.recorder import protocol as sp

# --- Helpers -------------------------------------------------------------------------------------

TITLES = [title for title, _ in ELSEWHERE]

# The final run_items state the run engine gives each outcome (engine/types.py ItemOutcome).
FINAL_STATE = {
    "done": "done",
    "up_to_date": "up_to_date",
    "partial": "partial",
    "stopped": "stopped",
    "carried_over": "carried_over",
    "failed": "failed",
    "unavailable": "unavailable",
    "interrupted": "interrupted",
    "device_busy": "up_next",
}


async def album_job(
    sim: Sim, recorded: list[int], *, timeouts: Timeouts | None = None
) -> tuple[CatalogAlbum, ItemJob]:
    """FINDINGS' "Elsewhere" in Albums, with these tracks (0-based) recorded already."""
    album = sim.elsewhere()
    await sim.refresh()
    await sim.add_album(album)
    sim.prerecord(album, recorded)
    return album, await sim.job(album.album.id, timeouts=timeouts)


async def followed_playlist(sim: Sim, titles: list[str]) -> CatalogPlaylist:
    """A followed playlist (no item access: played whole), added to the Library by its link."""
    catalog = sim.world.catalog
    entries = [catalog.entry(title, artist="Band", duration_ms=60_000) for title in titles]
    playlist = sim.playlist("Theirs", entries, access="followed")
    await sim.refresh()
    await sim.add_playlist(playlist)
    await sim.refresh()  # the listing stores its snapshot_id (D13)
    return playlist


async def run(
    sim: Sim, job: ItemJob, *, control: ItemControl | None = None, within: float = 3600
) -> tuple[ItemReport, RecordingHost]:
    """Runs the item, and checks every state it went through is one the tables allow."""
    host = RecordingHost()
    report = await sim.run_item(job, host=host, control=control, within=within)
    await sim.clock.settle()  # the simulator's bus reader catches up with the last events
    states = ["up_next", *host.phase_names(), FINAL_STATE[report.outcome]]
    for old, new in zip(states, states[1:], strict=False):
        check_item_transition(old, new)  # type: ignore[arg-type]
    return report, host


def stop_at(sim: Sim, seconds: float, request: StopRequest) -> ItemControl:
    control = ItemControl()
    sim.at(seconds, lambda: control.request_stop(request))
    return control


async def results(sim: Sim, job: ItemJob) -> list[dict[str, Any]]:
    rows = await sim.services.store.fetchall(
        "SELECT take_id, track_id, position, title, planned, result, reason, file_id "
        "FROM track_results WHERE run_item_id = ? ORDER BY id",
        (job.run_item_id,),
    )
    return [dict(row) for row in rows]


async def end_run(sim: Sim, run_id: int) -> None:
    """Ends the simulator's run, so the next job gets a new one."""
    now = iso_ms(sim.clock.now())
    await sim.services.store.execute(
        "UPDATE runs SET state = 'ended', outcome = 'completed', ended_at = ? WHERE id = ?",
        (now, run_id),
    )


def started_events(sim: Sim) -> list[dict[str, Any]]:
    return sim.events_of("track.started")


def errors(sim: Sim, code: str | None = None) -> list[dict[str, Any]]:
    return [e for e in sim.events_of("error") if code is None or e["code"] == code]


def plays(sim: Sim) -> int:
    return sim.webapi_calls().count("PUT /me/player/play")


# --- Planning ------------------------------------------------------------------------------------


async def test_nothing_missing_is_up_to_date_without_a_recorder(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 1, 2, 3, 4])
    calls = len(sim.webapi_calls())
    report, host = await run(sim, job)
    assert report.outcome == "up_to_date"
    assert report.up_to_date_by == "nothing_missing"
    assert (report.mode, report.planned, report.still_missing) == ("missing_only", 0, 0)
    assert host.phase_names() == ["planning"]
    assert sim.recorder_sessions() == []
    assert sim.webapi_calls()[calls:] == []  # planning needs no Web API call
    row = await sim.services.store.fetchone(
        "SELECT last_backup_at, completed_at FROM items WHERE id = ?", (album.album.id,)
    )
    assert row["last_backup_at"] is not None and row["completed_at"] is not None


async def test_unplayable_entries_are_left_out_and_offsets_are_by_uri(sim: Sim) -> None:
    catalog = sim.world.catalog
    album = catalog.add_album("Gaps", artist="Gap Band", tracks=4, unplayable=(1,))
    await sim.refresh()
    await sim.add_album(album)
    job = await sim.job(album.album.id)
    plan = await plan_item(sim.services, job)
    assert [track.position for track in plan.missing] == [0, 2, 3]
    report, host = await run(sim, job)
    assert report.outcome == "done" and report.planned == 3
    assert host.phases[1] == ("preflight", "missing_only", 3)
    assert sim.recorded_titles(album) == {"Track 1", "Track 3", "Track 4"}


async def test_an_album_nothing_of_which_plays_is_unavailable(sim: Sim) -> None:
    album = sim.world.catalog.add_album("Elsewhere Else", tracks=2, unplayable=(0, 1))
    await sim.refresh()
    await sim.add_album(album)
    job = await sim.job(album.album.id)
    report, _ = await run(sim, job)
    assert report.outcome == "unavailable" and report.mode is None
    row = await sim.services.store.fetchone(
        "SELECT unavailable_reason FROM items WHERE id = ?", (album.album.id,)
    )
    assert row["unavailable_reason"] == "not_offered"


async def test_a_removed_item_is_unavailable(sim: Sim) -> None:
    album, job = await album_job(sim, [])
    await sim.services.albums.remove(album.album.id)
    report, host = await run(sim, job)
    assert report.outcome == "unavailable"
    assert report.reason == "Removed from the Library."
    assert host.phase_names() == ["planning"]


async def test_an_item_whose_list_was_never_fetched_plays_whole(sim: Sim) -> None:
    album, job = await album_job(sim, [])
    await sim.services.store.execute(
        "UPDATE items SET catalog_fetched_at = NULL WHERE id = ?", (album.album.id,)
    )
    plan = await plan_item(sim.services, job)
    assert plan.mode == "whole" and plan.item_access and plan.up_to_date_by is None


# --- Playing only the missing tracks (FINDINGS § Playing only the missing tracks) -----------------


async def test_an_untracked_playlist_plays_whole(sim: Sim) -> None:
    """createRun with `items` runs an untracked playlist; the run's refresh didn't fetch its
    list, so the stored one may be old: it plays whole rather than plan from it."""
    playlist = sim.playlist("Mine", tracks=3)
    await sim.refresh()
    await sim.track(playlist.playlist.id)
    await sim.refresh()
    await sim.track(playlist.playlist.id, False)
    job = await sim.job(playlist.playlist.id)
    plan = await plan_item(sim.services, job)
    assert plan.mode == "whole" and plan.item_access and plan.up_to_date_by is None


async def test_missing_2_and_4_jumps_over_3_and_pauses_on_5(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 2, 4])
    report, host = await run(sim, job)
    assert report.outcome == "done" and report.still_missing == 0
    assert sim.recorded_titles(album) == set(TITLES)
    assert host.phase_names() == [
        "planning",
        "preflight",
        "preparing",
        "starting",
        "playing",
        "finishing",
    ]
    assert host.phases[1] == ("preflight", "missing_only", 2)
    started = started_events(sim)
    assert [(e["position"], e["planned"]) for e in started] == [
        (2, True),
        (3, False),
        (4, True),
        (5, False),
    ]
    assert plays(sim) == 2  # the start at track 2, the jump to track 4
    assert sim.mpris_calls() == ["Pause"]  # the plan was done on track 5
    assert report.counts.recorded == 2 and report.counts.skipped_duplicate == 2
    settings = dict(sim.world.recorder.started[0].settings)
    assert settings["recorder.skip_duplicates_forward"] == "false"


async def test_missing_3_and_5_ends_with_the_phantom_at_the_idle_exit(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 1, 3])
    report, _ = await run(sim, job)
    assert report.outcome == "done"
    assert sim.recorded_titles(album) == set(TITLES)
    started = started_events(sim)
    assert [e["title"] for e in started] == [
        "Now And Then",
        "Seaside Stillness",
        "Last Hours",
        "Passage",  # the phantom: Spotify's end of the album, forced at the idle exit
    ]
    assert started[-1]["planned"] is False
    assert sim.mpris_calls() == []  # nothing to pause: Spotify paused at the album's end
    finishing = report.timings.phase_s["finishing"]
    assert 20 <= finishing <= 40  # the idle exit's tail, as in FINDINGS' excerpt


async def test_a_planned_track_spytify_already_has_is_jumped_over(sim: Sim) -> None:
    """An owned playlist lists "Echo" twice: both entries are planned, and Spytify skips the
    second as a duplicate. With skip-forward off it would play to its end unrecorded; the
    controller jumps on to "Coda" (FINDINGS § Matching: about 2 s lost)."""
    catalog = sim.world.catalog
    entries = [
        catalog.entry(title, artist="Band", duration_ms=120_000)
        for title in ("Echo", "Bridge", "Echo", "Coda")
    ]
    playlist = sim.playlist("Mine", entries)
    await sim.refresh()
    await sim.track(playlist.playlist.id)
    await sim.refresh()
    job = await sim.job(playlist.playlist.id)
    report, host = await run(sim, job)
    assert report.outcome == "done" and report.planned == 4
    assert sim.recorded_titles(playlist) == {"Echo", "Bridge", "Coda"}
    started = sim.events_of("track.started")
    titles = [event["title"] for event in started]
    assert titles[:4] == ["Echo", "Bridge", "Echo", "Coda"]  # then the end's phantom of track 1
    assert plays(sim) == 2  # the first play, and the jump from the duplicate
    playing_s = report.timings.phase_s["playing"]
    assert playing_s < 3 * 120 + 30  # "Echo" didn't play a second time in full


async def test_counts_are_distinct_tracks_not_events(sim: Sim) -> None:
    _, job = await album_job(sim, [0, 1, 3])
    report, host = await run(sim, job)
    skipped_events = sim.events_of("track.skipped")
    assert len(skipped_events) == 2  # track 4 jumped over, and the phantom track 1
    assert report.counts.recorded == 2
    assert report.counts.skipped_duplicate == 1  # the phantom isn't counted
    assert host.counts[-1] == report.counts
    assert report.counts.bytes > 0


async def test_the_files_an_item_saved_get_the_umask_mode(
    sim: Sim, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spytify 2.0.2 tags into a 0600 temporary file (spytify-bugs.md #7): the fake does too here.
    import spotivault.fake.recorder as fake_recorder

    write_take = fake_recorder._write_take

    def write_take_0600(path: Path, size: int, umask: int) -> None:
        write_take(path, size, umask)
        path.chmod(0o600)

    monkeypatch.setattr(fake_recorder, "_write_take", write_take_0600)
    album, job = await album_job(sim, [0, 2, 4])
    before = {path: stat.S_IMODE(path.stat().st_mode) for path in sim.music_files()}
    report, _ = await run(sim, job)
    assert report.outcome == "done" and report.counts.recorded == 2
    new = [path for path in sim.music_files() if path not in before]
    assert len(new) == 2
    expected = 0o666 & ~sim.services.config.umask_bits
    assert {stat.S_IMODE(path.stat().st_mode) for path in new} == {expected}
    for path, mode in before.items():  # files it didn't save are left as they were
        assert stat.S_IMODE(path.stat().st_mode) == mode


async def test_the_seek_to_0_regression_records_a_track_left_paused_1_s_in(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 1, 2, 3])
    sim.leave_player_on(album, 4, 1000)  # bug 2: paused 1 s into "Last Hours" by a run before
    report, _ = await run(sim, job)
    assert report.outcome == "done"
    assert "Last Hours" in sim.recorded_titles(album)
    calls = sim.webapi_calls()
    assert calls.index("PUT /me/player/seek") < calls.index("PUT /me/player/play")


async def test_mpris_lag_waits_for_the_title_to_agree(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 2, 4])
    sim.world.mpris.metadata_lag_s = 0.8
    report, _ = await run(sim, job)
    assert report.outcome == "done"
    assert sim.recorded_titles(album) == set(TITLES)
    assert [e["position"] for e in started_events(sim)] == [2, 3, 4, 5]


async def test_liked_songs_plays_the_collection_and_its_alias_is_the_same_context(
    sim: Sim,
) -> None:
    catalog = sim.world.catalog
    catalog.liked.extend(catalog.entry(f"Liked {n}", artist="Fan") for n in range(1, 4))
    await sim.track("liked")
    await sim.refresh()
    job = await sim.job("liked")
    assert job.context_uri == catalog.liked_uri
    report, _ = await run(sim, job)
    assert report.outcome == "done" and report.counts.recorded == 3
    assert errors(sim, "context_changed") == []


# --- Playing whole, and D13 ----------------------------------------------------------------------


async def test_a_followed_playlist_plays_whole_then_is_up_to_date_by_d13(sim: Sim) -> None:
    playlist = await followed_playlist(sim, ["One", "Two", "Three"])
    item_id = playlist.playlist.id
    job = await sim.job(item_id)
    report, host = await run(sim, job)
    assert report.outcome == "done", report.reason
    assert (report.mode, report.planned) == ("whole", None)
    assert host.phases[1] == ("preflight", "whole", None)
    assert report.clean_full_pass
    assert sim.recorded_titles(playlist) == {"One", "Two", "Three"}
    settings = dict(sim.world.recorder.started[0].settings)
    assert settings["recorder.skip_duplicates_forward"] == "true"
    observed = await sim.services.store.fetchall(
        "SELECT ordinal, title FROM observed_tracks WHERE item_id = ? ORDER BY ordinal", (item_id,)
    )
    assert [(row["ordinal"], row["title"]) for row in observed] == [
        (1, "One"),
        (2, "Two"),
        (3, "Three"),
    ]
    row = await sim.services.store.fetchone(
        "SELECT snapshot_id, last_full_pass_snapshot FROM items WHERE id = ?", (item_id,)
    )
    assert row["last_full_pass_snapshot"] == row["snapshot_id"] is not None
    # Bug 1's Next at the idle exit restarted the player; it was paused again.
    assert "Pause" in sim.mpris_calls()
    assert sim.world.player.status == "Paused"

    await end_run(sim, job.run_id)
    again = await sim.job(item_id)
    report, host = await run(sim, again)
    assert report.outcome == "up_to_date" and report.up_to_date_by == "d13_unchanged"
    assert len(sim.recorder_sessions()) == 1


async def test_a_snapshot_the_refresh_couldnt_read_plays_whole(sim: Sim) -> None:
    playlist = await followed_playlist(sim, ["One", "Two"])
    job = await sim.job(playlist.playlist.id)
    await run(sim, job)
    await end_run(sim, job.run_id)
    again = await sim.job(playlist.playlist.id, snapshot_unread=True)
    report, _ = await run(sim, again)
    assert report.outcome == "done" and report.counts.skipped_duplicate == 2
    assert len(sim.recorder_sessions()) == 2


async def test_a_whole_replay_of_duplicates_spaces_its_web_api_checks(sim: Sim) -> None:
    """Eight duplicates half a second apart: D10's track-start check at most every 5 s."""
    playlist = await followed_playlist(sim, [f"Song {n}" for n in range(1, 9)])
    sim.prerecord(playlist, range(8))
    job = await sim.job(playlist.playlist.id, snapshot_unread=True)
    calls = len(sim.webapi_calls())
    report, _ = await run(sim, job)
    assert report.outcome == "done" and report.counts.skipped_duplicate == 8
    checks = sim.webapi_calls()[calls:].count("GET /me/player")
    assert checks <= 4  # the pre-flight, the first track, one more, the pause at the end


async def test_a_seeked_take_isnt_a_clean_full_pass(sim: Sim) -> None:
    """Someone scrubs "Two" from Spotify Connect: Spytify skips it `seeked`. Nothing failed,
    but "Two" isn't recorded, so the pass mustn't let D13 skip the playlist next time."""
    playlist = await followed_playlist(sim, ["One", "Two", "Three"])
    seeked = False

    def on_player(event: Any) -> None:
        nonlocal seeked
        meta = event.metadata
        if not seeked and event.kind == "track" and meta is not None and meta.title == "Two":
            seeked = True
            sim.at(10, lambda: sim.world.player.seek_to(40_000))

    sim.world.player.listeners.append(on_player)
    job = await sim.job(playlist.playlist.id)
    report, _ = await run(sim, job)
    assert report.outcome == "done" and report.counts.failed == 0
    assert report.counts.skipped_other == 1
    assert not report.clean_full_pass
    assert sim.recorded_titles(playlist) == {"One", "Three"}
    await end_run(sim, job.run_id)
    again = await sim.job(playlist.playlist.id)
    report, _ = await run(sim, again)
    assert report.outcome == "done" and report.clean_full_pass  # played again: "Two" now too
    assert sim.recorded_titles(playlist) == {"One", "Two", "Three"}


async def test_a_deleted_file_forces_a_full_pass(sim: Sim) -> None:
    playlist = await followed_playlist(sim, ["One", "Two"])
    job = await sim.job(playlist.playlist.id)
    await run(sim, job)
    await end_run(sim, job.run_id)
    for path in sim.music_files():
        if "Two" in path.name:
            path.unlink()
    sim.services.matching.invalidate()
    again = await sim.job(playlist.playlist.id)
    report, _ = await run(sim, again)
    assert report.outcome == "done"
    assert report.counts.recorded == 1 and report.counts.skipped_duplicate == 1
    assert sim.recorded_titles(playlist) == {"One", "Two"}


async def test_bug_1s_replay_at_the_end_of_a_whole_item_is_paused(sim: Sim) -> None:
    """Bug 1's live path: track 1 loads at the end, skip-forward's Next replays the playlist,
    every track a duplicate. The end of the context or the loop guard pauses it."""
    playlist = await followed_playlist(sim, ["One", "Two", "Three"])
    sim.world.recorder.album_end_race = True
    job = await sim.job(playlist.playlist.id)
    report, _ = await run(sim, job)
    assert report.outcome == "done" and report.counts.recorded == 3
    assert report.counts.skipped_duplicate == 0  # the replay's duplicates are repeats
    assert report.clean_full_pass  # the context went round to its first track: a whole pass
    assert len(errors(sim, "loop_guard")) <= 1
    assert sim.world.player.status == "Paused"


async def test_a_track_listed_twice_plays_on_and_the_pass_is_clean(sim: Sim) -> None:
    """The second "Two" is one repeat alone: Spytify skips it and skip-forward moves on, so
    "Four" and "Five" are recorded, and the pass ends at Spotify's end of the context."""
    playlist = await followed_playlist(sim, ["One", "Two", "Three", "Two", "Four", "Five"])
    job = await sim.job(playlist.playlist.id)
    report, _ = await run(sim, job)
    assert errors(sim, "loop_guard") == []
    assert report.outcome == "done" and report.clean_full_pass
    assert sim.recorded_titles(playlist) == {"One", "Two", "Three", "Four", "Five"}
    assert report.counts.recorded == 5


async def test_track_1_listed_again_isnt_taken_for_the_end(sim: Sim) -> None:
    """[A, B, A, C]: the repeat of track 1 mid-pass is no wrap; "Three" is still recorded, and
    D13's observed tracks hold all three."""
    playlist = await followed_playlist(sim, ["One", "Two", "One", "Three"])
    job = await sim.job(playlist.playlist.id)
    report, _ = await run(sim, job)
    assert report.outcome == "done" and report.clean_full_pass
    assert sim.recorded_titles(playlist) == {"One", "Two", "Three"}
    observed = await sim.services.store.fetchall(
        "SELECT title FROM observed_tracks WHERE item_id = ? ORDER BY ordinal",
        (playlist.playlist.id,),
    )
    assert [row["title"] for row in observed] == ["One", "Two", "Three"]


async def test_a_run_of_tracks_listed_again_trips_the_loop_guard(sim: Sim) -> None:
    """Open question 19, narrowed: "One", "Two" listed again in the same order look like bug
    1's replay. The guard pauses; the pass isn't trusted (partial, not clean), so D13 never
    skips the playlist and "Four" is still looked for next time."""
    playlist = await followed_playlist(sim, ["One", "Two", "Three", "One", "Two", "Four"])
    job = await sim.job(playlist.playlist.id)
    report, _ = await run(sim, job)
    assert [e["message"] for e in errors(sim, "loop_guard")] == [
        "A track came round a second time, so the player was paused."
    ]
    assert errors(sim, "loop_guard")[0]["fatal"] is False
    assert report.outcome == "partial" and not report.clean_full_pass
    assert report.reason == "The loop guard paused the player before the playlist ended."
    assert "Pause" in sim.mpris_calls()


def stall_at_start_of(sim: Sim, title: str) -> None:
    """Our player pauses by itself 0.1 s into `title` (a stall at a track boundary)."""
    stalled = False

    def on_player(event: Any) -> None:
        nonlocal stalled
        meta = event.metadata
        if stalled or event.kind != "track" or meta is None or meta.title != title:
            return
        stalled = True
        sim.at(0.1, sim.world.player.pause_by_itself)

    sim.world.player.listeners.append(on_player)


async def test_a_stall_at_a_tracks_start_is_a_stall_not_the_end(sim: Sim) -> None:
    """Paused 0.1 s into "Three", not the context's first track: interrupted (re-queued once),
    never a clean full pass of the two tracks heard."""
    playlist = await followed_playlist(sim, ["One", "Two", "Three", "Four"])
    stall_at_start_of(sim, "Three")
    job = await sim.job(playlist.playlist.id)
    report, _ = await run(sim, job)
    assert report.outcome == "interrupted" and report.interrupted_by == "stall"
    assert not report.clean_full_pass
    row = await sim.services.store.fetchone(
        "SELECT last_full_pass_snapshot FROM items WHERE id = ?", (playlist.playlist.id,)
    )
    assert row["last_full_pass_snapshot"] is None


async def test_a_missing_only_stall_at_a_tracks_start_is_a_stall(sim: Sim) -> None:
    album, job = await album_job(sim, [])
    stall_at_start_of(sim, "Now And Then")
    report, _ = await run(sim, job)
    assert report.outcome == "interrupted" and report.interrupted_by == "stall"
    assert sim.recorded_titles(album) == {"Passage", "Distant Peak"}


async def test_the_end_of_the_context_is_seen_when_mpris_lags(sim: Sim) -> None:
    """MPRIS's metadata for track 1 comes 2 s after the pause: the end is known only then."""
    playlist = await followed_playlist(sim, ["One", "Two", "Three"])
    sim.world.mpris.metadata_lag_s = 2.0
    job = await sim.job(playlist.playlist.id)
    report, _ = await run(sim, job)
    assert report.outcome == "done" and report.clean_full_pass
    assert report.interrupted_by is None


async def test_autoplay_moving_the_context_stops_the_session(sim: Sim) -> None:
    playlist = await followed_playlist(sim, ["One", "Two"])
    sim.autoplay()
    job = await sim.job(playlist.playlist.id)
    report, _ = await run(sim, job)
    [error] = errors(sim, "context_changed")
    assert error["fatal"] is True and error["source"] == "controller"
    assert report.outcome == "partial" and not report.clean_full_pass
    assert report.error_code == "context_changed"
    assert sim.recorded_titles(playlist) == {"One", "Two"}
    assert sim.world.player.status == "Paused"
    assert error["facts"]["context_uri"].startswith("spotify:playlist:")
    last = (await results(sim, job))[-1]
    assert (last["result"], last["reason"]) == ("skipped", "incomplete")  # the radio's track
    assert report.counts.failed == 0


async def test_autoplay_after_the_last_missing_track_just_pauses(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 1, 2, 3])
    sim.autoplay()
    report, _ = await run(sim, job)
    assert report.outcome == "done"
    assert errors(sim, "context_changed") == []
    assert sim.mpris_calls() == ["Pause"]


# --- GET /me/player lagging a play ---------------------------------------------------------------
#
# Right after our play, Spotify can still report the player as it was before it (item.py, "GET
# /me/player lags a play"). `state_lag_s` makes the simulated player do the same.

LAG_S = 4.0  # longer than the first track's check and the first re-read 2 s later
FOREVER_S = 100_000.0  # a state that never catches up


async def owned_playlist(sim: Sim, titles: list[str]) -> CatalogPlaylist:
    """An owned playlist (missing tracks only), tracked, with its track list stored."""
    catalog = sim.world.catalog
    entries = [catalog.entry(title, artist="Band", duration_ms=90_000) for title in titles]
    playlist = sim.playlist("Mine", entries)
    await sim.refresh()
    await sim.track(playlist.playlist.id)
    await sim.refresh()
    return playlist


def player_reads(calls: list[str]) -> int:
    return calls.count("GET /me/player")


def seconds_between(earlier: datetime | None, later: datetime | None) -> float:
    assert earlier is not None and later is not None
    return (later - earlier).total_seconds()


@pytest.mark.parametrize("mpris_lag_s", [0.0, 4.0], ids=["mpris_names_it", "mpris_late"])
async def test_the_context_before_the_play_isnt_taken_for_autoplay(
    sim: Sim, mpris_lag_s: float
) -> None:
    """A real run: run 2 recorded an album; a file of an owned playlist was deleted; run 4's
    check at the track's start, 1.3 s after the play, still read the album as the context. The
    item was stopped as autoplay and the track stayed missing. With MPRIS late (no id within
    3 s), steering goes by the title and GET /me/player is read again instead."""
    album, album_item = await album_job(sim, [])
    await run(sim, album_item)  # run 2: the player is left on the album
    await end_run(sim, album_item.run_id)
    playlist = await owned_playlist(sim, ["One", "Two", "Three", "Four"])
    sim.prerecord(playlist, [0, 1, 3])  # "Three"'s file was deleted
    sim.world.player.state_lag_s = LAG_S
    sim.world.mpris.metadata_lag_s = mpris_lag_s
    job = await sim.job(playlist.playlist.id)
    before = len(sim.webapi_calls())
    report, _ = await run(sim, job)
    assert report.outcome == "done", report.reason
    assert errors(sim, "context_changed") == []
    assert sim.recorded_titles(playlist) == {"One", "Two", "Three", "Four"}
    [take] = [row for row in await results(sim, job) if row["title"] == "Three"]
    assert (take["planned"], take["result"]) == (1, "recorded")
    calls = sim.webapi_calls()[before:]
    assert calls[:8] == [  # run 4's requests
        "GET /me/player/devices",
        "GET /me/player",
        "PUT /me/player/pause",
        "PUT /me/player/seek",
        "PUT /me/player/shuffle",
        "PUT /me/player/repeat",
        "PUT /me/player/play",
        "GET /me/player",  # at the track's start: still the album
    ]
    # Then the 60 s check. MPRIS naming the item's track settles the first; MPRIS late, it's
    # read again 2 s later (and D10's fallback reads it at "Four"'s start).
    assert player_reads(calls[7:]) == (2 if mpris_lag_s == 0 else 4)


async def test_autoplay_is_still_stopped_after_a_stale_start(sim: Sim) -> None:
    """The state lags the play, then catches up; when the playlist ends, autoplay's radio is
    stopped at its first track, as before."""
    album = sim.elsewhere()
    sim.leave_player_on(album, 0, 0)  # an earlier item's album
    playlist = await followed_playlist(sim, ["One", "Two"])
    sim.world.player.state_lag_s = LAG_S
    sim.autoplay()
    job = await sim.job(playlist.playlist.id)
    report, _ = await run(sim, job)
    [error] = errors(sim, "context_changed")
    assert error["facts"]["context_uri"] not in (album.album.uri, playlist.playlist.uri)
    assert report.outcome == "partial" and report.error_code == "context_changed"
    assert sim.recorded_titles(playlist) == {"One", "Two"}
    last = (await results(sim, job))[-1]
    assert (last["result"], last["reason"]) == ("skipped", "incomplete")  # the radio's track
    assert sim.world.player.status == "Paused"


async def test_a_state_that_never_catches_up_is_taken_as_true(sim: Sim) -> None:
    """No track list to vouch for the context (a whole item): after the first read and
    RECHECK_TRIES more, 2 s apart, the other context is taken as true and the item stopped."""
    album = sim.elsewhere()
    sim.leave_player_on(album, 0, 0)
    playlist = await followed_playlist(sim, ["One", "Two"])
    sim.world.player.state_lag_s = FOREVER_S
    job = await sim.job(playlist.playlist.id)
    before = len(sim.webapi_calls())
    report, _ = await run(sim, job)
    [error] = errors(sim, "context_changed")
    assert error["facts"]["context_uri"] == album.album.uri
    assert report.outcome == "partial"
    calls = sim.webapi_calls()[before:]
    assert player_reads(calls[calls.index("PUT /me/player/play") :]) == 1 + RECHECK_TRIES
    waited = seconds_between(report.timings.first_track_at, report.timings.finishing_at)
    assert RECHECK_TRIES * RECHECK_S <= waited < RECHECK_TRIES * RECHECK_S + 2
    [take] = await results(sim, job)
    assert (take["title"], take["result"], take["reason"]) == ("One", "skipped", "incomplete")


async def test_a_state_that_never_catches_up_is_let_go_while_mpris_names_the_track(
    sim: Sim,
) -> None:
    """MPRIS's id is one of the item's tracks, so the context hasn't moved on, however long
    GET /me/player keeps reporting the album: no re-reads, and the track is recorded."""
    album = sim.elsewhere()
    sim.leave_player_on(album, 0, 0)
    playlist = await owned_playlist(sim, ["One", "Two", "Three"])
    sim.prerecord(playlist, [0, 2])
    sim.world.player.state_lag_s = FOREVER_S
    job = await sim.job(playlist.playlist.id)
    before = len(sim.webapi_calls())
    report, _ = await run(sim, job)
    assert report.outcome == "done", report.reason
    assert errors(sim, "context_changed") == []
    assert "Two" in sim.recorded_titles(playlist)
    calls = sim.webapi_calls()[before:]
    assert player_reads(calls[calls.index("PUT /me/player/play") :]) == 2  # the start, 60 s


async def test_liked_songs_alias_isnt_learned_from_the_context_before_the_play(sim: Sim) -> None:
    """Spotify's own playlists share Liked Songs' alias prefix. The one playing before the play,
    still reported just after it, mustn't be learned as the alias: the real alias would then
    look like another context."""
    catalog = sim.world.catalog
    catalog.liked.extend(catalog.entry(f"Liked {n}", artist="Fan") for n in range(1, 4))
    top = catalog.add_playlist(
        "Your Top Songs", tracks=3, access="spotify", playlist_id="37i9dQZF1FTopSongs00001"
    )
    sim.leave_player_on(top, 1, 0)
    await sim.track("liked")
    await sim.refresh()
    sim.world.player.state_lag_s = LAG_S
    job = await sim.job("liked")
    report, _ = await run(sim, job)
    assert report.outcome == "done", report.reason
    assert report.counts.recorded == 3
    assert errors(sim, "context_changed") == []


def take_over_into(sim: Sim, title: str, seconds: float) -> list[datetime]:
    """The phone takes playback over `seconds` into `title`. The list gets the time it did."""
    taken: list[datetime] = []

    def take_over() -> None:
        taken.append(sim.clock.now())
        sim.world.player.take_over("Pixel 9")

    def on_player(event: Any) -> None:
        meta = event.metadata
        if event.kind == "track" and meta is not None and meta.title == title:
            sim.world.player.listeners.remove(on_player)  # once
            sim.at(seconds, take_over)

    sim.world.player.listeners.append(on_player)
    return taken


async def test_the_device_active_before_the_play_isnt_a_takeover(sim: Sim) -> None:
    """The phone was the active device (paused) before the play. Just after it, GET /me/player
    still reports the phone: not a takeover. A real one later is acted on at once."""
    album, job = await album_job(sim, [])
    sim.world.player.play_elsewhere("Pixel 9")
    sim.world.player.stop_elsewhere()  # paused there: D6 lets the item start
    sim.world.player.state_lag_s = LAG_S
    take_over_into(sim, "Distant Peak", 10)
    report, _ = await run(sim, job)
    assert report.outcome == "interrupted" and report.interrupted_by == "takeover"
    assert sim.recorded_titles(album) == {"Passage"}
    assert report.takeover is not None
    [discarded] = [row for row in await results(sim, job) if row["title"] == "Distant Peak"]
    assert report.takeover.discarded_take_id == discarded["take_id"]
    assert sim.mpris_calls() == []  # the player is left alone


async def test_a_takeover_hidden_by_the_lag_is_acted_on_at_the_next_read(sim: Sim) -> None:
    """The phone takes over 2.5 s into the first track, while GET /me/player still reports the
    album before the play: the pause's check reads again. The next read shows the phone, which
    wasn't active before the play, so it can't be the old state: acted on then, RECHECK_S after
    the pause, and not taken for autoplay."""
    album, job = await album_job(sim, [])
    other = sim.album("Before", 2)
    sim.leave_player_on(other, 0, 0)
    sim.world.player.state_lag_s = LAG_S
    taken = take_over_into(sim, "Passage", 2.5)
    report, _ = await run(sim, job)
    assert errors(sim, "context_changed") == []
    assert report.outcome == "interrupted" and report.interrupted_by == "takeover"
    waited = seconds_between(taken[0], report.timings.finishing_at)
    assert RECHECK_S <= waited < 2 * RECHECK_S
    assert sim.recorded_titles(album) == set()


@pytest.mark.parametrize("kind", ["album", "whole"])
async def test_a_takeover_at_the_first_tracks_start_isnt_taken_for_its_end(
    sim: Sim, kind: str
) -> None:
    """Nothing was active before the play (204). The phone takes over 1.2 s into the first
    track: our player pauses where Spotify's end of the context would. The pause's read shows
    the phone, which can't be the state from before the play: acted on at once."""
    if kind == "album":
        _, job = await album_job(sim, [])
        first = "Passage"
    else:
        playlist = await followed_playlist(sim, ["One", "Two", "Three"])
        job = await sim.job(playlist.playlist.id)
        first = "One"
    assert sim.world.player.player_state() is None
    sim.world.player.state_lag_s = 1.0  # stale at the track's start, caught up at the pause
    taken = take_over_into(sim, first, 1.2)
    report, _ = await run(sim, job)
    assert report.outcome == "interrupted" and report.interrupted_by == "takeover"
    assert seconds_between(taken[0], report.timings.finishing_at) < RECHECK_S  # at once


@pytest.mark.parametrize("mpris_lag_s", [0.0, 2.0], ids=["mpris_on_time", "mpris_late"])
async def test_a_takeover_by_the_device_before_the_play_at_the_first_tracks_start(
    sim: Sim, mpris_lag_s: float
) -> None:
    """The phone was active (paused) before the play, and takes over 1.2 s into the first
    track. Its read can be the old state, so it's read again; meanwhile the pause, though right
    at the first track's start, isn't taken for the context's end, nor when MPRIS's metadata
    comes after it. After the last re-read the takeover is taken as true."""
    album, job = await album_job(sim, [])
    sim.world.player.play_elsewhere("Pixel 9")
    sim.world.player.stop_elsewhere()
    sim.world.player.state_lag_s = 1.0
    sim.world.mpris.metadata_lag_s = mpris_lag_s
    taken = take_over_into(sim, "Passage", 1.2)
    report, _ = await run(sim, job)
    assert report.outcome == "interrupted" and report.interrupted_by == "takeover"
    # The re-reads began at the first read, stale: at the track's start, which with MPRIS late
    # is handled once its metadata comes.
    waited = seconds_between(taken[0], report.timings.finishing_at)
    assert RECHECK_S < waited < RECHECK_TRIES * RECHECK_S + mpris_lag_s + 1
    assert sim.recorded_titles(album) == set()


async def test_the_contexts_end_during_the_re_reads_is_judged_after_them(sim: Sim) -> None:
    """A whole playlist of one 3 s track, with GET /me/player 4 s behind the play: the context
    ends (its first track loaded, paused at 0) while the read at the track's start is being
    read again. Once a read catches up, the pause is judged: the end of the context, so the
    pass is whole, not a stall left to the idle exit."""
    album = sim.elsewhere()
    sim.leave_player_on(album, 0, 0)
    catalog = sim.world.catalog
    short = sim.playlist(
        "Theirs", [catalog.entry("Short", artist="Band", duration_ms=3_000)], access="followed"
    )
    await sim.refresh()
    await sim.add_playlist(short)
    await sim.refresh()
    sim.world.player.state_lag_s = LAG_S
    job = await sim.job(short.playlist.id)
    before = len(sim.webapi_calls())
    report, _ = await run(sim, job)
    assert report.outcome == "done", report.reason
    assert report.clean_full_pass
    assert errors(sim) == []
    calls = sim.webapi_calls()[before:]
    assert player_reads(calls[calls.index("PUT /me/player/play") :]) >= 3  # start, pause, re-read
    assert sim.recorded_titles(short) == {"Short"}


async def test_autoplay_is_stopped_at_once_before_a_read_caught_up(sim: Sim) -> None:
    """Nothing was active before the play (204), and no read has shown the item's context yet
    when autoplay's radio starts. The radio's context isn't the one from before the play, so it
    can't be the old state: stopped at its first track, as before."""
    catalog = sim.world.catalog
    playlist = sim.playlist(
        "Theirs", [catalog.entry("One", artist="Band", duration_ms=30_000)], access="followed"
    )
    await sim.refresh()
    await sim.add_playlist(playlist)
    await sim.refresh()
    assert sim.world.player.player_state() is None
    sim.world.player.state_lag_s = 1.3
    sim.autoplay()
    radio_at: list[datetime] = []

    def on_player(event: Any) -> None:
        meta = event.metadata
        if event.kind == "track" and meta is not None and meta.title != "One" and not radio_at:
            radio_at.append(sim.clock.now())

    sim.world.player.listeners.append(on_player)
    job = await sim.job(playlist.playlist.id)
    before = len(sim.webapi_calls())
    report, _ = await run(sim, job)
    assert report.outcome == "partial" and report.error_code == "context_changed"
    assert seconds_between(radio_at[0], report.timings.finishing_at) < RECHECK_S  # at once
    calls = sim.webapi_calls()[before:]
    assert player_reads(calls[calls.index("PUT /me/player/play") :]) == 2  # One's, the radio's
    one, radio = await results(sim, job)
    assert (one["title"], one["result"]) == ("One", "recorded")
    assert (radio["planned"], radio["result"], radio["reason"]) == (0, "skipped", "incomplete")


async def test_liked_songs_catches_up_when_it_was_playing_before_the_play(sim: Sim) -> None:
    """The phone was on Liked Songs (paused) before the play: its alias is the context from
    before it, and the phone the device. A read naming the take playing now, not the track
    loaded before the play, isn't the old state: the alias is learned from it and the state has
    caught up, so the phone taking over later is acted on at once."""
    catalog = sim.world.catalog
    catalog.liked.extend(
        catalog.entry(f"Liked {n}", artist="Fan", duration_ms=90_000) for n in range(1, 5)
    )
    await sim.track("liked")
    await sim.refresh()
    sim.world.player.play_elsewhere("Pixel 9")  # Liked Songs, at its first track
    sim.world.player.stop_elsewhere()
    taken = take_over_into(sim, "Liked 3", 30)
    job = await sim.job("liked")
    report, _ = await run(sim, job)
    assert errors(sim, "context_changed") == []
    assert report.outcome == "interrupted" and report.interrupted_by == "takeover"
    assert seconds_between(taken[0], report.timings.finishing_at) < RECHECK_S  # at once


# --- D6, the pre-flight and the start ------------------------------------------------------------


async def test_d6_another_device_playing_is_device_busy(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    sim.world.player.play_elsewhere("Pixel 9")
    calls = len(sim.webapi_calls())
    report, host = await run(sim, job)
    assert report.outcome == "device_busy"
    assert report.device_busy is not None and report.device_busy.name == "Pixel 9"
    assert host.phase_names() == ["planning", "preflight"]
    assert sim.recorder_sessions() == []
    assert [c for c in sim.webapi_calls()[calls:] if c.startswith("PUT")] == []


async def test_our_device_missing_fails_the_run(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    sim.world.player.client_gone()  # our device is listed only while the client runs
    report, _ = await run(sim, job)
    assert report.outcome == "failed"
    assert report.run_failure is not None and report.run_failure.reason == "device_missing"


async def test_no_room_in_the_music_folder_fails_the_run(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    sim.world.storage.set_state(sim.services.config.music_dir, free_bytes=10**9)
    report, _ = await run(sim, job)
    assert report.outcome == "failed" and report.error_code == "storage"
    assert report.run_failure is not None and report.run_failure.reason == "storage"
    assert errors(sim, "storage")[0]["fatal"] is True


async def test_the_web_api_disconnected_fails_the_run(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    sim.world.webapi.failures = [NotConnected("not connected")]
    report, _ = await run(sim, job)
    assert report.outcome == "failed" and report.error_code == "webapi"
    assert report.run_failure is not None and report.run_failure.reason == "not_connected"


async def test_a_web_api_outage_while_preparing_fails_the_item(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    original = sim.world.webapi.seek

    async def seek(*args: Any, **kwargs: Any) -> None:
        raise SpotifyUnavailable("Spotify is down", status=503)

    sim.world.webapi.seek = seek  # type: ignore[method-assign]
    report, host = await run(sim, job)
    sim.world.webapi.seek = original  # type: ignore[method-assign]
    assert report.outcome == "failed" and report.error_code == "webapi"
    assert report.run_failure is None  # the run moves on to the next item
    assert host.phase_names()[-1] == "preparing"


async def test_a_bad_setting_fails_the_run(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    sim.world.recorder.start_failure = RecorderStartError(
        "spytifyd exited with code 2: --set encode.format: expected one of mp3, aac",
        exit_code=2,
        log_tail=["2026-11-15T00:00:00Z error --set encode.format: expected one of mp3, aac"],
    )
    report, host = await run(sim, job)
    assert report.outcome == "failed" and report.error_code == "recorder_exit"
    assert report.run_failure is not None and report.run_failure.reason == "recorder"
    assert report.recorder_exit_code == 2
    assert host.phase_names()[-1] == "starting"
    assert errors(sim, "recorder_exit")[0]["facts"]["cause"] == "bad_setting"


async def test_an_output_folder_it_cant_write_fails_the_run_for_storage(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    line = "x error session.start: the output folder cannot be written to (code -32007)"
    sim.world.recorder.start_failure = RecorderStartError(
        "spytifyd exited with code 1", exit_code=1, log_tail=[line]
    )
    report, _ = await run(sim, job)
    assert report.run_failure is not None and report.run_failure.reason == "storage"


async def test_a_socket_in_use_is_retried_once(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 1, 2, 3])
    line = "x error socket /run/s.sock: another spytifyd is listening on /run/s.sock"
    sim.world.recorder.start_failure = RecorderStartError(
        "spytifyd exited with code 1", exit_code=1, log_tail=[line]
    )
    sim.world.recorder.orphans = 1
    report, _ = await run(sim, job)
    assert report.outcome == "done"
    assert len(sim.world.recorder.started) == 2
    assert sim.world.recorder.orphans == 0  # kill_orphans() ran


async def test_no_player_within_wait_target_fails_the_item(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    line = "x error session.start: spotify is not running (code -32001)"
    sim.world.recorder.start_failure = RecorderStartError(
        "spytifyd exited with code 1", exit_code=1, log_tail=[line]
    )
    report, _ = await run(sim, job)
    assert report.outcome == "failed" and report.run_failure is None


async def test_a_stop_before_the_recorder_starts_ends_at_once(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    control = ItemControl()
    control.request_stop(StopRequest("after_track", "user"))
    report, host = await run(sim, job, control=control)
    assert report.outcome == "stopped"
    assert host.phase_names() == ["planning"]
    assert sim.recorder_sessions() == []


# --- Stops ---------------------------------------------------------------------------------------


async def test_stop_after_this_track(sim: Sim) -> None:
    album, job = await album_job(sim, [])
    control = stop_at(sim, 30, StopRequest("after_track", "user"))
    report, _ = await run(sim, job, control=control)
    assert report.outcome == "stopped"
    assert sim.recorded_titles(album) == {"Passage"}  # the take finished first
    assert report.counts.recorded == 1 and report.counts.failed == 0
    assert sim.mpris_calls() == ["Pause"]  # the next track was paused
    assert sim.world.player.status == "Paused"


async def test_stop_now_discards_the_take(sim: Sim) -> None:
    album, job = await album_job(sim, [])
    control = stop_at(sim, 30, StopRequest("now", "user"))
    report, _ = await run(sim, job, control=control)
    assert report.outcome == "stopped"
    assert sim.recorded_titles(album) == set()
    [take] = await results(sim, job)
    assert (take["result"], take["reason"]) == ("failed", "discarded")
    assert sim.world.player.status == "Paused"


async def test_a_stop_after_this_track_can_become_now(sim: Sim) -> None:
    album, job = await album_job(sim, [])
    control = stop_at(sim, 30, StopRequest("after_track", "user"))
    sim.at(40, lambda: control.request_stop(StopRequest("now", "user")))
    report, _ = await run(sim, job, control=control)
    assert report.outcome == "stopped"
    assert sim.recorded_titles(album) == set()
    assert report.timings.phase_s["playing"] < 45


def stop_once_the_album_ends(sim: Sim, request: StopRequest, *, after_s: float) -> ItemControl:
    """A stop `after_s` after Spotify's end of the album (track 1 loaded, paused): while the
    item is finishing and the last take waits for the idle exit."""
    control = ItemControl()
    sent = False

    def on_player(event: Any) -> None:
        nonlocal sent
        if not sent and event.kind == "track" and event.album_end:
            sent = True
            sim.at(after_s, lambda: control.request_stop(request))

    sim.world.player.listeners.append(on_player)
    return control


@pytest.mark.parametrize("cause", ["user", "shutdown"])
async def test_stop_now_while_finishing_keeps_the_last_take(sim: Sim, cause: str) -> None:
    """The last track played in full and waits for the idle exit to be cut. A stop now would
    have Spytify reject it (handleStop), so it's sent as {now: false}: saved at the idle exit."""
    album, job = await album_job(sim, [0, 1, 2, 3])
    request = StopRequest("now", cause)  # type: ignore[arg-type]
    control = stop_once_the_album_ends(sim, request, after_s=5)
    report, _ = await run(sim, job, control=control)
    assert report.outcome == "done"  # nothing is missing any more
    assert sim.recorded_titles(album) == set(TITLES)
    take = (await results(sim, job))[0]
    assert (take["title"], take["result"]) == ("Last Hours", "recorded")
    finishing_at = report.timings.finishing_at
    assert finishing_at is not None
    ended = (report.timings.ended_at - finishing_at).total_seconds()
    assert ended < 40  # inside the SIGTERM bound


async def test_the_end_of_a_window_is_carried_over(sim: Sim) -> None:
    album, job = await album_job(sim, [])
    control = stop_at(sim, 30, StopRequest("after_track", "window_end"))
    report, _ = await run(sim, job, control=control)
    assert report.outcome == "carried_over"
    assert sim.recorded_titles(album) == {"Passage"}


async def test_a_stop_once_nothing_is_missing_is_done(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 1, 2, 3])
    control = stop_at(sim, 60, StopRequest("after_track", "window_end"))
    report, _ = await run(sim, job, control=control)
    assert report.outcome == "done"
    assert sim.recorded_titles(album) == set(TITLES)


async def test_shutdown_is_interrupted(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    control = ItemControl()
    asked: list[float] = []

    def shutdown() -> None:
        asked.append(sim.clock.monotonic())
        control.request_stop(StopRequest("now", "shutdown"))

    sim.at(30, shutdown)
    report, _ = await run(sim, job, control=control)
    assert report.outcome == "interrupted" and report.interrupted_by == "shutdown"
    [take] = await results(sim, job)
    assert (take["result"], take["reason"]) == ("failed", "interrupted")
    assert sim.clock.monotonic() - asked[0] < 40  # docker's stop grace, with room to spare


# --- Interruptions -------------------------------------------------------------------------------


async def test_a_stall_is_interrupted(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    sim.stall_at(30)
    report, _ = await run(sim, job)
    assert report.outcome == "interrupted" and report.interrupted_by == "stall"
    assert report.reason == "Playback paused for more than 20 s."
    [take] = await results(sim, job)
    assert (take["title"], take["result"], take["reason"]) == ("Passage", "failed", "interrupted")
    assert report.counts.failed == 1


async def test_a_short_stall_saves_the_take_with_pause_fade(sim: Sim) -> None:
    album, job = await album_job(sim, [])
    sim.stall_at(30, for_s=5)
    report, _ = await run(sim, job)
    assert report.outcome == "partial"
    assert report.reason == "1 track failed: interrupted"
    assert report.still_missing == 1
    assert sim.recorded_titles(album) == set(TITLES[1:])
    finished = sim.events_of("track.finished")[0]
    assert (finished["pause_fade"], finished["counted"]) == (True, False)


async def test_a_takeover_is_interrupted_with_the_discarded_take(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    sim.take_over_at(30)
    report, _ = await run(sim, job)
    assert report.outcome == "interrupted" and report.interrupted_by == "takeover"
    assert report.takeover is not None and report.takeover.device.name == "Pixel 9"
    [take] = await results(sim, job)
    assert report.takeover.discarded_take_id == take["take_id"]
    assert (take["result"], take["reason"]) == ("failed", "interrupted")
    assert sim.mpris_calls() == []  # the player is left alone: the phone plays on
    assert sim.world.player.remote is not None and sim.world.player.remote.is_playing


async def test_the_client_going_away_is_interrupted(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    sim.at(30, sim.world.player.client_gone)
    report, _ = await run(sim, job)
    assert report.outcome == "interrupted" and report.interrupted_by == "stall"
    assert report.reason == "The Spotify client went away."


# --- Spytify's problems --------------------------------------------------------------------------


async def test_silent_capture_is_partial(sim: Sim) -> None:
    album, job = await album_job(sim, [])
    sim.capture_at(30, "silent")
    report, _ = await run(sim, job)
    assert report.outcome == "partial"
    [error] = errors(sim, "capture_silent")
    assert error["source"] == "spytify" and not error["withdrawn"]
    assert report.reason == error["message"]
    assert sim.recorded_titles(album) == set()
    [take] = await results(sim, job)
    assert (take["result"], take["reason"]) == ("skipped", "silent")
    assert sim.world.player.status == "Paused"


async def test_stalled_capture_is_partial(sim: Sim) -> None:
    _, job = await album_job(sim, [])
    sim.capture_at(30, "stalled")
    report, _ = await run(sim, job)
    assert report.outcome == "partial"
    assert errors(sim, "capture_stalled")
    [take] = await results(sim, job)
    assert (take["result"], take["reason"]) == ("failed", "interrupted")


async def test_a_low_volume_take_fails(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 1, 2, 3])
    sim.world.player.set_volume(50)
    sim.world.recorder.hang_methods = {"player.control"}  # full_volume never answers
    report, _ = await run(sim, job)
    assert report.outcome == "partial" and report.reason == "1 track failed: low volume"
    [take] = [row for row in await results(sim, job) if row["planned"]]
    assert (take["result"], take["reason"]) == ("failed", "low_volume")
    assert sim.events_of("track.finished")[0]["counted"] is False
    assert errors(sim, "player_volume_low")


async def test_an_unexpected_recorder_exit_fails_the_item(sim: Sim) -> None:
    _, job = await album_job(sim, [])

    def crash() -> None:
        session = sim.world.recorder.live()
        assert session is not None
        asyncio.ensure_future(session.kill())

    sim.at(30, crash)
    report, _ = await run(sim, job)
    assert report.outcome == "failed" and report.error_code == "recorder_exit"
    assert report.recorder_exit_code == -9
    assert errors(sim, "recorder_exit")
    assert sim.world.player.status == "Paused"


# --- Timeouts ------------------------------------------------------------------------------------


async def test_no_first_track_replays_at_30_s_and_gives_up_at_90_s(
    sim: Sim, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, job = await album_job(sim, [])
    monkeypatch.setattr(sim.world.player, "api_play", lambda *args, **kwargs: None)
    report, _ = await run(sim, job)
    assert report.outcome == "failed" and report.error_code == "recorder_timeout"
    assert plays(sim) == 2  # the play, and the replay at 30 s
    assert errors(sim, "recorder_timeout")[0]["fatal"] is True
    assert sim.recorder_sessions()[0].sigterms == 1
    assert 90 <= report.timings.phase_s["playing"] < 95


async def test_finishing_too_long_is_terminated(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 1, 2, 3], timeouts=Timeouts(finishing_extra_s=1.0))
    sim.world.recorder.exit_delay_s = 30.0  # it saves the last take, then hangs on
    report, _ = await run(sim, job)
    assert report.outcome == "done"
    session = sim.recorder_sessions()[0]
    assert session.sigterms >= 1
    assert sim.recorded_titles(album) == set(TITLES)


async def test_finishing_gets_sigterm_at_idle_exit_plus_40_s(
    sim: Sim, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The plan's timeouts, at their defaults: finishing may last --idle-exit (20 s) + 40 s, then
    SIGTERM; 45 s later the second one stops the recorder at once."""
    album, job = await album_job(sim, [0, 1, 2, 3])
    sim.world.recorder.exit_delay_s = 300.0  # it saves the last take, then hangs on
    sigterms_at: list[datetime] = []
    sigterm = SimRecorderSession.sigterm

    def timed_sigterm(session: SimRecorderSession) -> None:
        sigterms_at.append(sim.clock.now())
        sigterm(session)

    monkeypatch.setattr(SimRecorderSession, "sigterm", timed_sigterm)
    report, _ = await run(sim, job)
    assert report.outcome == "done"
    assert sim.recorded_titles(album) == set(TITLES)  # the last take was saved before
    finishing_at = report.timings.finishing_at
    assert finishing_at is not None
    after = [(at - finishing_at).total_seconds() for at in sigterms_at]
    assert after == pytest.approx([20 + 40, 20 + 40 + 45], abs=0.01)


async def test_the_item_maximum_is_terminated(sim: Sim) -> None:
    """1.25 × the planned length + 10 min, here 0.55 × + 0 = 149 s: session.stop {now: false}
    lets track 4's take finish (it ends at 184 s), and the session ends at the next track."""
    timeouts = Timeouts(item_max_factor=0.55, item_max_extra_s=0.0)
    album, job = await album_job(sim, [0, 2], timeouts=timeouts)
    report, _ = await run(sim, job)
    assert report.outcome == "partial"
    assert report.reason == "Stopped at the item's time limit."
    assert sim.recorded_titles(album) == set(TITLES) - {"Last Hours"}
    session = sim.recorder_sessions()[0]
    assert "session.stop" in session.calls and session.sigterms == 0
    assert sim.world.player.status == "Paused"


async def test_the_item_maximum_lets_a_long_take_finish(sim: Sim) -> None:
    """design.md: at the limit "the take playing is finished". Here 18 s into a 90 s take, so
    a SIGTERM ladder (45 s, then stop at once) would have cut it."""
    timeouts = Timeouts(item_max_factor=0.1, item_max_extra_s=0.0)
    album, job = await album_job(sim, [0, 2, 4], timeouts=timeouts)
    report, _ = await run(sim, job)
    assert report.outcome == "partial" and report.still_missing == 1
    assert sim.recorder_sessions()[0].sigterms == 0
    assert "Distant Peak" in sim.recorded_titles(album)
    take = (await results(sim, job))[0]
    assert (take["title"], take["result"]) == ("Distant Peak", "recorded")


async def test_the_item_maximum_terminates_a_recorder_that_doesnt_stop(
    sim: Sim, monkeypatch: pytest.MonkeyPatch
) -> None:
    """session.stop is answered but not heeded: SIGTERM once the take's end plus 30 s passed
    (18 s in, 72 s of the take left: at 120 s), then the usual ladder."""
    timeouts = Timeouts(item_max_factor=0.1, item_max_extra_s=0.0)
    album, job = await album_job(sim, [0, 2, 4], timeouts=timeouts)

    def unheeded(session: SimRecorderSession, now: bool) -> sp.SessionStopResult:
        return sp.SessionStopResult(recorded=0, skipped=0, stopping=True)

    monkeypatch.setattr(SimRecorderSession, "_session_stop", unheeded)
    sigterms_at: list[float] = []
    sigterm = SimRecorderSession.sigterm

    def timed_sigterm(session: SimRecorderSession) -> None:
        sigterms_at.append(sim.clock.monotonic())
        sigterm(session)

    monkeypatch.setattr(SimRecorderSession, "sigterm", timed_sigterm)
    started = sim.clock.monotonic()
    report, _ = await run(sim, job)
    assert report.outcome == "partial" and report.reason == "Stopped at the item's time limit."
    assert sigterms_at and sigterms_at[0] - started == pytest.approx(120, abs=3)
    assert "Distant Peak" in sim.recorded_titles(album)  # the take playing at the limit


async def test_the_socket_losing_the_last_events_is_read_from_the_events_file(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 1, 3])
    sim.world.recorder.lose_final_notifications = True
    report, _ = await run(sim, job)
    assert report.outcome == "done"
    assert report.counts.recorded == 2
    finished = [e["take_id"] for e in sim.events_of("track.finished")]
    assert len(finished) == 2  # the last one came from the --events file
    files = await sim.services.store.fetchval("SELECT COUNT(*) FROM files")
    assert files == 2


async def test_track_results_and_files_rows(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 1, 3])
    await run(sim, job)
    rows = await results(sim, job)
    assert [(r["position"], r["planned"], r["result"], r["reason"]) for r in rows] == [
        (2, 1, "recorded", None),
        (3, 0, "skipped", "duplicate"),
        (4, 1, "recorded", None),
        (None, 0, "skipped", "duplicate"),  # the phantom: no entry of the list
    ]
    tracks = {entry.track.name: entry.track.id for entry in album.entries if entry.track}
    assert rows[0]["track_id"] == tracks["Now And Then"]
    # The phantom of track 1 isn't a play of it: the Library's and Albums' last result of
    # track 1 mustn't be its duplicate skip (catalog/albums.py _last_results).
    assert (rows[3]["title"], rows[3]["track_id"]) == ("Passage", None)
    files = await sim.services.store.fetchall(
        "SELECT id, track_id, path, format, bitrate, counted, run_id FROM files ORDER BY id"
    )
    assert [dict(f) for f in files] == [
        {
            "id": rows[0]["file_id"],
            "track_id": tracks["Now And Then"],
            "path": "fakename/Elsewhere/03 - Now And Then.m4a",
            "format": "aac",
            "bitrate": 256,
            "counted": 1,
            "run_id": job.run_id,
        },
        {
            "id": rows[2]["file_id"],
            "track_id": tracks["Last Hours"],
            "path": "fakename/Elsewhere/05 - Last Hours.m4a",
            "format": "aac",
            "bitrate": 256,
            "counted": 1,
            "run_id": job.run_id,
        },
    ]
    item = await sim.services.store.fetchone(
        "SELECT last_backup_at, completed_at FROM items WHERE id = ?", (album.album.id,)
    )
    assert item["last_backup_at"] is not None and item["completed_at"] is not None


async def test_relayed_events_match_the_contract(sim: Sim) -> None:
    """The fields of contracts/events.md § Spytify, relayed, and § Warnings."""
    _, job = await album_job(sim, [0, 2, 4])
    sim.capture_at(100, "silent")
    await run(sim, job)
    shapes = {
        "track.started": {
            "run_id",
            "item_id",
            "take_id",
            "artist",
            "title",
            "album",
            "length_ms",
            "cover_url",
            "track_id",
            "position",
            "planned",
        },
        "track.finished": {
            "run_id",
            "item_id",
            "take_id",
            "track_id",
            "path",
            "duration_ms",
            "bytes",
            "counted",
            "low_volume",
            "pause_fade",
            "partial",
        },
        "track.skipped": {"run_id", "item_id", "take_id", "reason", "path", "track_id"},
        "session.state": {"run_id", "item_id", "state"},
        "error": {
            "source",
            "code",
            "message",
            "fatal",
            "withdrawn",
            "run_id",
            "item_id",
            "facts",
        },
    }
    for kind, keys in shapes.items():
        events = sim.events_of(kind)
        assert events, kind
        for data in events:
            assert set(data) == keys, kind
            if "run_id" in data:
                assert (data["run_id"], data["item_id"]) == (job.run_id, job.item_id)
    for data in sim.events_of("session.state"):
        assert data["state"] in ("idle", "waiting", "recording", "ad", "paused", "stopping")
    for data in sim.events_of("track.finished", "track.skipped"):
        assert data["path"] is None or not data["path"].startswith("/")


async def test_levels_are_relayed_only_while_recording(sim: Sim) -> None:
    _, job = await album_job(sim, [0, 1, 2, 3])
    sim.world.recorder.level_interval_s = 0.1
    seen: list[str | None] = []
    original = sim.services.bus.publish_level

    def watch(data: Any) -> None:
        seen.append(engine_session_state())
        original(data)

    engines: list[ItemEngine] = []

    def engine_session_state() -> str | None:
        return engines[0].live().session_state if engines else None

    sim.services.bus.publish_level = watch  # type: ignore[method-assign]
    host = RecordingHost()
    engine = ItemEngine(sim.services, job, host=host, control=ItemControl())
    engines.append(engine)
    task = asyncio.ensure_future(engine.run())
    await sim.advance_until(task.done, within=600)
    await task
    assert seen and set(seen) <= {"recording", "stopping"}


async def test_live_and_the_recorder_pid_while_it_records(sim: Sim) -> None:
    album, job = await album_job(sim, [0, 2, 4])
    engine = ItemEngine(sim.services, job, host=RecordingHost(), control=ItemControl())
    before = engine.live()
    assert before.phase == "planning" and before.tracks == () and engine.recorder_pid is None
    task = asyncio.ensure_future(engine.run())
    await sim.clock.advance(30)
    live = engine.live()
    assert live.phase == "playing" and live.session_state == "recording"
    assert live.now_playing is not None and live.now_playing.title == "Distant Peak"
    assert live.now_playing.position == 2
    assert [(t.position, t.state) for t in live.tracks] == [
        (1, "recorded"),
        (2, "recording"),
        (3, "recorded"),
        (4, "pending"),
        (5, "recorded"),
    ]
    assert engine.recorder_pid == sim.recorder_sessions()[0].pid
    await sim.advance_until(task.done, within=600)
    await task
    assert [(t.position, t.state) for t in engine.live().tracks] == [
        (1, "recorded"),
        (2, "recorded"),
        (3, "skipped_duplicate"),
        (4, "recorded"),
        (5, "skipped_duplicate"),
    ]
    assert engine.live().tracks[1].size_bytes and engine.recorder_pid is None
    assert engine.live().phase == "finishing"


async def test_the_m3u_and_stale_files_are_asked_for(
    sim: Sim, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, job = await album_job(sim, [0, 1, 2, 3])
    asked: list[str] = []

    async def write_m3u(item_id: str) -> None:
        asked.append(f"m3u {item_id}")

    async def cleanup_stale(folders: Any = None) -> None:
        asked.append(f"cleanup, recorders running: {sim.world.recorder.live() is not None}")

    monkeypatch.setattr(sim.services.files, "write_m3u", write_m3u)
    monkeypatch.setattr(sim.services.files, "cleanup_stale", cleanup_stale)
    report, _ = await run(sim, job)
    assert report.outcome == "done"
    assert asked == ["cleanup, recorders running: False", f"m3u {job.item_id}"]


async def test_a_stop_during_the_cleanup_starts_no_recorder(
    sim: Sim, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Between items only `.spytify/` is tidied (folders=[]); a stop that comes meanwhile is
    seen before spytifyd starts."""
    _, job = await album_job(sim, [])
    control = ItemControl()
    asked: list[Any] = []

    async def cleanup_stale(folders: Any = None) -> None:
        asked.append(folders)
        control.request_stop(StopRequest("after_track", "user"))

    monkeypatch.setattr(sim.services.files, "cleanup_stale", cleanup_stale)
    report, host = await run(sim, job, control=control)
    assert asked == [[]]
    assert report.outcome == "stopped"
    assert sim.recorder_sessions() == []
    assert host.phase_names()[-1] == "starting"


async def test_a_dropped_socket_stops_the_recorder_with_signals(
    sim: Sim, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spytifyd dropped us (512 lines behind) and records on: an after-track stop that can't
    reach it over the socket is a SIGTERM, which finishes the take as {now: false} would."""
    album, job = await album_job(sim, [])
    call = SimRecorderSession.call

    async def dropped(session: SimRecorderSession, method: str, *args: Any, **kwargs: Any) -> Any:
        if method == "session.stop":
            raise RecorderGone("session.stop: the recorder's socket is closed")
        return await call(session, method, *args, **kwargs)

    monkeypatch.setattr(SimRecorderSession, "call", dropped)
    control = stop_at(sim, 30, StopRequest("after_track", "window_end"))
    report, _ = await run(sim, job, control=control)
    assert report.outcome == "carried_over"
    assert sim.recorder_sessions()[0].sigterms == 1
    assert sim.recorded_titles(album) == {"Passage"}  # the take finished first
    assert report.timings.phase_s["playing"] < 120  # not left to play the album through


async def test_a_failing_m3u_writer_never_fails_the_item(
    sim: Sim, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, job = await album_job(sim, [0, 1, 2, 3])

    async def broken(*args: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(sim.services.files, "write_m3u", broken)
    monkeypatch.setattr(sim.services.files, "cleanup_stale", broken)
    report, _ = await run(sim, job)
    assert report.outcome == "done"


async def test_a_play_answering_404_is_unavailable_in_this_run_only(sim: Sim) -> None:
    """Our device is listed, so the context is what Spotify couldn't find. Whether the item is
    gone for good is the catalog refresh's to decide: `items` isn't marked (an album marked
    there would drop out of every later run)."""
    album, job = await album_job(sim, [])
    del sim.world.catalog.albums[album.album.id]  # gone from Spotify since the refresh
    report, _ = await run(sim, job)
    assert report.outcome == "unavailable"
    assert report.reason == "Spotify couldn't find it to play (404)."
    row = await sim.services.store.fetchone(
        "SELECT unavailable_at, unavailable_reason FROM items WHERE id = ?", (album.album.id,)
    )
    assert (row["unavailable_at"], row["unavailable_reason"]) == (None, None)


async def test_a_play_answering_404_for_our_gone_device_fails_the_run(
    sim: Sim, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spotify answers 404 "Device not found" too: the client went away after the pre-flight."""
    album, job = await album_job(sim, [])
    player = sim.world.player

    def play_on_a_gone_device(*args: Any, **kwargs: Any) -> None:
        player.client_gone()
        raise NotFound("Device not found", status=404)

    monkeypatch.setattr(player, "api_play", play_on_a_gone_device)
    report, _ = await run(sim, job)
    assert report.outcome == "failed"
    assert report.run_failure is not None and report.run_failure.reason == "device_missing"
    row = await sim.services.store.fetchone(
        "SELECT unavailable_at FROM items WHERE id = ?", (album.album.id,)
    )
    assert row["unavailable_at"] is None


async def test_the_timings_add_up(sim: Sim) -> None:
    _, job = await album_job(sim, [0, 2, 4])
    report, _ = await run(sim, job)
    timings = report.timings
    total = (timings.ended_at - timings.started_at).total_seconds()
    assert sum(timings.phase_s.values()) == pytest.approx(total, abs=0.01)
    assert timings.planned_ms == ELSEWHERE[1][1] + ELSEWHERE[3][1]
    assert timings.recorder_started_at and timings.first_track_at and timings.recorder_exit_at
    assert timings.to_json()["phase_s"]["playing"] > 180


# --- Steering, pure ------------------------------------------------------------------------------


def track(position: int, title: str | None = None) -> PlannedTrack:
    ident = f"{position:022d}"
    return PlannedTrack(
        position=position,
        track_id=ident,
        uri=f"spotify:track:{ident}",
        title=title or f"Track {position + 1}",
        artists=("A",),
        album="Album",
        duration_ms=90_000,
        key=f"a\x1ftrack {position + 1}",
    )


def missing_plan(missing: list[int], count: int = 5) -> ItemPlan:
    tracks = tuple(track(n) for n in range(count))
    return ItemPlan(
        mode="missing_only",
        tracks=tracks,
        missing=tuple(t for t in tracks if t.position in missing),
    )


def steer(steering: Steering, position: int, *, playing: bool = True) -> tuple[str, Any]:
    decision = steering.on_track_started(
        track_id=f"{position:022d}", title=f"Track {position + 1}", playing=playing
    )
    jump = decision.jump_to.position if decision.jump_to else None
    return decision.action, jump


def test_steering_plays_planned_tracks_and_jumps_over_the_rest() -> None:
    steering = Steering(missing_plan([1, 3]))
    first = steering.first_offset()
    assert first is not None and first.position == 1
    assert steer(steering, 1) == ("stay", None)
    assert steer(steering, 2) == ("jump", 3)
    assert steer(steering, 3) == ("stay", None)
    assert steer(steering, 4) == ("pause", None)


def test_steering_never_jumps_while_paused() -> None:
    steering = Steering(missing_plan([1, 3]))
    steering.first_offset()
    assert steer(steering, 0, playing=False) == ("stay", None)  # the phantom take


def test_steering_falls_back_to_the_title() -> None:
    steering = Steering(missing_plan([2]))
    decision = steering.on_track_started(
        track_id="relinked0000000000000ab", title="Track 3", playing=True
    )
    assert decision.action == "stay" and decision.planned and decision.position == 2


def test_steering_guards_against_a_planned_track_going_round() -> None:
    steering = Steering(missing_plan([1]))
    steering.first_offset()
    assert steer(steering, 1) == ("stay", None)
    assert steer(steering, 1) == ("steering_guard", None)
    assert steering.guarded


def whole(steering: Steering, title: str, *, playing: bool = True) -> str:
    return steering.on_track_started(track_id=None, title=title, playing=playing, artist="B").action


def test_steering_whole_items_and_the_loop_guard() -> None:
    """Bug 1's replay: the context plays again from its first track, every track a repeat in the
    order first heard. The second repeat in a row pauses it. The guard alone isn't a wrap: a
    run of repeats can also be a run the playlist lists twice."""
    steering = Steering(ItemPlan(mode="whole", tracks=(), missing=()))
    assert steering.first_offset() is None
    for title in ("One", "Two", "Three"):
        decision = steering.on_track_started(track_id=None, title=title, playing=True, artist="B")
        assert decision.action == "stay" and decision.planned
    first = steering.on_track_started(track_id=None, title="One", playing=True, artist="B")
    assert first.action == "stay" and first.repeat and not first.planned
    assert not steering.guarded
    assert whole(steering, "Two") == "loop_guard"
    assert steering.guarded and steering.wrapped is False


def test_steering_a_track_listed_twice_isnt_a_loop() -> None:
    """One repeat alone stays: Spytify skips it as a duplicate and skip-forward moves on, so the
    tracks after it are heard (the finding: [A, B, C, B, D, E] was cut at the second B)."""
    steering = Steering(ItemPlan(mode="whole", tracks=(), missing=()))
    actions = [whole(steering, title) for title in ("A", "B", "C", "B", "D", "E")]
    assert actions == ["stay"] * 6 and not steering.guarded
    steering = Steering(ItemPlan(mode="whole", tracks=(), missing=()))
    actions = [whole(steering, title) for title in ("A", "B", "A", "C")]
    assert actions == ["stay"] * 4
    assert not steering.guarded and steering.wrapped is False  # a repeat of track 1 isn't a wrap
    # Repeats that aren't in a row in the order first heard don't trip it either.
    steering = Steering(ItemPlan(mode="whole", tracks=(), missing=()))
    actions = [whole(steering, title) for title in ("A", "B", "C", "D", "C", "A", "D", "B")]
    assert actions == ["stay"] * 8 and not steering.guarded


def test_steering_the_end_of_the_context_is_a_wrap() -> None:
    steering = Steering(ItemPlan(mode="whole", tracks=(), missing=()))
    for title in ("One", "Two", "Three"):
        whole(steering, title)
    assert steering.is_first_track(track_id=None, title="One", artist="B")
    assert not steering.is_first_track(track_id=None, title="Three", artist="B")
    assert whole(steering, "Three", playing=False) == "stay"  # a phantom, not the first track
    assert steering.wrapped is False
    assert whole(steering, "One", playing=False) == "stay"  # the idle exit's phantom of track 1
    assert steering.wrapped is True
    paused = Steering(ItemPlan(mode="whole", tracks=(), missing=()))
    whole(paused, "One")
    paused.context_ended()  # the item engine saw the pause at the start of track 1
    assert paused.wrapped is True


def test_steering_the_first_track_of_a_missing_only_item() -> None:
    steering = Steering(missing_plan([3]))
    assert steering.is_first_track(track_id=f"{0:022d}", title="Track 1", artist="A")
    assert not steering.is_first_track(track_id=f"{3:022d}", title="Track 4", artist="A")
    assert steering.is_first_track(track_id=None, title="Track 1", artist="A")  # by title
    assert not Steering(ItemPlan(mode="missing_only", tracks=(), missing=())).is_first_track(
        track_id=None, title="Track 1", artist="A"
    )


def test_steering_a_planned_duplicate_jumps_on() -> None:
    steering = Steering(missing_plan([1, 3]))
    steering.first_offset()
    assert steer(steering, 1) == ("stay", None)
    decision = steering.on_planned_duplicate()  # Spytify had track 2 after all
    assert decision.action == "jump" and decision.jump_to is not None
    assert decision.jump_to.position == 3
    assert steer(steering, 3) == ("stay", None)
    assert steering.on_planned_duplicate().action == "pause"


def test_the_context_check_learns_liked_songs_alias() -> None:
    assert same_context(None, "spotify:album:x", liked_alias=None)
    assert not same_context("spotify:playlist:y", "spotify:album:x", liked_alias=None)
    check = ContextCheck("spotify:user:u:collection", liked=True)
    assert check.matches("spotify:playlist:37i9dQZF1FLikedSongs01")
    assert check.matches("spotify:playlist:37i9dQZF1FLikedSongs01")
    assert not check.matches("spotify:playlist:37i9dQZF1FOtherAlias01")
    assert not ContextCheck("spotify:album:x", liked=False).matches(
        "spotify:playlist:37i9dQZF1FLikedSongs01"
    )


# --- The outcome rules, pure (engine/item_outcome.py) --------------------------------------------


def test_the_outcome_rules_in_order() -> None:
    phone = Device("p", "Pixel 9", "Smartphone", True, False, 50)
    pixel = Takeover(device=phone, discarded_take_id=None)
    stop = StopRequest("now", "user")
    # 1: a failure during the play wins over everything.
    failed = Ending("failed", "refused", error_code="webapi")
    assert decide(AttemptFacts(failure=failed, still_missing=0, stop=stop)) == failed
    # 2: nothing planned is missing: done, whatever stopped it.
    assert decide(AttemptFacts(still_missing=0, stop=stop, takeover=pixel)).outcome == "done"
    # 3: the recorder exiting by itself.
    crashed = decide(AttemptFacts(still_missing=2, crashed="exit 1", stop=stop))
    assert (crashed.outcome, crashed.error_code) == ("failed", "recorder_exit")
    # 4: the stop's cause.
    assert decide(AttemptFacts(still_missing=1, stop=stop, takeover=pixel)).outcome == "stopped"
    window = StopRequest("after_track", "window_end")
    assert decide(AttemptFacts(still_missing=1, stop=window)).outcome == "carried_over"
    shutdown = decide(AttemptFacts(still_missing=1, stop=StopRequest("now", "shutdown")))
    assert (shutdown.outcome, shutdown.interrupted_by) == ("interrupted", "shutdown")
    # 5 and 6: interruptions.
    taken = decide(AttemptFacts(still_missing=1, takeover=pixel, stalled=True))
    assert (taken.outcome, taken.reason) == ("interrupted", "Playback moved to Pixel 9.")
    stalled = decide(AttemptFacts(still_missing=1, stalled=True, capture_problem="silent"))
    assert (stalled.outcome, stalled.interrupted_by) == ("interrupted", "stall")
    # 7 and 8.
    assert decide(AttemptFacts(still_missing=1)).reason == "1 track still missing."
    assert decide(AttemptFacts(mode="whole")).outcome == "done"


def test_the_partial_reasons() -> None:
    assert partial_reason(AttemptFacts(capture_problem="silence", hit_item_max=True)) == "silence"
    assert partial_reason(AttemptFacts(hit_item_max=True)) == "Stopped at the item's time limit."
    whole = AttemptFacts(mode="whole", context_moved=True)
    assert partial_reason(whole) == (
        "Playback moved on to another context before the playlist ended."
    )
    assert partial_reason(AttemptFacts(mode="whole", guard_cut_pass=True)) == (
        "The loop guard paused the player before the playlist ended."
    )
    assert partial_reason(AttemptFacts(context_moved=True)) is None  # missing_only: by tracks
    reasons = Counter({"low_volume": 2, "interrupted": 1})
    assert partial_reason(AttemptFacts(failed_reasons=reasons, still_missing=3)) == (
        "3 tracks failed: low volume, interrupted"
    )
