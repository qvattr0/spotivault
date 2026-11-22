"""tests/engine_sim.py: the simulator S6's engine tests run on works, before any engine does.

Each test drives the simulated world by hand where the item engine will drive it, so a builder
can trust the simulator's side of a failing engine test.
"""

import asyncio

from engine_sim import ELSEWHERE, Sim
from spotivault.fake.player import SimPlayer
from spotivault.ports import RecorderSpec


async def play(sim: Sim, uri: str, offset_uri: str | None = None) -> None:
    await sim.world.webapi.play(
        device_id=sim.world.catalog.our_device.id, context_uri=uri, offset_uri=offset_uri
    )


async def test_it_starts_set_up_with_an_empty_library(sim: Sim) -> None:
    services = sim.services
    assert await services.setup.is_complete()
    assert await services.connection.held_reason() is None
    status = await services.client.status()
    assert status.installed and status.running and status.logged_in
    assert sim.world.catalog.library_playlists() == []
    assert await services.storage.check()


async def test_an_album_and_a_playlist_reach_the_store(sim: Sim) -> None:
    album = sim.elsewhere()
    playlist = sim.playlist("Mine", tracks=3)
    followed = sim.playlist("Theirs", tracks=4, access="followed")
    await sim.refresh()
    await sim.add_album(album)
    await sim.add_playlist(followed)
    await sim.track(playlist.playlist.id)
    rows = await sim.services.store.fetchall("SELECT id, kind, tracked FROM items ORDER BY kind")
    kinds = {row["id"]: (row["kind"], row["tracked"]) for row in rows}
    assert kinds[album.album.id] == ("album", 1)
    assert kinds[playlist.playlist.id] == ("owned", 1)
    assert kinds[followed.playlist.id] == ("followed", 1)
    count = await sim.services.store.fetchval(
        "SELECT COUNT(*) FROM item_tracks WHERE item_id = ?", (album.album.id,)
    )
    assert count == len(ELSEWHERE)


async def test_prerecord_fills_the_index(sim: Sim) -> None:
    album = sim.elsewhere()
    sim.prerecord(album, [0, 2])
    assert sim.recorded_titles(album) == {"Passage", "Now And Then"}
    index = await sim.services.matching.index()
    assert len(index.paths) == 2


async def test_a_job_has_its_rows_and_short_paths(sim: Sim) -> None:
    album = sim.elsewhere()
    await sim.refresh()
    await sim.add_album(album)
    job = await sim.job(album.album.id)
    row = await sim.services.store.fetchone(
        "SELECT state, attempt FROM run_items WHERE id = ?", (job.run_item_id,)
    )
    assert (row["state"], row["attempt"]) == ("up_next", 1)
    assert job.context_uri == album.album.uri and job.kind == "album"
    assert job.socket_path.name == f"spytify-{job.run_id}-1.sock"
    again = await sim.job(album.album.id, attempt=2)
    assert again.run_item_id == job.run_item_id and again.attempt == 2


async def test_a_whole_album_records_by_hand(sim: Sim) -> None:
    """What the item engine will do for "nothing recorded yet", done by hand: pause, start the
    recorder, play from the first track, wait for the exit."""
    album = sim.elsewhere()
    await sim.refresh()
    await sim.add_album(album)
    job = await sim.job(album.album.id)
    settings = await sim.services.settings.recorder_settings("missing_only")
    spec = RecorderSpec(
        run_id=job.run_id,
        item_id=job.item_id,
        settings=settings,
        log_file=job.log_file,
        events_file=job.events_file,
        socket_path=job.socket_path,
        work_dir=job.work_dir,
        umask=sim.services.config.umask_bits,
    )
    session = await sim.services.ports.recorder.start(spec)
    await play(sim, job.context_uri, album.entries[0].track.uri)  # type: ignore[union-attr]
    await sim.advance_until(lambda: session.returncode is not None, within=900)
    assert await session.wait() == 0
    assert sim.recorded_titles(album) == {title for title, _ in ELSEWHERE}
    assert len(sim.music_files()) == len(ELSEWHERE)


async def test_stalls_and_takeovers_are_scripted_on_the_clock(sim: Sim) -> None:
    album = sim.elsewhere()
    player: SimPlayer = sim.world.player
    await play(sim, album.album.uri)
    sim.stall_at(5, for_s=3)
    await sim.clock.advance(5.5)
    assert player.status == "Paused"
    await sim.clock.advance(3)
    assert player.status == "Playing"
    sim.take_over_at(2)
    await sim.clock.advance(2.5)
    assert player.status == "Paused"
    player.resume_by_itself()  # playback is the phone's now: nothing happens
    assert player.status == "Paused"
    state = await sim.world.webapi.player_state()
    assert state is not None and state.device is not None and state.device.name == "Pixel 9"


async def test_mpris_metadata_can_lag_behind_the_track(sim: Sim) -> None:
    album = sim.elsewhere()
    sim.world.mpris.metadata_lag_s = 0.8
    await play(sim, album.album.uri)
    await sim.clock.advance(0.1)
    first = await sim.world.mpris.metadata()
    await sim.clock.advance(1)
    assert (await sim.world.mpris.metadata()).title == "Passage"  # type: ignore[union-attr]
    assert first is None or first.title != "Passage"
    async with sim.world.mpris.subscribe() as changes:
        await play(sim, album.album.uri, album.entries[2].track.uri)  # type: ignore[union-attr]
        assert (await sim.world.mpris.metadata()).title == "Passage"  # type: ignore[union-attr]
        await sim.clock.advance(1)
        change = await asyncio.wait_for(anext(aiter(changes)), 1)
        assert change.metadata is not None and change.metadata.title == "Now And Then"


async def test_bus_events_are_collected(sim: Sim) -> None:
    sim.services.bus.publish("backlog", {"x": 1})
    await sim.clock.settle()
    assert sim.events_of("backlog") == [{"x": 1}]
