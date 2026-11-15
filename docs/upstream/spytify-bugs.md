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
| 5 | Nothing cleans up leftover `.part` files after a crash | 2.0.1 (source) | Stale partial files next to recordings | The controller removes stale `.part` files between items | Not filed | None |
| 6 | One take is 3.6 s shorter than its cut points | 2.0.1 | A track may lose a few seconds | None yet | Not investigated | None |

## 1. Skip-forward restarts a paused player at the end of an album

- **Symptom:** at the end of an album or playlist, Spotify loads track 1 again and pauses on it. Track 1 is already recorded, so Spytify announces a duplicate take and, with `recorder.skip_duplicates_forward=true`, presses **Next**. Next on a paused player starts playback again. Live, the whole album can replay, every track skipped as a duplicate. At the idle exit, a phantom `track.started` + `track.skipped` is emitted, and the Next can race the process exit.
- **Repro:** [prototype/upstream-issue-draft.md](../../prototype/upstream-issue-draft.md), with a fake-player scenario.
- **Impact:** playback after the item ended, inflated skip counts, possibly a loop.
- **Workaround:** run the recorder with `recorder.skip_duplicates_forward=false` and let the controller play only the missing tracks. Pause the player after the recorder exits. Count distinct tracks, not events. Followed playlists, which play whole with skip-forward on, get a loop guard.
- **Upstream:** draft, not posted.
- **Local patch:** none.

## 2. A restart within 2 s of the paused position isn't seen

- **Symptom:** when a session starts while the player is paused more than 300 ms into a track, Spytify treats it as already playing and won't record it. That's expected. But when the same track is then restarted from 0, Spytify ignores the `Seeked` if it lands within 2 s of the paused position (`seekSlackMs`). Paused at 980 ms, the restart is missed and the track plays unrecorded. Paused at 5.9 s, it's caught.
- **Repro:** [prototype/upstream-issue-restart-draft.md](../../prototype/upstream-issue-restart-draft.md).
- **Impact:** the retry of an interrupted item loses the track it was interrupted on.
- **Workaround:** pause and seek to 0 (`PUT /me/player/seek?position_ms=0`) before starting the recorder, so no track is "already playing".
- **Upstream:** draft, not posted.
- **Local patch:** none.

## 3. `session.start` can't take an idle exit

- **Symptom:** Spotify on Linux pauses at the end of a context and never reports Stopped. The only way a session ends on a pause is `IdleExit`, which only `spytifyd --once --idle-exit` sets. `session.start` over the socket takes only `single_track`, so the always-running daemon never finishes the last track.
- **Repro:** FINDINGS.md § End-of-item handling.
- **Impact:** a recorder process per item instead of one daemon.
- **Workaround:** `spytifyd --once --serve --idle-exit 20s` per item.
- **Upstream:** worth raising on #758 (the user's own feature request): accept `idle_exit` or `end_on_stop` in `session.start`.
- **Local patch:** none.

## 4. `--once` leaves a held take's WAV behind

- **Symptom:** a take stopped with `now` is held for `track.keep`, and its WAV is deleted when the next track is saved. `--once` exits without calling `Shutdown`, so that WAV stays in `<output>/.spytify/`. Spytify's start-up sweep only removes WAVs 10 minutes old or more.
- **Repro:** read from the 2.0.1 source (`keep.go`, `runOnce`). Not reproduced yet.
- **Impact:** stale WAVs in the music share.
- **Workaround:** the controller removes `.spytify/*.wav` files older than 60 s while no recorder runs.
- **Upstream:** not filed.
- **Local patch:** none.

## 5. Leftover `.part` files after a crash

- **Symptom:** encoding writes `<final>.part` and renames it into place. Nothing removes a `.part` left by a crash.
- **Repro:** read from the 2.0.1 source (`finisher.go`). Not reproduced yet.
- **Impact:** partial files next to recordings.
- **Workaround:** the controller removes `.part` files older than 60 s while no recorder runs.
- **Upstream:** not filed.
- **Local patch:** none.

## 6. A take shorter than its cut points

- **Symptom:** the Satie track (`--positions 10`, 22.4 s) was saved as 18.5 s, though its cut points span 22.1 s. Other takes are within about 3.7 s of the Web API length.
- **Repro:** FINDINGS.md § Playing only the missing tracks.
- **Impact:** possibly a few seconds missing from some tracks.
- **Workaround:** none yet.
- **Upstream:** not investigated.
- **Local patch:** none.
