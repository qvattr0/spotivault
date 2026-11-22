# Spytify bugs

Every bug or gap in [Spytify](https://github.com/spytify/spytify) that affects spotivault, with what we do about it. Add one as soon as it's found, even before it's understood.

Each entry says:
- **Symptom:** what goes wrong.
- **Repro:** how to make it happen, with a fake-player script where possible.
- **Impact:** what it costs spotivault.
- **Workaround:** what the controller does instead.
- **Upstream:** the issue link, or the draft until it's posted.
- **Local patch:** none, planned or applied. A patch lives in `image/spytify/patches/`, is applied when the image builds `spytifyd` from source, and needs a fake-player regression test. It's only adopted with the user's OK, and dropped once upstream releases the fix.

## Summary

| # | Bug | Found in | Impact | Workaround | Upstream | Local patch |
|---|---|---|---|---|---|---|
| 1 | Skip-forward presses Next on a paused player at the end of an album | 2.0.1 | Playback restarts after the item ended; can loop | Skip-forward off for planned items | Draft | None |
| 2 | A restart within 2 s of the paused position isn't seen | 2.0.1 | The track isn't recorded | Seek to 0 before the recorder starts | Draft | None |
| 3 | `session.start` can't take an idle exit | 2.0.1 | The always-running recorder never saves the last track | One `--once --idle-exit` recorder per item | Comment on #758 to write | None |
| 4 | `--once` exits without deleting a held take's WAV | 2.0.1 (source) | Stale WAVs in `/music/.spytify/` | The controller removes stale WAVs between items | Not filed | None |
| 5 | Nothing cleans up leftover `.part` files after a crash | 2.0.1 (source) | Stale partial files next to recordings | The controller removes Spytify's stale `.part` files at start-up and after a recorder was killed | Not filed | None |
| 6 | One take is 3.6 s shorter than its cut points | 2.0.1 | A track may lose a few seconds | None yet | Not investigated | None |
| 7 | Tagged files ignore the umask | 2.0.2 (source) | Recorded AAC, MP3 and FLAC files are 0600: other NAS users and media servers can't read them | The controller sets the item's files to 0666 less UMASK | Not filed | None |
| 8 | The `--events` file holds every `level` record | 2.0.2 (source) | A long item's events file grows with its length: about 150 MB for 24 hours | The real reader leaves `level` lines out unparsed (`recorder/events_file.py`); the item engine parses only `track.*` | Not filed | None |

## 1. Skip-forward restarts a paused player at the end of an album

- **Symptom:** at the end of an album or playlist, Spotify loads track 1 again and pauses on it. Track 1 is already recorded, so Spytify announces a duplicate take and, with `recorder.skip_duplicates_forward=true`, presses **Next**. Next on a paused player starts playback again. Live, the whole album can replay, every track skipped as a duplicate. At the idle exit, a phantom `track.started` + `track.skipped` is emitted, and the Next can race the process exit.
- **Repro:** [prototype/upstream-issue-draft.md](../../prototype/upstream-issue-draft.md), with a fake-player scenario.
- **Impact:** playback after the item ended, inflated skip counts, possibly a loop.
- **Workaround:** run the recorder with `recorder.skip_duplicates_forward=false` and let the controller play only the missing tracks. Pause the player after the recorder exits. Count distinct tracks, not events. Followed playlists, which play whole with skip-forward on, get a loop guard: two tracks in a row coming round again in the order first heard pause the player (one repeat alone is a track the playlist lists twice). Code: the flag is set per item in `settings.py` (`build_recorder_settings`); `engine/item.py` pauses the player at the finish and again after the exit; `engine/steering.py` holds the loop guard.
- **Upstream:** draft, not posted.
- **Local patch:** none.

## 2. A restart within 2 s of the paused position isn't seen

- **Symptom:** when a session starts while the player is paused more than 300 ms into a track, Spytify treats it as already playing and won't record it. That's expected. But when the same track is then restarted from 0, Spytify ignores the `Seeked` if it lands within 2 s of the paused position (`seekSlackMs`). Paused at 980 ms, the restart is missed and the track plays unrecorded. Paused at 5.9 s, it's caught.
- **Repro:** [prototype/upstream-issue-restart-draft.md](../../prototype/upstream-issue-restart-draft.md).
- **Impact:** the retry of an interrupted item loses the track it was interrupted on.
- **Workaround:** pause (when something plays) and seek to 0 (`PUT /me/player/seek?position_ms=0`) before starting the recorder, so no track is "already playing". Code: `engine/item.py` `_prepare`.
- **Upstream:** draft, not posted.
- **Local patch:** none.

## 3. `session.start` can't take an idle exit

- **Symptom:** Spotify on Linux pauses at the end of a context and never reports Stopped. The only way a session ends on a pause is `IdleExit`, which only `spytifyd --once --idle-exit` sets. `session.start` over the socket takes only `single_track`, so the always-running daemon never finishes the last track.
- **Repro:** FINDINGS.md § End-of-item handling.
- **Impact:** a recorder process per item instead of one daemon.
- **Workaround:** `spytifyd --once --serve --idle-exit 20s` per item. Code: `recorder/process.py` `command_line`.
- **Upstream:** worth raising on #758 (the user's own feature request): accept `idle_exit` or `end_on_stop` in `session.start`.
- **Local patch:** none.

## 4. `--once` leaves a held take's WAV behind

- **Symptom:** a take stopped with `now` is held for `track.keep`, and its WAV is deleted when the next track is saved. `--once` exits without calling `Shutdown`, so that WAV stays in `<output>/.spytify/`. Spytify's start-up sweep only removes WAVs 10 minutes old or more.
- **Repro:** read from the 2.0.1 source (`keep.go`, `runOnce`). Not reproduced yet.
- **Impact:** stale WAVs in the music share.
- **Workaround:** the controller removes WAVs in `<music>/.spytify/` older than 60 s while no recorder runs. Code: `files.py` `cleanup_stale`, before each recorder starts (that folder only) and at start-up.
- **Upstream:** not filed.
- **Local patch:** none.

## 5. Leftover `.part` files after a crash

- **Symptom:** encoding writes `<final>.part` and renames it into place. Nothing removes a `.part` left by a crash.
- **Repro:** read from the 2.0.1 source (`finisher.go`). Not reproduced yet.
- **Impact:** partial files next to recordings.
- **Workaround:** the controller removes Spytify's own `.part` files (`<name>.mp3.part`, `.m4a.part`, `.flac.part`, `.wav.part`) older than 60 s while no recorder runs, walking the whole music folder: at start-up, and once after a recorder was killed by a signal (the first cleanup before an item at least 60 s later). Another program's `.part` files are left alone. Code: `files.py` `cleanup_stale` and `recorder_killed`.
- **Upstream:** not filed.
- **Local patch:** none.

## 6. A take shorter than its cut points

- **Symptom:** the Satie track (`--positions 10`, 22.4 s) was saved as 18.5 s, though its cut points span 22.1 s. Other takes are within about 3.7 s of the Web API length.
- **Repro:** FINDINGS.md § Playing only the missing tracks.
- **Impact:** possibly a few seconds missing from some tracks.
- **Workaround:** none yet.
- **Upstream:** not investigated.
- **Local patch:** none.

## 7. Tagged files ignore the umask

- **Symptom:** Spytify tags AAC, MP3 and FLAC files by having ffmpeg write a copy into a temporary file made with `os.CreateTemp` (mode 0600), then renames that copy into place. The final file is 0600 whatever the umask. Folders are made with mode 0755, so a umask of 000 still gives 0755. WAV files and their sidecars follow the umask.
- **Repro:** read from the 2.0.2 source (`internal/tag/writer.go`, called from `internal/core/finisher.go`). On the image's spytifyd 2.0.2, `test_umask_reaches_tagged_files` in `controller/tests/test_recorder_integration.py` is an expected failure (not strict), which is what the bug predicts. Why it fails hasn't been read by hand yet.
- **Impact:** on the NAS, other users and a media server running as another user can't read the music. `UMASK` (design.md § Container) never reaches it.
- **Workaround:** after each item, the controller gives the files that item saved mode 0666 less `UMASK` (`files.py` `fix_modes`). Folders are left at Spytify's 0755. Code: `fix_modes` is called from `engine/item.py` when the item ends, before its `.m3u` is written.
- **Upstream:** not filed.
- **Local patch:** none. A patch would chmod the tagged copy to 0666 less the umask before the rename.

## 8. The `--events` file holds every `level` record

- **Symptom:** spytifyd writes every event to `--events`, `level` included. Its level meter sends up to 10 a second while a track plays, so a long item's events file grows with the item's length.
- **Repro:** read from the 2.0.2 source (`cmd/spytifyd/main.go`, `eventSink`, a `json.Encoder` of `proto.Event`). Not measured on a real item yet.
- **Impact:** about 150 MB for 24 hours of recording, in `/config/logs/spytify/`, with no rotation (web-ui.md Q23). Parsing every record on the event loop at an item's end took about 100 ms for a 39-track item, before the fix. A 24-hour item's file would hold hundreds of thousands of records.
- **Workaround:** the real reader (`recorder/events_file.py`) leaves `level` lines out before parsing them, and the item engine (`engine/item.py`) parses only the `track.*` records. Nothing removes the file yet.
- **Upstream:** not filed.
- **Local patch:** none.
