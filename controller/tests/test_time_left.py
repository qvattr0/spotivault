"""engine/time_left.py: a run's own time left. The pure sum against
contracts/vectors/run-time-left.json, and each item's missing tracks as stored, which must be what
planning.py would plan. The run engine's use of it is in test_engine_run.py; the item engine's
`ItemLive.left` in test_engine_item.py."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest

from contract import CONTRACTS
from engine_sim import Sim
from spotivault.clock import iso_ms
from spotivault.engine import time_left
from spotivault.engine.planning import plan_item
from spotivault.engine.time_left import ITEM_OVERHEAD_MS, item_estimates, work_out
from spotivault.engine.types import ItemLeft, MissingTrack

VECTORS = json.loads((CONTRACTS / "vectors" / "run-time-left.json").read_text(encoding="utf-8"))


def tracks_of(value: list[dict[str, Any]] | None) -> tuple[MissingTrack, ...] | None:
    if value is None:
        return None
    return tuple(MissingTrack(key=t["key"], duration_ms=t["duration_ms"]) for t in value)


def current_of(value: dict[str, Any] | None) -> ItemLeft | None:
    if value is None:
        return None
    return ItemLeft(
        take_ms=value["take_ms"], take_key=value["take_key"], tracks=tracks_of(value["tracks"])
    )


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["id"])
def test_run_time_left_vectors(case: dict[str, Any]) -> None:
    inp = case["input"]
    result = work_out(
        current_of(inp["current"]),
        [tracks_of(tracks) for tracks in inp["waiting"]],
        stop_mode=inp["stop_mode"],
        recorded=frozenset(inp["recorded"]),
        window_ms=inp["window_left_ms"],
    )
    expected = case["expected"]
    assert (result.ms, result.seconds, result.unknown_items) == (
        expected["ms"],
        expected["seconds"],
        expected["unknown_items"],
    )


def test_the_overhead_is_the_backlogs() -> None:
    assert ITEM_OVERHEAD_MS == 35_000


# --- Each item's missing tracks, as stored -----------------------------------------------------


async def test_an_items_missing_tracks_are_what_planning_plans(sim: Sim) -> None:
    album = sim.elsewhere()
    gaps = sim.world.catalog.add_album("Gaps", artist="Gap Band", tracks=4, unplayable=(1,))
    await sim.refresh()
    await sim.add_album(album)
    await sim.add_album(gaps)
    sim.prerecord(album, [0, 2])
    estimates = await item_estimates(
        sim.services, [(album.album.id, False), (gaps.album.id, False)]
    )
    for item_id in (album.album.id, gaps.album.id):
        plan = await plan_item(sim.services, await sim.job(item_id))
        assert plan.mode == "missing_only"
        expected = tuple(MissingTrack(t.key, t.duration_ms) for t in plan.missing)
        assert estimates[item_id] == expected
    assert [t.duration_ms for t in estimates[album.album.id] or ()] == [90_000, 93_000, 88_000]
    assert len(estimates[gaps.album.id] or ()) == 3  # the unplayable entry is left out


async def test_items_that_play_whole_have_no_length_and_gone_ones_nothing(sim: Sim) -> None:
    services = sim.services
    untracked = sim.playlist("Mine", tracks=3)
    followed = sim.playlist("Theirs", tracks=2, access="followed")
    removed = sim.album("Removed", 2, artist="Gone Band")
    unavailable = sim.album("Unavailable", 2, artist="Lost Band")
    unfetched = sim.album("Unfetched", 2, artist="New Band")
    await sim.refresh()
    await sim.track(untracked.playlist.id, False)
    await sim.add_playlist(followed)
    for album in (removed, unavailable, unfetched):
        await sim.add_album(album)
    await services.albums.remove(removed.album.id)
    now = iso_ms(sim.clock.now())
    await services.store.execute(
        "UPDATE items SET unavailable_at = ?, unavailable_reason = 'deleted' WHERE id = ?",
        (now, unavailable.album.id),
    )
    await services.store.execute(
        "UPDATE items SET catalog_fetched_at = NULL WHERE id = ?", (unfetched.album.id,)
    )
    ids = [
        untracked.playlist.id,
        followed.playlist.id,
        removed.album.id,
        unavailable.album.id,
        unfetched.album.id,
    ]
    estimates = await item_estimates(services, [(item_id, False) for item_id in ids])
    assert estimates == {
        untracked.playlist.id: None,  # not tracked: its stored list may be old, it plays whole
        followed.playlist.id: None,  # no item access, never fully passed: plays whole
        removed.album.id: (),
        unavailable.album.id: (),
        unfetched.album.id: None,  # no list fetched: plays whole
    }
    assert await item_estimates(services, [("nosuchitem000000000000", False)]) == {}


async def test_a_followed_playlist_up_to_date_by_d13_adds_nothing(sim: Sim) -> None:
    catalog = sim.world.catalog
    entries = [catalog.entry(title, artist="Band", duration_ms=60_000) for title in ("A", "B")]
    playlist = sim.playlist("Theirs", entries, access="followed")
    await sim.refresh()
    await sim.add_playlist(playlist)
    await sim.refresh()  # the listing stores its snapshot_id (D13)
    item_id = playlist.playlist.id
    job = await sim.job(item_id)
    report = await sim.run_item(job)
    assert report.clean_full_pass
    assert await item_estimates(sim.services, [(item_id, False)]) == {item_id: ()}
    # This run's refresh couldn't read its snapshot_id: D13 can't skip it, it plays whole.
    assert await item_estimates(sim.services, [(item_id, True)]) == {item_id: None}


async def test_the_lists_are_walked_on_a_worker_thread(
    sim: Sim, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Walking the queue's track lists touches most of the library on Run now, and it's done
    again after each item: on a big library it would hold up the event loop, so it runs on a
    worker thread, as the backlog's walk does (design.md § Stack)."""
    album = sim.elsewhere()
    await sim.refresh()
    await sim.add_album(album)
    on_threads: list[str] = []
    to_thread = asyncio.to_thread

    async def spy(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        on_threads.append(getattr(func, "__name__", repr(func)))
        return await to_thread(func, *args, **kwargs)

    monkeypatch.setattr(time_left.asyncio, "to_thread", spy)
    estimates = await item_estimates(sim.services, [(album.album.id, False)])
    assert len(estimates[album.album.id] or ()) == 5
    assert "_estimates_from_rows" in on_threads
