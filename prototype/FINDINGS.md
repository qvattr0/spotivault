# Feasibility findings

Status per risk: ✅ pass · ⚠️ works with a workaround · ❌ fail · ⏳ not tested yet.

**Verdict:** the design is feasible. A web UI can drive both applications end to end:
- **Spytify** through its JSON-RPC socket.
- **The Spotify client** through the Web API (listing the library, starting playback) and MPRIS (status, fallback playback).

One quirk shapes the controller: Spotify only *pauses* at the end of a playlist or album, and Spytify's always-running recorder then never finishes the last track. The fix is Spytify's own **`--once --idle-exit`** mode, one recorder process per item, which finishes the last track 20–25 s after the pause, with no client restart (row 11 and "End-of-item handling" below).

| # | Risk | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `probe` talks to `spytifyd` over JSON-RPC: `core.info`, `settings.set` and errors | ✅ | Tested on 2026-11-11 against `spytifyd` 2.0.1 with its fake player, then in the container. All 9 settings were applied, booleans sent as JSON `true`/`false` were accepted, and errors came back as JSON-RPC errors. Example: `player.control pause` on a stopped player returns `-32005 the player does not accept "pause"`, which is harmless. |
| 2 | Image builds on Ubuntu 24.04 with Spotify 1.3.4 (needs glibc ≥ 2.39) and the Spytify 2.0.1 `.deb` | ✅ | spotify-client 1.3.4.258, spytifyd v2.0.1, glibc 2.39, ffmpeg 6.1.1 (aac, flac, libmp3lame). Image is 1.95 GB. Gotcha: the Ubuntu 24.04 base image already has a user `ubuntu` with UID 1000, so it is removed before creating `app`. |
| 3 | Spotify client runs under Xvfb without a GPU (`--no-sandbox --disable-gpu`, `shm_size: 1g`) | ✅ | All 8 supervised services RUNNING. The client renders in Xvfb. PulseAudio logs harmless "no system bus" errors. |
| 4 | Spotify login works inside noVNC, without a browser hand-off, and survives container recreates | ✅ | **Scan code to log in**: a QR code scanned with the Spotify phone app. The window title reads "Spotify Premium". The **Log in** button would need an external browser, and none is installed. The login survived three client restarts (row 11). **But recreating the container logged it out.** That run changed both the hostname (to `LorneNAS`) and, through an image rebuild, `/etc/machine-id`. It also hit a crash first: Chromium's `SingletonLock` in `~/.cache/spotify` still named the old hostname, so the client quit at start. Fixes: the entrypoint clears `Singleton*` at start and keeps one machine ID in `/config/machine-id`, and the hostname is fixed in compose. **Confirmed after the fixes:** after logging in again, `docker compose up -d --force-recreate` (new container ID `0d5a96702c2b`) kept the login, and the device came back under the same name and device ID. So a fixed machine ID plus a fixed `DEVICE_NAME` is enough; the container's real hostname doesn't matter. An image rebuild no longer changes the machine ID, because it lives in `/config`. A rebuild alone wasn't re-tested. |
| 5 | Client publishes MPRIS, and Spytify's startup checks pass | ✅ | `probe info` passes all 8 checks: target, player_running, ffmpeg, encoder, capture = PulseAudio/parec, session_bus, player_heard, output_writable. The one warning is to turn crossfade and gapless playback off. |
| 6 | Web API PKCE with paste-back to a `127.0.0.1` redirect | ✅ | `probe auth --client-id` prints the URL. The user approves, the browser lands on an error page at `http://127.0.0.1:8888/callback?code=…`, and `probe auth --callback '<address>'` swaps the code for tokens. `GET /me` returns 200, and all 6 requested scopes were granted. The Client ID is permanent for the app's life. **Refresh tokens expire 6 months after authorization**, and refreshing doesn't extend that ([Spotify, 2026-06-18](https://developer.spotify.com/blog/2026-06-18-refresh-token-expiration)). The probe stores `authorized_at`. |
| 7 | Library endpoints answer under the 2026 dev-mode rules | ⚠️ | `GET /me/playlists` → 200 (18 playlists). `GET /me/albums` → 200 (124 albums). `GET /albums/{id}/tracks` → 200. `GET /playlists/{id}/items` → 200 for the user's own playlists; each entry's track is under `item`, no longer `track`. But the track list of a playlist the user **follows but doesn't own** returns **403** on both `/items` and `/tracks`, so its track count is unknown. Spotify-made playlists (e.g. Discover Weekly, visible in the client's sidebar) are not returned by `/me/playlists`. |
| 8 | Container's client appears in `/me/player/devices` and accepts `play` with a `context_uri` | ✅ | The client registers as a `Computer` device named after the container's **hostname** (`5a0daaa5aa5e` = the container ID), next to the user's other computers. The probe originally picked the wrong one ("first Computer"); it now matches its own hostname. **Device name is configurable:** set the `DEVICE_NAME` environment variable (default `spotivault`; the prototype compose sets `LorneNAS`). The client has no setting for its device name; it calls `gethostname()`. So `hostname-shim.c`, a tiny library preloaded into the Spotify process only (`LD_PRELOAD`), returns `$DEVICE_NAME` from `gethostname()`/`uname()`. That makes the name an ordinary environment variable, editable in the UGOS Docker app like the volume mappings, rather than Docker's `hostname:` option, which that app may not expose. Verified that the shim is loaded in the client's processes and returns `LorneNAS` while the real hostname is the container ID. `GET /me/player/devices` lists **`LorneNAS`** (id `bec8bd3c…`), and the name and ID stayed the same across a container recreate. Changing `DEVICE_NAME` may need a new login (row 4); not tested. `PUT /me/player/shuffle`, `/repeat` → 200; `PUT /me/player/play` → 204 for an album, an owned playlist and a followed playlist (even though that one's track list returned 403). The device ID stayed the same across client restarts. |
| 9 | MPRIS `OpenUri` starts a playlist (fallback path) | ✅ | `OpenUri string:spotify:playlist:…` started playback, MPRIS went to `Playing`, and the Web API reported that playlist as the context. MPRIS `Stop` is ignored: the status stays `Paused`. |
| 10 | Spytify records the first track when the session is started before playback | ✅ | The order pause → `full_volume` → `session.start` → `play` recorded track 1 from 0 ms. `full_volume` mattered: Spytify logged "player volume raised from 0% to 100% for the session". If the player is paused mid-track on something else when the session starts, Spytify treats that track as "already playing" and starts with the next one; switching context cuts it cleanly. |
| 11 | End of playlist is detected, and the last track is saved | ✅ | Detection works: the track count (when known), MPRIS `Paused`, or a context change. Saving the last track needs the right recorder mode; see **End-of-item handling** below. **`spytifyd --once --serve --idle-exit 20s`** (tested 2026-11-11 on the 1-track album "Panspermia"): Spotify paused at the end, 20 s later Spytify logged "player idle for 20s, ending the session", and it saved the full take (187.9 s of the 188 s track), tagged, then exited. No client restart. **`probe record` now works this way** (2026-11-13, 5-track album "Elsewhere", 7.6 min): all 5 tracks saved, the last one 87.4 s of 88 s, and the recorder exited 22 s after Spotify paused. Durations 86.1–99.3 s, each within ~3 s of the Web API's length, as before. |
| 12 | Re-run skips every track (`recorder.duplicates=skip` + `skip_duplicates_forward`) | ✅ | The re-run of a 2-track album skipped both as `duplicate` within 1 s; no files changed. In `--once` mode, the re-run of the 5-track "Elsewhere" skipped all 5 in 2 s, and the recorder exited 21 s later. The duplicate index is `/music/.spytify/recorded.jsonl`, in the output folder, so it travels with the music share. |
| 13 | AAC output is correct (`.m4a`, tags, cover) | ✅ | AAC-LC, 44.1 kHz stereo, ~285 kb/s total including the cover. Tags: title, artist, album_artist, album, track. 640×640 cover embedded. Durations 112.7 s and 134.1 s vs the Web API's 112.8 s and 134.3 s. Path at the time: `/music/<artist>/<album>/<artist> - <title>.m4a`. The default is now `/music/<artist>/<album>/<track> - <title>.m4a` (see "File naming" below). |
| 14 | Lossless offered by the Linux client (1.3.4) | ❌ | The user checked: the highest option is **Very high** (Ogg Vorbis 320 kbps), and **Lossless** isn't listed. `audio.play_bitrate_enumeration=4`. FLAC would only store a lossy stream in a bigger file. Default AAC 256; AAC 320 is the highest useful option. |

## End-of-item handling

Spotify on Linux pauses at the end of a playlist or album and never reports *Stopped*. In Spytify 2.0.1 (the latest release; the only commit since touches the macOS menu bar icon), a take is closed when one of these happens:
- the next track starts;
- `endOfPlayback()` runs, on any of:
  - the player reporting `Stopped`;
  - the metadata going empty;
  - the player quitting ("player interface gone");
  - the capture stream ending;
  - the **idle exit**: `onTick` in `internal/core/session_health.go` ends the session once the player isn't playing and there has been no sound for `IdleExit`.

`IdleExit` is set only by `spytifyd --once --idle-exit` (`cmd/spytifyd/main.go`). `session.start` over the socket takes only `single_track`, so the always-running recorder never gets it.

Every route checked, by reading the code and testing in the container:

| Route | Result |
| --- | --- |
| `spytifyd --once --serve --idle-exit 20s`, one process per item | ✅ **Use this.** The last take is saved 20–27 s after the pause (20 s idle + up to ~7 s encoding). `--serve` keeps the socket, so events and `settings.*` still work during the run. |
| Restart the Spotify client ("player gone") | ✅ Works, but restarts the client for every item; ~35 s. The fallback. |
| `session.stop` (graceful) | ❌ Waits for the current track to end, which never happens while paused. |
| `session.stop now` + `track.keep` | ❌ Saves the take as "*title* (partial)", which doesn't count as recorded, so the next run records it again. |
| `recorder.stop_with_player` | ❌ Fires only on *Stopped* or the player quitting. |
| `recorder.session_timer` | ❌ Lets the playing track finish first, so it hangs the same way. |
| MPRIS `Stop` | ❌ Ignored by Spotify, which stays `Paused`. |
| MPRIS `Next` at the end | ❌ Spotify stays paused on the same track at position 0; no track change, so no cut. Tested on a 1-track album. |
| Kill Spotify's PulseAudio stream | ❌ Spytify's capture waits for a new stream, so the capture doesn't end. |

**What `--once` changes for the controller:**
- **Lifecycle:** the controller starts `spytifyd --once --serve --idle-exit 20s` for each item, instead of supervisord running one daemon. Settings go in as `--set key=value` or into `config.toml`; there's no recorder socket between runs.
- **Mid-item pauses also end the session.** If playback pauses for more than 20 s (another device takes over, or the network stalls), the session ends early. The controller sees fewer tracks than expected and re-queues the item; tracks already recorded are skipped.
- **Playback that never starts:** the idle exit only counts after the player has played. If playback never starts, the controller must stop the process: SIGTERM finishes the current track, a second one stops at once.
- **Skip-forward restarts playback at the end of an item (a Spytify bug).** At the end of an album, Spotify loads track 1 again and pauses on it. Track 1 is always recorded by then, so Spytify takes it as a new duplicate take, and `skip_duplicates_forward` presses **Next**, which makes the paused player play. Confirmed on 2026-11-13 by reading the source, with the fake player, and with `dbus-monitor` on the real client. It shows up two ways:
  - **Live:** Spotify sends track 1's metadata a moment before `Paused`, so Spytify presses Next at once.
    - In a run where the last track was recorded fresh, the whole album played again, every track skipped as a duplicate (~3 s), and then it paused.
    - It could in principle loop.
  - **At the idle exit:** `endOfPlayback()` forces the pending change to track 1, so the session ends with a phantom `track.started` + `track.skipped duplicate`. If the track wasn't recorded, it's `skipped incomplete` instead.
    - The Next it starts races the process exit: once, Spotify started playing track 2 after the recorder had gone.
  - Spytify's own code comments say a duplicate "paused at its start waits for Play", so this is a bug. The issue draft, with a fake-player reproduction, is in [upstream-issue-draft.md](upstream-issue-draft.md).
  - **For the controller:**
    - Pause the player after the recorder exits.
    - Count distinct tracks recorded, not raw events: one run counted 10 skips for a 5-track album.
    - **Better, avoid the trigger (tested 2026-11-13, `probe record --only-missing`):** run the recorder with `--set recorder.skip_duplicates_forward=false`, and let the controller decide what plays. With skip-forward off, Spytify pressed no MPRIS Next in any run: `dbus-monitor` saw 0 Player method calls in two runs, and only the controller's own `Pause` in a third. The end-of-album duplicate of track 1 stays paused, and the phantom `track.started` + `track.skipped duplicate` at the idle exit is still there but harmless. Details in "Playing only the missing tracks" below.
    - **A `uris` list doesn't work:** the Linux client clears its player instead of playing. So the controller plays the context with `offset` at the first missing track and jumps over recorded ones itself.
    - **Seek to 0 before the recorder starts.** Spytify treats a track the player is paused on past 300 ms as "already playing" (`startFromInitial`, `freshStartMs`): it won't record it. An `offset` play of that same track doesn't change the track, so it stays unrecorded. That's exactly a retry after a mid-track interruption. One run lost track 5 this way: it played fully, with no `track.started`. The fix is `PUT /me/player/seek?position_ms=0` (plus a pause) before starting the recorder; the rerun recorded it. `probe record` now does this in both modes. **Cause:** Spotify does send MPRIS `Seeked` (~0 ms) on the restart, but Spytify ignores it when it lands within 2 s of the paused position (`seekSlackMs`). Paused at 980 ms, the restart was missed; paused at 5.9 s, it logged "started over" and took it. Bug report draft: [upstream-issue-restart-draft.md](upstream-issue-restart-draft.md).
    - **Read the events left after the recorder exits.** The last take's `track.finished` arrives as the process exits. The probe used to stop reading at the exit and counted 0 of 1.

**Upstream:** worth raising with Spytify on #758, the user's own feature request. The maintainer's suggested setup relies on `stop_with_player`, which never fires with Spotify on Linux because it pauses at the end. Accepting `idle_exit` (or `end_on_stop`) in `session.start`, or ending a session that stays paused past the track's length, would let the always-running recorder handle this too.

## Stopping at the first duplicate (Spytify #758)

The user's feature request #758 asks for an option that ends the session at the first track already recorded. The maintainer offered to add it, off by default, "for keeping a playlist up to date … with its newest tracks at the top". It isn't in 2.0.1.

For spotivault it only fits part of the library:
- **Albums:** a fixed track order. Stopping at the first duplicate is right for an album recorded before. But it breaks the "Interrupted · will retry" case: if tracks 1–3 were saved before the interruption, the retry stops at track 1 and never records track 4. Unless playback starts at the first missing track.
- **Playlists:** Spotify adds new tracks at the **bottom** by default, and `context_uri` playback follows the playlist's own order, not the client's "Recently added" sort. Playing from the top hits an old, recorded track first, so the option would end the session at once and miss every new track. It fits only playlists kept newest-first.
- **Followed playlists** (no track list, 403): the order is the owner's, so no assumption is safe.

**What the controller can do instead**, for albums and owned playlists:
- It has the track list from the Web API, and Spytify's duplicate index, `/music/.spytify/recorded.jsonl`. Entries are keyed by lowercased `artist␟title`, with no Spotify ID, so matching is by name.
- So it can compute the missing tracks itself and play only those. Almost nothing already recorded plays (about 2 s per gap), which is what #758 is after, without assuming any order.
- For followed playlists, it falls back to context playback with skip-forward.
- #758 is still a useful safety net for playlists the user keeps newest-first.

### Playing only the missing tracks (tested 2026-11-13)

**1. A `uris` list: ❌ doesn't play on the Linux client (1.3.4).** `PUT /me/player/play` with `{"uris": [...]}` returns 204, then:
- The client loads nothing, and MPRIS sends `CanPlay`, `CanPause` and `CanGoNext` = false.
- `GET /me/player` reports `item: null`, `context: null`, `is_playing: false`, and `actions.disallows` pausing, resuming and skipping.

The same happened with one URI or two, with and without `device_id`, with `offset` by position or URI, with `position_ms`, and with `open.spotify.com` links. `POST /me/player/queue` returned 200, but the queue stayed empty. A context play right after worked, so the client was fine; it just ignores `uris`. Whether this is the Linux client or the 2026 dev-mode API can't be told without another device, and the only other one is the user's PC. So the question of where a `uris` list ends doesn't arise.

MPRIS `OpenUri spotify:track:…` does play the track, but the Web API reports the album as its context, and at the end the same track **starts again**. That's no use either.

**2. `context_uri` + `offset`: ✅ works, so the controller does the skipping.**
- `PUT /me/player/play {"context_uri": album/playlist, "offset": {"position": first_missing}}` starts at the first missing track.
- On each `track.started`, the controller looks up the track in the item's list. It uses the Web API's `item.uri`, once its name agrees with the event's title (it can lag a moment).
- If the track is planned, the controller lets it play.
- If not, it jumps to the next planned track with another `offset` play, or pauses when none is left. The recorder's idle exit then ends the item.
- At the end of an album, Spotify still loads track 1 and pauses. With skip-forward off, nothing restarts it.

**Runs on "Elsewhere"** (5 × ~90 s). Recorder `spytifyd --once --serve --idle-exit 20s --set recorder.skip_duplicates_forward=false`, with `dbus-monitor` on `org.mpris.MediaPlayer2.Player` method calls:

| Missing | What happened | Saved | MPRIS calls | Recorder exit |
| --- | --- | --- | --- | --- |
| 2, 4 | Played 2. Track 3 started, and 2 s later the controller jumped to 4 (`skipped duplicate`). Track 5 started, and 1 s later the controller paused it. | 2 = 91.8 s (API 94.0), 4 = 91.9 s (API 93.8) | not captured (monitor misfired) | 20 s after the pause |
| 5, player left paused ~1 s into track 5 by the run before | **Lost:** "Last Hours is already playing"; it played fully, but no `track.started`. Before the seek-to-0 fix. | none | 0 | 20 s after the end |
| 5, player paused 4.9 s into track 5, with the seek-to-0 fix | Recorded from 0 ms. Album end → track 1 paused. Phantom `Passage` start + duplicate skip at the idle exit. | 5 = 87.3 s (API 88.4) | **0** | 20 s |
| 3, 5 | Played 3. Track 4 started, and 2 s later the controller jumped to 5. 5 ended, then the album-end wrap, then the phantom start at the idle exit. | 3 = 99.2 s (API 102.9), 5 = 87.3 s | **0** | 26 s |
| none | "5 tracks: 5 recorded … nothing missing: not starting a recorder" | — | — | — |

Excerpt (missing 3, 5):

```
06:00:59 PUT /me/player/play offset=2 -> 204
06:01:00 started  fakename - Now And Then (102s)
06:02:39 started  fakename - Seaside Stillness (93s)
06:02:41 plan: track 4 is not on the plan: jump to track 5 -> 204
06:02:42 skipped  …-003 reason=duplicate
06:02:42 started  fakename - Last Hours (88s)
06:02:44 finished …/fakename - Now And Then.m4a (3209 KiB, 99.2s)
06:04:06 session.state paused                      ← album end: track 1 loaded, paused
06:04:26 started  fakename - Passage (87s)         ← phantom at the idle exit
06:04:26 skipped  …-005 reason=duplicate           ← no Next: the player stays paused
06:04:31 finished …/fakename - Last Hours.m4a (2788 KiB, 87.3s)
06:04:34 recorder exited with code 0
06:04:34 plan [3, 5]: 2 distinct files saved, still missing none
```

**Cost of a jump:** about 2 s of the recorded track plays before the jump. It's never saved: Spytify classifies the track as a duplicate as soon as it starts, and with skip-forward off it just waits. An off-plan track that *isn't* recorded (only with `--positions`) gets a take that the controller's pause cuts. At the idle exit it is `skipped incomplete`, and no file is written (Satie track 11).

**3. Matching Spytify's index: ✅ the key can be built from the Web API.**
- **The key:** `trackKey` in `internal/core/records.go` is `strings.ToLower(strings.TrimSpace(artist)) + "\x1f" + strings.ToLower(strings.TrimSpace(title))`, with `info.Artist()` = the **first** MPRIS artist and `xesam:title`. There's no other normalization: no Unicode NFC, and no stripping of "feat." or "- Remaster".
- **The lookup** (`recordIndex.lookup`) only counts an entry while `os.Stat(path)` succeeds. Later lines win.
- **A second fallback:** `records.find` also counts a file at the path the naming settings would give, with or without a number prefix, even with no index entry.
- **MPRIS has only the first artist:** Spotify's `xesam:artist` holds just one name, so the key is always first artist + title. It doesn't matter how many artists the Web API lists. Checked on 3 multi-artist tracks:
  - Satie / Olga Scheps: `xesam:artist = ["Erik Satie"]`
  - Satie + 3 others: `["Erik Satie"]`
  - Bowie and Midge Ure "- 2010/2012 Remaster" titles: MPRIS title = Web API `name`, character for character.
- **So the controller's key is** `artists[0].name` + `name`, trimmed and lowercased the Go way:
  - Python's `str.lower()` differs for `İ`, and for a final `Σ` (`ς` vs Go's `σ`).
  - `strip()` also strips U+001C–U+001F.
  - `probe.py` has `track_key`/`go_lower`/`go_trim`.
- **Recorded and checked:** "Satie" track 10 (`--positions 10`, 22 s, 2 artists, accents, colon, apostrophe). Spytify wrote `erik satie␟cinq grimaces pour le songe d'une nuit d'été: iv. fanfaronnade`, and `web_track_key` gives the same string. The 5 "Elsewhere" keys match too.
- **When the keys disagree, the failure is safe:** the controller thinks a track is missing and plays it. Spytify then sees a duplicate, and the controller jumps on (about 2 s lost). For the opposite (the controller skips a track Spytify would record), the Web API name would have to match an index entry while the MPRIS title doesn't. That wasn't seen. Spytify's naming-path fallback errs the same safe way.
- **Unplayable tracks must be left out:** fetch the list with `market=from_token` and drop `is_playable: false`.
  - An `offset` at an unplayable track silently plays a different one: the Rachmaninoff "Introduction" (unplayable) loaded a Mendelssohn Octet movement instead.
  - An owned 300-track playlist has 20 unplayable tracks.
  - Local files and episodes are left out too.
- **Take length:** the Satie take is 18.5 s of 22.4 s, although its cut points span 22.1 s. Something inside the take was left out. Not looked into; the Elsewhere takes are all within ~3.7 s of the API length, as before.

**4. `uris` vs `context_uri` + `offset`.**

| | `uris` list | `context_uri` + `offset` + controller jumps |
| --- | --- | --- |
| Plays on the Linux client | ❌ No | ✅ Yes |
| Recorded tracks heard | none (in theory) | ~2 s each, at each gap, not saved |
| End of the plan | — | The controller pauses, or Spotify wraps to track 1 paused at the album end; the idle exit ends the run 20–26 s later |
| Web API calls | 1 | 1 + 1 per gap, plus 1 `GET /me/player` per track start |
| Context in `GET /me/player` | `null` | the album/playlist, so the "context moved on" (autoplay) check still works |

**Playlists:** the track-list side was checked on owned playlists: `/playlists/{id}/items` with the track under `item`, including unplayable and multi-artist entries. A followed playlist gave 403, so `--only-missing` falls back to whole-context playback. On a playlist, `offset` by position turned out to count only playable entries, so the probe now offsets by URI; a playlist recording that way is row 21.

## Implications for the design

- **Run engine, per item:**
  1. list the tracks (`market=from_token`), and compute the missing ones from `recorded.jsonl`; if none, skip the item (albums and owned playlists; followed playlists play whole, with skip-forward)
  2. pause, seek to 0, and shuffle and repeat off
  3. start `spytifyd --once --serve --idle-exit 20s --set recorder.skip_duplicates_forward=false`, which starts the session itself
  4. `full_volume` over its socket
  5. `PUT /me/player/play` with the context, `offset` **by URI** at the first missing track (row 19), and the `device_id` matched by `DEVICE_NAME`
  6. follow events; on a `track.started` that isn't planned (identified by MPRIS `mpris:trackid`, row 18), jump to the next missing track by URI, or pause if none is left
  7. the process exits 20–27 s after the end, with the last track saved; read its remaining events
  8. pause the player, in case it is playing
  9. recompute what's missing from the index, and re-queue the item if anything is
  10. on a timeout, SIGTERM the process; restarting the client is the fallback
- **Container:**
  - Keep the Connect device name stable with `DEVICE_NAME` (row 8) and the machine ID in `/config` (row 4).
  - Keep the client's own folder under `/config` so the login survives restarts.
- **Followed playlists:** no track list (403), but `/me/playlists` does give their `items.total` (row 20), so the UI can show "n / total recorded". End detection relies on MPRIS/context instead.
- **Spotify-made playlists** (Discover Weekly, Daily Mixes) can't be listed through the API.
  - Option: the user pastes their links, and playback works by URI.
  - This is untested for Spotify-made playlists.
- **Web API login** expires every 6 months. The UI must show the date and offer a reconnect.
- **File naming:** the default is `/music/<artist>/<album>/<track> - <title>.m4a`.
  - It's set with three Spytify settings: `output.group_by=artist/album`, `output.template={track} - {title}` and `output.prefix=none`.
  - `<artist>` is the main artist: the album's first artist, so collaborations share one folder.
  - `{track}` is two digits ("05"). A track with no number is saved as just `<title>.m4a`.
  - The album folder gets " (year)" added when the player gives a year, which the Linux client hasn't so far.
  - Checked on 2026-11-13 with the fake player: `Some Artist/Some Album/05 - Numbered Song.m4a` and `Some Artist/Some Album/No Number.m4a`.
  - Spytify's own app offers the same settings under Settings → Recorder: group by folders, file name template, prefix, underscores and diacritics. So the web UI can offer them too, through `settings.set` or `--set`.
  - Changing the naming later doesn't re-record anything, since Spytify finds recorded tracks by artist and title through its index. Renaming files outside Spytify does cause re-recording.
  - Files recorded before the change keep their old names.
- **Format:** no lossless on Linux, so offer AAC 256 (default), AAC 320 and MP3, and hide or label FLAC.
- **Working files:** Spytify keeps working WAVs and its duplicate index in `<output>/.spytify/`. A take stopped with `now` leaves its WAV there until the next track; the controller should clean up stale ones.

## M1 live validation (S0, 2026-11-15)

Step S0 of the M1 plan, on the prototype rebuilt with **Spytify 2.0.2**. Commands: `probe liked`, `probe offsets`, `probe playlists`, `probe prefs`, [tests/s0-fresh-client.sh](tests/s0-fresh-client.sh) and [tests/s0_spytify_fake.py](tests/s0_spytify_fake.py).

| # | Question | Status | Evidence |
| --- | --- | --- | --- |
| 15 | Spytify 2.0.2 behaves like 2.0.1 | ✅ | All 8 `core.info` checks pass. A real `--once` recording (row 21) and the fake-player runs (row 27) behave as before. The image was rebuilt from the same `/config`. |
| 16 | An image rebuild keeps the client's login (row 4's open point) | ✅ | Rebuilt image, same `/config`: `LorneNAS` listed in `GET /me/player/devices` with no new scan. |
| 17 | Liked Songs as a playback context (Q9) | ✅ | `context_uri` `spotify:user:<id>:collection` plays. `offset.position` 0 and 2 loaded `/me/tracks` entries 0 and 2 (newest first). **`GET /me/player` names the context `spotify:playlist:37i9dQZF1F…`**, a playlist alias, not the URI that was played, so a "context moved on" check must accept that alias. `spotify:collection:tracks` returns 204 but nothing plays; `spotify:user:<id>:collection:tracks` returns 400 "Invalid context uri". |
| 18 | MPRIS identifies the loaded track (D10) | ✅ | `mpris:trackid` is `/com/spotify/track/<id>`, and `<id>` is the playlist entry's (or `/me/tracks` entry's) own ID in every test. **`GET /me/player` reports a relinked ID for 4 of 9 playlist tracks, with or without `market`**, and `linked_from` was removed in 2026, so only MPRIS can tell which entry is loaded. |
| 19 | `offset.position` with unplayable entries | ❌ use `offset.uri` | On an owned 300-track playlist with 20 unplayable entries (`is_playable: false`), a position counts **only playable entries**: position 19 loaded entry 21 (entries 2 and 20 unplayable), 69 loaded 72. **`offset: {"uri": entry's uri}` loaded the exact entry at 9 of 9 positions**, including entry 289 after all 20 unplayable ones. |
| 20 | Followed playlists in `/me/playlists` | ⚠️ | `snapshot_id` is present on all 18 playlists, followed included. **The followed playlist also has `items.total` (35)**, although the migration guide says it's left out. `/items` still returns 403. `GET /playlists/{id}` returns 200 with name, owner, images, `snapshot_id` and `followers`, and no `items` field. Covers come from `image-cdn-ak.spotifycdn.com`. |
| 21 | `--only-missing` on an owned playlist, with a gap after an unplayable entry | ✅ | Plan: entries 225 and 227 (226 unplayable). Offset by URI started 225 (146.2 s saved of 148 s). Spotify skipped 226 by itself and played 227 (98.8 s of 98 s). 228 started, the probe identified it through MPRIS and paused at once; its take was `skipped incomplete` at the idle exit. The recorder exited 18 s after the pause. Spytify named the files with each track's **album** track number (`12 - Open Window.m4a`). |
| 22 | Field names under the 2026 rules (Risk) | ✅ | Only playlist entries moved to `item` (`/playlists/{id}/items`: `added_at, added_by, is_local, item, …`). **`/me/tracks` entries still use `track`**, `/me/albums` entries use `album` with `album.tracks.items`, and albums carry `release_date`. `/me/albums` and `/albums/{id}/tracks` answer 200 (Q11). |
| 23 | Installing the client at runtime (Q13) | ✅ | 17.6 s on Docker Desktop: InRelease verified with gpgv against the baked keyring (0.5 s), Packages by sha256, the 179 MB `.deb` downloaded (14.9 s) and checked, `dpkg-deb -x` (1.7 s, **387 MB unpacked**), `ldd` finds every library. **`http://repository.spotify.com` now answers 301 to `https://`**, so the installer must use https (curl without `-L` saved an empty file). |
| 24 | Signals that the client is logged in (Q2) | ✅ | A fresh profile on its own display and bus: **MPRIS name present** (`PlaybackStatus` Stopped), no `Users/` folder, window titles `Spotify` and `spotify` only. The logged-in client: `Users/<id>-user/`, and a window titled **`Spotify Premium`** (it shows "Artist - Title" while playing). So MPRIS alone doesn't mean logged in. |
| 25 | `--disable-dev-shm-usage` | ✅ | The fresh client started with the flag held 0 open files in `/dev/shm`; the logged-in client without it held 69. So the image can stop depending on `shm_size`. Rendering under a 64 MB `/dev/shm` is checked in S2. |
| 26 | Checklist settings in the prefs file (Q3) | ⚠️ | In `Users/<id>-user/prefs`: `audio.allow_downgrade=false` (Auto adjust), `audio.automix=false`, `audio.normalize_v2=false`, `audio.play_bitrate_enumeration=4` (Very high). Crossfade and gapless show only as `audio.crossfade_migrated_to_ps=true` and `audio.gapless_migrated_to_ps=true`: they moved to Spotify's servers. No key for autoplay, equalizer or mono; a toggle test (`probe prefs --save`, change, `--diff`) is still to do. |
| 27 | `spytifyd --fake`, `--events` and `SPYTIFY_CONFIG` | ✅ | A timeline of two tracks, then track 1 loaded paused (Spotify's end of album), with `--idle-exit 3s`: both takes saved as `Artist/Album/01 - One.m4a` and `02 - Two.m4a`; the phantom `track.started` + `track.skipped duplicate` of the paused track 1 shows up, as with the real client. **The `--events` file holds the last `track.finished`**, written as the process exits. `settings.set` over the socket is saved to `$SPYTIFY_CONFIG`; `--set` values aren't. Spytify's standalone `cmd/fakeplayer` is a real MPRIS player (Play, Pause, Next, Previous, SetPosition; OpenUri and Seek do nothing) but plays through `pw-play`, so it needs PipeWire. |

**What changes for the controller:**
- **Start and jump by `offset.uri`**, never by position.
- **Identify the loaded track by `mpris:trackid`.** Use the Web API's player state only for the context and the device.
- **Liked Songs:** play `spotify:user:<id>:collection`. Remember the context URI the Web API reports after the first play, and treat it as the same context.
- **`/me/tracks`** is read with `track`, and playlists with `item`.
- **Followed playlists** have a total from `/me/playlists`, so the backlog and the Library can count their tracks, but not their durations.
- **Login detection:** a `Users/*-user/` folder **and** a Spotify window titled anything but `Spotify`. The Web API device list confirms it.
- **The client installer** uses https and verifies InRelease, Packages and the `.deb`. Keeping a previous version costs another 387 MB in `/config`.

## Not tested yet

- A long playlist run, e.g. "Old-School", 16 tracks, about an hour. Multi-track runs are tested on a 5-track album and a 2-track playlist plan only.
- Autoplay off really stopping at the end of a playlist. Albums ended in `Paused`, as expected.
- Spotify-made playlists by URI.
- A linked playlist (public, not followed): metadata and playback (Q10).
- Which prefs keys autoplay, equalizer and mono write (Q3, row 26).
- Why the Satie take is 3.6 s shorter than its cut points.
- The NAS: UGOS Docker app fields, `/volume6/Music`, overnight runs.
