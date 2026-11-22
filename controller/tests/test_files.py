"""files.py: the .m3u writer (paths, order, umask, renames, names) and the stale-file cleanup
(S6, history-files-metrics; plan § Verification, "the .m3u writer (`../` paths)").

The index is written by hand, as Spytify would: the file's path under the music folder, keyed by
Spytify's track key. The tracks, the item's list and the takes are rows of the schema.
"""

import dataclasses
import json
import os
import sqlite3
import stat
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI

from spotivault.files import (
    STALE_AFTER_S,
    CleanupResult,
    FilesService,
    m3u_entry,
    m3u_file_name,
)
from spotivault.matching import track_key
from spotivault.services import Services

PLAYLIST = "a" * 22
FOLLOWED = "b" * 22
ALBUM = "e" * 22
OTHER = "c" * 22


def at(day: int, hour: int = 0) -> str:
    return f"2026-11-{day:02d}T{hour:02d}:00:00.000Z"


def track_id(number: int) -> str:
    return f"{number:022d}"


# --- Seeding ------------------------------------------------------------------------------------


def seed_item(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    kind: str = "owned",
    name: str = "Mix",
    item_access: int = 1,
    m3u_path: str | None = None,
) -> None:
    artist = total = None
    if kind == "album":
        artist, total = "Artist", 3
    conn.execute(
        "INSERT INTO items (id, kind, uri, name, artist, total, added_by, added_at, tracked, "
        "item_access, m3u_path) VALUES (?, ?, ?, ?, ?, ?, 'user', ?, 1, ?, ?)",
        (
            item_id,
            kind,
            f"spotify:playlist:{item_id}",
            name,
            artist,
            total,
            at(1),
            item_access,
            m3u_path,
        ),
    )


def seed_track(conn: sqlite3.Connection, number: int, artists: list[str], name: str) -> str:
    tid = track_id(number)
    conn.execute(
        "INSERT INTO tracks (id, uri, name, artists, duration_ms, spytify_key, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            tid,
            f"spotify:track:{tid}",
            name,
            json.dumps(artists),
            180_000 + number * 1000,
            track_key(artists[0], name),
            at(1),
        ),
    )
    return tid


def seed_entry(conn: sqlite3.Connection, item_id: str, position: int, track: str | None) -> None:
    conn.execute(
        "INSERT INTO item_tracks (item_id, position, track_id, playable, unplayable_reason, "
        "added_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            item_id,
            position,
            track,
            1 if track else 0,
            None if track else "local",
            at(1),
        ),
    )


def seed_run(conn: sqlite3.Connection, started: str) -> int:
    cursor = conn.execute(
        "INSERT INTO runs (kind, trigger, state, outcome, started_at, ended_at, recorded, "
        "skipped_duplicate, skipped_other, failed, bytes_added) "
        "VALUES ('run', 'run_now', 'ended', 'completed', ?, ?, 0, 0, 0, 0, 0)",
        (started, started),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def seed_run_item(conn: sqlite3.Connection, run: int, item_id: str, mode: str) -> int:
    cursor = conn.execute(
        "INSERT INTO run_items (run_id, item_id, queue_pos, ran_order, state, mode) "
        "VALUES (?, ?, 1, 1, 'done', ?)",
        (run, item_id, mode),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def seed_take(
    conn: sqlite3.Connection,
    run_item: int,
    take: str,
    *,
    artist: str,
    title: str,
    started: str,
    result: str,
    reason: str | None,
    track: str | None = None,
) -> None:
    file_id = None
    if result == "recorded":  # a recorded take has its file (the schema's CHECK)
        run = conn.execute("SELECT run_id FROM run_items WHERE id = ?", (run_item,)).fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO files (spytify_key, path, bytes, duration_ms, format, counted, run_id, "
            "take_id, recorded_at) VALUES (?, ?, 1000, 180000, 'aac', 1, ?, ?, ?)",
            (track_key(artist, title), f"{artist}/{title}.m4a", run, take, started),
        )
        file_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO track_results (run_item_id, take_id, track_id, artist, title, planned, "
        "result, reason, file_id, started_at, finished_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
        (run_item, take, track, artist, title, result, reason, file_id, started, started),
    )


def write_index(music: Path, entries: list[tuple[str, Path]]) -> None:
    """Spytify's recorded.jsonl for these (key, file) pairs; the files must exist."""
    index = music / ".spytify" / "recorded.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"Key": key, "Path": str(path)}) for key, path in entries]
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_track_file(music: Path, rel: str) -> Path:
    path = music / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"audio")
    return path


# --- The pure helpers ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "file_name"),
    [
        ("Chill Mix", "Chill Mix"),
        ("Rock/Pop\\Mix", "Rock_Pop_Mix"),
        ("  ..hidden name  ", "hidden name"),
        ("", "Playlist"),
        ("...", "Playlist"),
        ("\x00\x1fbell\x7f", "bell"),
        ("tab\there", "tab here"),
    ],
)
def test_m3u_file_name(name: str, file_name: str) -> None:
    assert m3u_file_name(name) == file_name


def test_a_long_name_is_cut_to_200_bytes_at_a_character() -> None:
    name = m3u_file_name("é" * 150)  # 300 bytes in UTF-8
    assert name == "é" * 100
    assert len(name.encode("utf-8")) == 200


def test_m3u_entry_paths_are_relative_to_the_m3u(tmp_path: Path) -> None:
    music = tmp_path / "music"
    m3u = music / "Playlists" / "Mix.m3u"
    track = music / "fakename" / "Elsewhere" / "05 - Last Hours.m4a"
    assert m3u_entry(m3u, track) == "../fakename/Elsewhere/05 - Last Hours.m4a"
    assert m3u_entry(music / "a.m3u", music / "b" / "c.m4a") == "b/c.m4a"


# --- The .m3u


async def test_m3u_in_web_api_order(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    a = make_track_file(music_dir, "A/Album/01 - T0.m4a")
    c = make_track_file(music_dir, "B/Album/01 - T2.m4a")
    write_index(music_dir, [(track_key("A", "T0"), a), (track_key("B", "T2"), c)])
    services.matching.invalidate()

    def seed(conn: sqlite3.Connection) -> None:
        seed_item(conn, PLAYLIST, name="Mix")
        t0 = seed_track(conn, 0, ["A"], "T0")
        t1 = seed_track(conn, 1, ["A"], "T1")  # not recorded
        t2 = seed_track(conn, 2, ["B"], "T2")
        seed_entry(conn, PLAYLIST, 0, t0)
        seed_entry(conn, PLAYLIST, 1, t1)
        seed_entry(conn, PLAYLIST, 2, None)  # a local file: never listed
        seed_entry(conn, PLAYLIST, 3, t2)

    await services.store.transaction(seed)
    path = await services.files.write_m3u(PLAYLIST)

    assert path == music_dir / "Playlists" / "Mix.m3u"
    assert path.read_text(encoding="utf-8") == (
        "#EXTM3U\n"
        "#EXTINF:180,A - T0\n"
        "../A/Album/01 - T0.m4a\n"
        "#EXTINF:182,B - T2\n"
        "../B/Album/01 - T2.m4a\n"
    )
    row = await services.store.fetchone("SELECT m3u_path FROM items WHERE id = ?", (PLAYLIST,))
    assert row is not None and row["m3u_path"] == "Playlists/Mix.m3u"
    assert [p.name for p in path.parent.iterdir()] == ["Mix.m3u"]  # no temporary file left


async def test_m3u_of_a_whole_item_in_recorded_order(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    t0 = make_track_file(music_dir, "A/Album/01 - T0.m4a")
    t1 = make_track_file(music_dir, "A/Album/02 - T1.m4a")
    t2 = make_track_file(music_dir, "B/Album/01 - T2.m4a")
    write_index(
        music_dir,
        [(track_key("A", "T0"), t0), (track_key("B", "T2"), t2)],  # T1 was never recorded
    )
    services.matching.invalidate()
    assert t1.exists()  # a file the index doesn't know about: still not listed

    def seed(conn: sqlite3.Connection) -> None:
        seed_item(conn, FOLLOWED, kind="followed", name="Followed", item_access=0)
        ids = (
            seed_track(conn, 0, ["A"], "T0"),
            seed_track(conn, 1, ["A"], "T1"),
            seed_track(conn, 2, ["B"], "T2"),
        )
        run = seed_run(conn, at(1, 1))
        run_item = seed_run_item(conn, run, FOLLOWED, "whole")
        # Played in this order: T2 recorded, T0 a duplicate, T1 failed.
        seed_take(
            conn,
            run_item,
            "take-1",
            artist="B",
            title="T2",
            started=at(1, 1),
            result="recorded",
            reason=None,
            track=ids[2],
        )
        seed_take(
            conn,
            run_item,
            "take-2",
            artist="A",
            title="T0",
            started=at(1, 2),
            result="skipped",
            reason="duplicate",
            track=ids[0],
        )
        seed_take(
            conn,
            run_item,
            "take-3",
            artist="A",
            title="T1",
            started=at(1, 3),
            result="failed",
            reason="low_volume",
            track=ids[1],
        )

    await services.store.transaction(seed)
    path = await services.files.write_m3u(FOLLOWED)
    assert path is not None
    assert path.read_text(encoding="utf-8").splitlines() == [
        "#EXTM3U",
        "#EXTINF:182,B - T2",
        "../B/Album/01 - T2.m4a",
        "#EXTINF:180,A - T0",
        "../A/Album/01 - T0.m4a",
    ]


async def test_a_whole_items_clean_pass_order_wins(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    t0 = make_track_file(music_dir, "A/Album/01 - T0.m4a")
    t2 = make_track_file(music_dir, "B/Album/01 - T2.m4a")
    write_index(music_dir, [(track_key("A", "T0"), t0), (track_key("B", "T2"), t2)])
    services.matching.invalidate()

    def seed(conn: sqlite3.Connection) -> None:
        seed_item(conn, FOLLOWED, kind="followed", name="Followed", item_access=0)
        run = seed_run(conn, at(1, 1))
        run_item = seed_run_item(conn, run, FOLLOWED, "whole")
        seed_take(
            conn,
            run_item,
            "take-1",
            artist="B",
            title="T2",
            started=at(1, 1),
            result="recorded",
            reason=None,
        )
        # The last clean full pass played T0 before T2.
        for ordinal, (artist, title, key) in enumerate(
            [("A", "T0", track_key("A", "T0")), ("B", "T2", track_key("B", "T2"))], start=1
        ):
            conn.execute(
                "INSERT INTO observed_tracks (item_id, ordinal, spytify_key, artist, title, "
                "run_id) VALUES (?, ?, ?, ?, ?, ?)",
                (FOLLOWED, ordinal, key, artist, title, run),
            )

    await services.store.transaction(seed)
    path = await services.files.write_m3u(FOLLOWED)
    assert path is not None
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[2] == "../A/Album/01 - T0.m4a" and lines[4] == "../B/Album/01 - T2.m4a"


async def test_a_recorded_track_that_became_unplayable_stays_in_the_m3u(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    """Its label pulled it: the refresh stores it unplayable, but its file is still there, and
    a backup keeps it in the playlist (in Spotify's order)."""
    a = make_track_file(music_dir, "A/Album/01 - T0.m4a")
    b = make_track_file(music_dir, "A/Album/02 - T1.m4a")
    write_index(music_dir, [(track_key("A", "T0"), a), (track_key("A", "T1"), b)])
    services.matching.invalidate()

    def seed(conn: sqlite3.Connection) -> None:
        seed_item(conn, PLAYLIST, name="Mix")
        t0 = seed_track(conn, 0, ["A"], "T0")
        t1 = seed_track(conn, 1, ["A"], "T1")
        seed_entry(conn, PLAYLIST, 0, t0)
        conn.execute(
            "INSERT INTO item_tracks (item_id, position, track_id, playable, unplayable_reason, "
            "added_at) VALUES (?, 1, ?, 0, 'not_playable', ?)",
            (PLAYLIST, t1, at(1)),
        )

    await services.store.transaction(seed)
    path = await services.files.write_m3u(PLAYLIST)
    assert path is not None
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[2::2] == ["../A/Album/01 - T0.m4a", "../A/Album/02 - T1.m4a"]


async def test_a_file_the_controller_didnt_write_is_never_overwritten(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    """You made Playlists/Mix.m3u yourself: the playlist gets " (<id6>)", and a rename later
    leaves your file alone."""
    a = make_track_file(music_dir, "A/Album/01 - T0.m4a")
    write_index(music_dir, [(track_key("A", "T0"), a)])
    services.matching.invalidate()
    yours = music_dir / "Playlists" / "Mix.m3u"
    yours.parent.mkdir(parents=True)
    yours.write_text("#EXTM3U\nmine.mp3\n", encoding="utf-8")

    def seed(conn: sqlite3.Connection) -> None:
        seed_item(conn, PLAYLIST, name="Mix")
        seed_entry(conn, PLAYLIST, 0, seed_track(conn, 0, ["A"], "T0"))

    await services.store.transaction(seed)
    path = await services.files.write_m3u(PLAYLIST)
    assert path == music_dir / "Playlists" / f"Mix ({PLAYLIST[:6]}).m3u"
    assert yours.read_text(encoding="utf-8") == "#EXTM3U\nmine.mp3\n"
    assert await services.files.write_m3u(PLAYLIST) == path  # its own name from now on

    await services.store.execute("UPDATE items SET name = 'Other' WHERE id = ?", (PLAYLIST,))
    assert await services.files.write_m3u(PLAYLIST) == music_dir / "Playlists" / "Other.m3u"
    assert yours.exists() and not path.exists()  # only its own old file went

    for name in (f"Taken ({PLAYLIST[:6]}).m3u", f"Taken ({PLAYLIST}).m3u", "Taken.m3u"):
        (music_dir / "Playlists" / name).write_text("x", encoding="utf-8")
    await services.store.execute("UPDATE items SET name = 'Taken' WHERE id = ?", (PLAYLIST,))
    assert await services.files.write_m3u(PLAYLIST) is None  # no free name: none written


async def test_a_whole_items_m3u_adds_what_was_recorded_since_the_clean_pass(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    """Run 1 was a clean pass (T0, T2). Its owner added T3, which run 2 recorded in a pass
    that wasn't clean: T3 goes at the end, after the clean pass's order."""
    t0 = make_track_file(music_dir, "A/Album/01 - T0.m4a")
    t2 = make_track_file(music_dir, "B/Album/01 - T2.m4a")
    t3 = make_track_file(music_dir, "C/Album/01 - T3.m4a")
    keys = [track_key("A", "T0"), track_key("B", "T2"), track_key("C", "T3")]
    write_index(music_dir, list(zip(keys, [t0, t2, t3], strict=True)))
    services.matching.invalidate()

    def seed(conn: sqlite3.Connection) -> None:
        seed_item(conn, FOLLOWED, kind="followed", name="Followed", item_access=0)
        first = seed_run(conn, at(1, 1))
        seed_run_item(conn, first, FOLLOWED, "whole")
        for ordinal, (artist, title) in enumerate([("A", "T0"), ("B", "T2")], start=1):
            conn.execute(
                "INSERT INTO observed_tracks (item_id, ordinal, spytify_key, artist, title, "
                "run_id) VALUES (?, ?, ?, ?, ?, ?)",
                (FOLLOWED, ordinal, track_key(artist, title), artist, title, first),
            )
        second = seed_run(conn, at(2, 1))
        run_item = seed_run_item(conn, second, FOLLOWED, "whole")
        for take, artist, title, result, reason in [
            ("take-1", "A", "T0", "skipped", "duplicate"),
            ("take-2", "C", "T3", "recorded", None),
            ("take-3", "B", "T2", "skipped", "duplicate"),
        ]:
            seed_take(
                conn,
                run_item,
                take,
                artist=artist,
                title=title,
                started=at(2, 1),
                result=result,
                reason=reason,
            )

    await services.store.transaction(seed)
    path = await services.files.write_m3u(FOLLOWED)
    assert path is not None
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[2::2] == [
        "../A/Album/01 - T0.m4a",
        "../B/Album/01 - T2.m4a",
        "../C/Album/01 - T3.m4a",
    ]


async def test_nothing_is_written_for_an_album_a_switched_off_setting_or_no_recordings(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    def seed(conn: sqlite3.Connection) -> None:
        seed_item(conn, ALBUM, kind="album", name="Album")
        seed_item(conn, PLAYLIST, name="Mix")
        seed_entry(conn, PLAYLIST, 0, seed_track(conn, 0, ["A"], "T0"))

    await services.store.transaction(seed)
    assert await services.files.write_m3u(ALBUM) is None  # albums never get one
    assert await services.files.write_m3u(PLAYLIST) is None  # nothing recorded yet

    a = make_track_file(music_dir, "A/Album/01 - T0.m4a")
    write_index(music_dir, [(track_key("A", "T0"), a)])
    services.matching.invalidate()
    await services.settings.set_value("write_m3u", False)
    assert await services.files.write_m3u(PLAYLIST) is None
    assert not (music_dir / "Playlists").exists()


async def test_the_umask_applies_to_the_file_and_the_new_folder(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    a = make_track_file(music_dir, "A/Album/01 - T0.m4a")
    write_index(music_dir, [(track_key("A", "T0"), a)])
    services.matching.invalidate()

    def seed(conn: sqlite3.Connection) -> None:
        seed_item(conn, PLAYLIST, name="Mix")
        seed_entry(conn, PLAYLIST, 0, seed_track(conn, 0, ["A"], "T0"))

    await services.store.transaction(seed)
    # UMASK is for /music: 027 leaves the file 0640 and the new folder 0750, whatever this
    # process's own umask is.
    services.config = dataclasses.replace(services.config, umask="027")
    path = await services.files.write_m3u(PLAYLIST)
    assert path is not None
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o640
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o750


async def test_a_renamed_playlist_moves_its_m3u(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    a = make_track_file(music_dir, "A/Album/01 - T0.m4a")
    write_index(music_dir, [(track_key("A", "T0"), a)])
    services.matching.invalidate()

    def seed(conn: sqlite3.Connection) -> None:
        seed_item(conn, PLAYLIST, name="Mix")
        seed_entry(conn, PLAYLIST, 0, seed_track(conn, 0, ["A"], "T0"))

    await services.store.transaction(seed)
    old = await services.files.write_m3u(PLAYLIST)
    assert old is not None and old.exists()

    await services.store.execute("UPDATE items SET name = 'Mix Two' WHERE id = ?", (PLAYLIST,))
    new = await services.files.write_m3u(PLAYLIST)
    assert new == music_dir / "Playlists" / "Mix Two.m3u"
    assert new.exists() and not old.exists()
    row = await services.store.fetchone("SELECT m3u_path FROM items WHERE id = ?", (PLAYLIST,))
    assert row is not None and row["m3u_path"] == "Playlists/Mix Two.m3u"


async def test_the_second_item_with_the_same_name_gets_its_id_in_the_name(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    a = make_track_file(music_dir, "A/Album/01 - T0.m4a")
    write_index(music_dir, [(track_key("A", "T0"), a)])
    services.matching.invalidate()
    second = "bbbbbbbbbbbbbbbbbbbbbb"

    def seed(conn: sqlite3.Connection) -> None:
        seed_item(conn, PLAYLIST, name="Mix")
        seed_item(conn, second, name="Mix")
        track = seed_track(conn, 0, ["A"], "T0")
        seed_entry(conn, PLAYLIST, 0, track)
        seed_entry(conn, second, 0, track)

    await services.store.transaction(seed)
    first_path = await services.files.write_m3u(PLAYLIST)
    second_path = await services.files.write_m3u(second)
    assert first_path == music_dir / "Playlists" / "Mix.m3u"
    assert second_path == music_dir / "Playlists" / "Mix (bbbbbb).m3u"
    # Writing the first again keeps its own name.
    assert await services.files.write_m3u(PLAYLIST) == first_path


async def test_recorded_files_get_the_umask_mode(
    running_app: FastAPI, services: Services, music_dir: Path, tmp_path: Path
) -> None:
    # Spytify 2.0.2 leaves tagged files at 0600 (spytify-bugs.md #7): fix_modes gives them 0666
    # less UMASK. Missing files and files outside the music folder are skipped.
    tagged = make_track_file(music_dir, "A/Album/01 - T0.m4a")
    already = make_track_file(music_dir, "A/Album/02 - T1.m4a")
    outside = tmp_path / "outside.m4a"
    outside.write_bytes(b"x")
    for path in (tagged, outside):
        os.chmod(path, 0o600)
    os.chmod(already, 0o640)
    services.config = dataclasses.replace(services.config, umask="027")
    changed = await services.files.fix_modes(
        ["A/Album/01 - T0.m4a", str(already), "A/Album/03 - gone.m4a", str(outside), "../x"]
    )
    assert changed == 1
    assert stat.S_IMODE(os.stat(tagged).st_mode) == 0o640
    assert stat.S_IMODE(os.stat(already).st_mode) == 0o640
    assert stat.S_IMODE(os.stat(outside).st_mode) == 0o600
    services.config = dataclasses.replace(services.config, umask="000")
    assert await services.files.fix_modes(["A/Album/01 - T0.m4a"]) == 1
    assert stat.S_IMODE(os.stat(tagged).st_mode) == 0o666


async def test_the_files_service_is_on_services(running_app: FastAPI, services: Services) -> None:
    assert isinstance(services.files, FilesService)


# --- Stale files


def age(path: Path, services: Services, seconds: float) -> Path:
    """Sets the file's modification time to `seconds` before the fake clock's now."""
    moment = services.clock.now().timestamp() - seconds
    os.utime(path, (moment, moment))
    return path


async def test_cleanup_removes_stale_wavs_and_parts_only(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    spytify = music_dir / ".spytify"
    spytify.mkdir(exist_ok=True)
    old_wav = age(_touch(spytify / "old.wav"), services, STALE_AFTER_S * 2)
    fresh_wav = age(_touch(spytify / "fresh.wav"), services, 10)
    stray_wav = age(_touch(music_dir / "Artist" / "stray.wav"), services, STALE_AFTER_S * 2)
    old_part = age(_touch(music_dir / "Artist" / "Album" / "01.m4a.part"), services, 120)
    fresh_part = age(_touch(music_dir / "Artist" / "Album" / "02.m4a.part"), services, 5)
    finished = age(_touch(music_dir / "Artist" / "Album" / "03.m4a"), services, 999)
    index_file = age(_touch(spytify / "recorded.jsonl"), services, 999)

    result = await services.files.cleanup_stale()

    assert result == CleanupResult(wavs_removed=1, parts_removed=1)
    assert not old_wav.exists()
    assert not old_part.exists()
    # Kept: a WAV that may still be written, a part that's still growing, a WAV outside
    # .spytify/, and every finished file.
    assert fresh_wav.exists() and fresh_part.exists() and stray_wav.exists()
    assert finished.exists() and index_file.exists()


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


async def test_cleanup_removes_only_spytifys_own_leftovers(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    """Another program's partial download, and the WAVs of another Spytify recording into a
    subfolder of the share, are never touched however old (the share is the user's)."""
    old = STALE_AFTER_S * 100
    download = age(_touch(music_dir / "Downloads" / "set.webm.part"), services, old)
    bare = age(_touch(music_dir / "Downloads" / "mix.part"), services, old)
    nested_wav = age(_touch(music_dir / "Desk" / ".spytify" / "take.wav"), services, old)
    ours = [
        age(_touch(music_dir / "A" / f"01 - T.{ext}.part"), services, old)
        for ext in ("mp3", "m4a", "flac", "wav")
    ]
    result = await services.files.cleanup_stale()
    assert result == CleanupResult(wavs_removed=0, parts_removed=4)
    assert download.exists() and bare.exists() and nested_wav.exists()
    assert not any(path.exists() for path in ours)


async def test_between_items_only_spytifys_folder_is_tidied(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    """folders=[] (the item engine, before each recorder start): no walk of the music folder.
    After a recorder was killed, the first cleanup once its .part is stale walks it once."""
    part = age(_touch(music_dir / "Artist" / "Album" / "01.m4a.part"), services, 300)
    held = age(_touch(music_dir / ".spytify" / "held.wav"), services, 300)
    assert await services.files.cleanup_stale([]) == CleanupResult(1, 0)
    assert part.exists() and not held.exists()

    services.files.recorder_killed()
    assert await services.files.cleanup_stale([]) == CleanupResult(0, 0)  # not stale yet
    assert part.exists()
    clock = services.clock
    clock.set_now(clock.now() + timedelta(seconds=STALE_AFTER_S))  # type: ignore[attr-defined]
    assert await services.files.cleanup_stale([]) == CleanupResult(0, 1)
    assert not part.exists()
    late = age(_touch(music_dir / "Other" / "02.m4a.part"), services, 300)
    assert await services.files.cleanup_stale([]) == CleanupResult(0, 0)  # walked once only
    assert late.exists()


async def test_cleanup_of_some_folders_looks_only_there(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    written = age(_touch(music_dir / "Artist" / "Album" / "01.m4a.part"), services, 300)
    other = age(_touch(music_dir / "Other" / "02.m4a.part"), services, 300)
    spytify_wav = age(_touch(music_dir / ".spytify" / "held.wav"), services, 300)

    result = await services.files.cleanup_stale([music_dir / "Artist" / "Album"])

    assert result == CleanupResult(wavs_removed=1, parts_removed=1)
    assert not written.exists() and not spytify_wav.exists()
    assert other.exists()


async def test_cleanup_of_a_folder_that_is_gone_removes_nothing(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    result = await services.files.cleanup_stale([music_dir / "Gone" / "Folder"])
    assert result == CleanupResult(wavs_removed=0, parts_removed=0)


async def test_cleanup_with_nothing_to_tidy_says_zero(
    running_app: FastAPI, services: Services, music_dir: Path
) -> None:
    fresh = _touch(music_dir / "Artist" / "Album" / "03.m4a.part")
    age(fresh, services, 1)
    assert (await services.files.cleanup_stale()) == CleanupResult(0, 0)
    assert fresh.exists()
