# Draft: Spytify bug report (restart of an "already playing" track)

Draft for <https://github.com/spytify/spytify/issues>. Not posted. Copy everything below the line; the first line is the title.

---

**Title:** A track paused less than 2 s in when the session starts is never recorded, even after it's played again from the start

**Version:** spytifyd 2.0.1 (Linux, `.deb`), Spotify 1.3.4 over MPRIS, PulseAudio capture. Same with `spytifyd --once` and with `session.start` on the always-running daemon.

## What happens

When a session starts while the player is paused on a track more than 300 ms in, Spytify logs `"<title>" is already playing; recording starts with the next track` and doesn't record it. That's expected.

If that same track is then played again **from the start**, it should be recorded. That works when the player was paused **5.9 s** in: Spytify logs "started over" and starts a take. But when it was paused **1 s** in, the restart goes unnoticed: the track plays to its end and no take is made.

This is the usual way to resume an interrupted recording: the player was left paused shortly after a track began, and the next run starts that track over (e.g. Web API `PUT /me/player/play` with the album and an `offset` at that track).

## Evidence

The same steps each time, on a real Spotify client:
1. Play track 5 of an album.
2. Pause after *n* seconds.
3. Start `spytifyd --once --idle-exit 8s`.
4. Restart track 5 from 0 with `PUT /me/player/play {"context_uri": …, "offset": {"position": 4}, "position_ms": 0}`.

The track was already recorded, so a take shows up as `track.started` + `track.skipped duplicate`. That's enough to tell whether a take started.

**Paused at 980 ms:** no take.

```
06:45:46 info  "Last Hours" is already playing; recording starts with the next track
             (restart from 0 at 06:45:49: no "started over", no track.started)
06:46:04 info  session 20261113-064546 ended: 0 recorded, 0 skipped
```

**Paused at 5885 ms:** take started.

```
06:46:13 info  "Last Hours" is already playing; recording starts with the next track
06:46:17 debug "Last Hours" started over: the player is at 9 ms
             track.started Last Hours / track.skipped duplicate
06:46:30 info  session 20261113-064613 ended: 0 recorded, 1 skipped
```

In an earlier run the track wasn't recorded yet, and the player had been left paused ~1 s in. The whole 88 s track played after the restart, with no `track.started`, and the session ended "0 recorded, 1 skipped". The one skip was the next track, loaded at the album's end.

`dbus-monitor` shows that Spotify does announce the restart: the `offset` play sends `org.mpris.MediaPlayer2.Player.Seeked` with a position of 0–4 ms (`int64 2000`, `int64 4000` µs).

## Cause

The restart is the `Seeked` signal, and `internal/meta/mpris.go` drops it:

```go
want := m.clock.read(at)          // paused: the position at the pause, e.g. 980 ms
...
if want >= 0 && ms-want <= seekSlackMs && want-ms <= seekSlackMs {   // seekSlackMs = 2000
    return nil                     // |0 − 980| ≤ 2000: taken as the player restating its position
}
if us < 1_500_000 {
    return []Event{{Kind: TrackChanged, Track: last, PositionMs: ms, Restart: true}}
}
```

The slack is there so a player restating its position isn't taken as a seek. But a jump back to the start of a track paused under ~2 s in always falls inside it. So no `TrackChanged{Restart: true}` reaches `onTrack`, and the ghost segment from `startFromInitial` stays current for the whole track.

Paused 300 ms – 2 s in is the gap: under 300 ms, `startFromInitial` waits for Play instead of making a ghost (`freshStartMs`), and over 2 s, the `Seeked` gets past the slack.

## Suggested fix

Either of these would do:
- **In the `Seeked` handler:** take a jump to under `restartToMs` as a restart whenever the clock says the item was clearly past it, e.g. more than `freshStartMs` (300 ms), whatever `seekSlackMs` says. A position restated near 0 stays inside that margin.
- **In the core:** when the current segment is a ghost from `startFromInitial`, take any `Seeked` back near 0 as a restart. Nothing of the ghost is being recorded, so treating a restatement as a restart costs nothing.

**Workaround for now:** seek the player to 0 (`PUT /me/player/seek?position_ms=0`) *before* starting the session. `startFromInitial` then sees a track paused at its start and records it once it plays.
