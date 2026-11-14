# Draft: Spytify bug report

Draft for <https://github.com/spytify/spytify/issues>. Not posted.

---

**Title:** "Skip to next when already recorded" presses Next on a paused player at the end of an album, which restarts playback

**Version:** spytifyd 2.0.1 (Linux, `.deb`), Spotify 1.3.4 over MPRIS, PulseAudio capture.
**Settings:** `recorder.duplicates=skip`, `recorder.skip_duplicates_forward=true`; `spytifyd --once --serve --idle-exit 20s`.

## What happens

At the end of an album or playlist, Spotify loads the first track again and pauses on it. If that track was already recorded, which is always the case after a full run, Spytify announces it as a new take, skips it as a duplicate and presses **Next**. Next on a paused player starts the following track, so the player plays again after the item has ended.

`session_take.go` intends to prevent exactly this ("one paused at its start waits for Play, as next would make a paused player play the next track"), and so does `startFromInitial` ("a track changed or a session ended before then leaves no take"). I hit it on two paths.

### 1. Live, while the session runs

Spotify sends the new metadata (track 1) a moment before `PlaybackStatus=Paused`. The change is planned while the status is still `Playing`, it resolves, and the duplicate is announced and skipped forward. Excerpt from a 5-track album with tracks 1–4 recorded and track 5 recording:

```
05:31:28.430 debug cut for "Passage" at 88988 ms (kind 1, noticed at 89950 ms, ...)   <- track 1, loaded paused
05:31:28.431 MPRIS Next (dbus-monitor)
05:31:28 track.started Passage / track.skipped duplicate
05:31:28 session.state paused, then recording
05:31:28-30 Distant Peak, Now And Then, Seaside Stillness, Last Hours: started, skipped duplicate, Next each
05:31:30 session.state paused
```

The whole album played again, and every track was skipped as a duplicate. This can loop: each pass ends on track 1 loaded paused again. Here the second pass ended through path 2 instead.

### 2. At session end (idle exit)

When `--idle-exit` ends the session, `endOfPlayback()` calls `tryResolve(true)`. That forces the still-pending change to the paused track 1, and `cutAt` → `announce` runs for a take that never played:
- If the track was already recorded, it emits `track.started` and `track.skipped reason=duplicate`, and starts the Next goroutine. That goroutine races the process exit: in one of two runs, Spotify started playing track 2 after spytifyd had exited.
- If the track wasn't recorded, it emits `track.started` and `track.skipped reason=incomplete`.

Either way the session's "skipped" count includes a track that never played ("session … ended: 1 recorded, 1 skipped").

## Reproduce with the fake player (path 2, deterministic)

`record-b.json` records B once:

```json
{"name": "record B once", "seed": 1, "lead_in_ms": 200, "tail_ms": 500,
 "items": [{"artist": "Artist", "title": "B", "album": "Album", "track_number": 1, "length_ms": 3000, "art": "none"}]}
```

`end-on-b.json` plays A to its end, then loads B and stays paused at its start. `desync_ms` holds the Playing notice back past the end of the timeline, so the player stays paused:

```json
{"name": "A plays to its end; the player then loads B (already recorded) and pauses at its start",
 "seed": 1, "lead_in_ms": 200, "tail_ms": 0,
 "items": [
  {"artist": "Artist", "title": "A", "album": "Album", "track_number": 2, "length_ms": 3000, "art": "none"},
  {"artist": "Artist", "title": "B", "album": "Album", "track_number": 1, "length_ms": 3000, "art": "none",
   "pause_at_ms": 1, "pause_ms": 30000, "desync_ms": 60000}
 ]}
```

```sh
for t in record-b end-on-b; do
  spytifyd --once --idle-exit 5s --fake "$PWD/$t.json" --fake-realtime \
    --set output.dir=/tmp/fk/out --set recorder.duplicates=skip \
    --set recorder.skip_duplicates_forward=true --set output.group_by=none \
    --events "$t.events" --log-file "$t.log"
done
grep -v '"level"' end-on-b.events
```

The second run emits `track.started` and `track.skipped duplicate` for B after "player idle for 5s, ending the session", and logs "1 recorded, 1 skipped". Expected: B leaves no take, nothing is skipped, and no Next is sent.

## Suggested fix

- **Skip forward only once the duplicate is actually playing.** Wait until its first sound reaches the capture, or until `Playing` is confirmed after the change, rather than acting on the metadata change alone. A duplicate that plays starts making sound within a fraction of a second, so skipping stays just as fast.
- **At session end, a change that never played should leave no take.** Drop the pending change in `endOfPlayback()` instead of forcing it, as `startFromInitial` does for a track paused at its start.
