# Feasibility findings

Status per risk: ✅ pass · ⚠️ works with a workaround · ❌ fail · ⏳ not tested yet.

**Verdict:** the design is feasible. A web UI can drive both applications end to end:
- **Spytify** through its JSON-RPC socket.
- **The Spotify client** through the Web API (listing the library, starting playback) and MPRIS (status, fallback playback).

One workaround is needed: Spotify only *pauses* at the end of a playlist or album, so the controller restarts the client to make Spytify finish the last track (row 11).

| # | Risk | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `probe` talks to `spytifyd` over JSON-RPC: `core.info`, `settings.set` and errors | ✅ | Tested on 2026-11-11 against `spytifyd` 2.0.1 with its fake player, then in the container. All 9 settings were applied, booleans sent as JSON `true`/`false` were accepted, and errors came back as JSON-RPC errors. Example: `player.control pause` on a stopped player returns `-32005 the player does not accept "pause"`, which is harmless. |
| 2 | Image builds on Ubuntu 24.04 with Spotify 1.3.4 (needs glibc ≥ 2.39) and the Spytify 2.0.1 `.deb` | ✅ | spotify-client 1.3.4.258, spytifyd v2.0.1, glibc 2.39, ffmpeg 6.1.1 (aac, flac, libmp3lame). Image is 1.95 GB. Gotcha: the Ubuntu 24.04 base image already has a user `ubuntu` with UID 1000, so it is removed before creating `app`. |
| 3 | Spotify client runs under Xvfb without a GPU (`--no-sandbox --disable-gpu`, `shm_size: 1g`) | ✅ | All 8 supervised services RUNNING. The client renders in Xvfb. PulseAudio logs harmless "no system bus" errors. |
| 4 | Spotify login works inside noVNC, without a browser hand-off, and survives container recreates | ✅ | **Scan code to log in**: a QR code scanned with the Spotify phone app. The window title reads "Spotify Premium". The **Log in** button would need an external browser, and none is installed. The login survived three client restarts (row 11). **But recreating the container logged it out.** That run changed both the hostname (to `LorneNAS`) and, through an image rebuild, `/etc/machine-id`. It also hit a crash first: Chromium's `SingletonLock` in `~/.cache/spotify` still named the old hostname, so the client quit at start. Fixes: the entrypoint clears `Singleton*` at start and keeps one machine ID in `/config/machine-id`, and the hostname is fixed in compose. **Confirmed after the fixes:** after logging in again, `docker compose up -d --force-recreate` (new container ID `0d5a96702c2b`) kept the login, and the device came back under the same name and device ID. So a fixed machine ID plus a fixed `DEVICE_NAME` is enough; the container's real hostname doesn't matter. An image rebuild no longer changes the machine ID, because it lives in `/config`. A rebuild alone wasn't re-tested. |
| 5 | Client publishes MPRIS, and Spytify's startup checks pass | ✅ | `probe info` passes all 8 checks: target, player_running, ffmpeg, encoder, capture = PulseAudio/parec, session_bus, player_heard, output_writable. The one warning is to turn crossfade and gapless playback off. |
| 6 | Web API PKCE with paste-back to a `127.0.0.1` redirect | ✅ | `probe auth --client-id` prints the URL. The user approves, the browser lands on an error page at `http://127.0.0.1:8888/callback?code=…`, and `probe auth --callback '<address>'` swaps the code for tokens. `GET /me` returns 200, and all 6 requested scopes were granted. The Client ID is permanent for the app's life. **Refresh tokens expire 6 months after authorization**, and refreshing doesn't extend that ([Spotify, 2026-06-18](https://developer.spotify.com/blog/2026-06-18-refresh-token-expiration)). The probe stores `authorized_at`. |
| 7 | Library endpoints answer under the 2026 dev-mode rules | ⚠️ | `GET /me/playlists` → 200 (18 playlists). `GET /me/albums` → 200 (124 albums). `GET /albums/{id}/tracks` → 200. `GET /playlists/{id}/items` → 200 for the user's own playlists; each entry's track is under `item`, no longer `track`. But the track list of a playlist the user **follows but doesn't own** returns **403** on both `/items` and `/tracks`, so its track count is unknown. Spotify-made playlists (e.g. Discover Weekly, visible in the client's sidebar) are not returned by `/me/playlists`. |
| 8 | Container's client appears in `/me/player/devices` and accepts `play` with a `context_uri` | ✅ | The client registers as a `Computer` device named after the container's **hostname** (`5a0daaa5aa5e` = the container ID), next to the user's other computers. The probe originally picked the wrong one ("first Computer"); it now matches its own hostname. **Device name is configurable:** set the `DEVICE_NAME` environment variable (default `spotibackup`; the prototype compose sets `LorneNAS`). The client has no setting for its device name; it calls `gethostname()`. So `hostname-shim.c`, a tiny library preloaded into the Spotify process only (`LD_PRELOAD`), returns `$DEVICE_NAME` from `gethostname()`/`uname()`. That makes the name an ordinary environment variable, editable in the UGOS Docker app like the volume mappings, rather than Docker's `hostname:` option, which that app may not expose. Verified that the shim is loaded in the client's processes and returns `LorneNAS` while the real hostname is the container ID. `GET /me/player/devices` lists **`LorneNAS`** (id `bec8bd3c…`), and the name and ID stayed the same across a container recreate. Changing `DEVICE_NAME` may need a new login (row 4); not tested. `PUT /me/player/shuffle`, `/repeat` → 200; `PUT /me/player/play` → 204 for an album, an owned playlist and a followed playlist (even though that one's track list returned 403). The device ID stayed the same across client restarts. |
| 9 | MPRIS `OpenUri` starts a playlist (fallback path) | ✅ | `OpenUri string:spotify:playlist:…` started playback, MPRIS went to `Playing`, and the Web API reported that playlist as the context. MPRIS `Stop` is ignored: the status stays `Paused`. |
| 10 | Spytify records the first track when the session is started before playback | ✅ | The order pause → `full_volume` → `session.start` → `play` recorded track 1 from 0 ms. `full_volume` mattered: Spytify logged "player volume raised from 0% to 100% for the session". If the player is paused mid-track on something else when the session starts, Spytify treats that track as "already playing" and starts with the next one; switching context cuts it cleanly. |
| 11 | End of playlist is detected | ⚠️ | Detecting the end works: the track count (when known), or MPRIS `Paused` for 20 s, or a context change. **But Spotify only pauses at the end of a context, so Spytify never closes the last track.** It waits in "stopping", with the take still a WAV under `/music/.spytify/`. Spytify closes a track only when the player reports *Stopped*, the metadata empties, the player quits, or capture ends (its `session.go` / `session_events.go`). Tried: MPRIS `Stop` (ignored), killing Spotify's PulseAudio stream (Spytify just waits for a new stream). **Works: restarting the Spotify client.** Spytify logs "player interface gone", cuts the take at the declared length and saves it within ~7 s. The client comes back logged in. Cost per item: ~20 s idle wait + ~8 s + ~7 s restart. |
| 12 | Re-run skips every track (`recorder.duplicates=skip` + `skip_duplicates_forward`) | ✅ | The re-run of a 2-track album skipped both as `duplicate` within 1 s; no files changed. The duplicate index is `/music/.spytify/recorded.jsonl`, in the output folder, so it travels with the music share. |
| 13 | AAC output is correct (`.m4a`, tags, cover) | ✅ | AAC-LC, 44.1 kHz stereo, ~285 kb/s total including the cover. Tags: title, artist, album_artist, album, track. 640×640 cover embedded. Durations 112.7 s and 134.1 s vs the Web API's 112.8 s and 134.3 s. Path: `/music/<artist>/<album>/<artist> - <title>.m4a`. |
| 14 | Lossless offered by the Linux client (1.3.4) | ❌ | The user checked: the highest option is **Very high** (Ogg Vorbis 320 kbps), and **Lossless** isn't listed. `audio.play_bitrate_enumeration=4`. FLAC would only store a lossy stream in a bigger file. Default AAC 256; AAC 320 is the highest useful option. |

## Implications for the design

- **Run engine, per item:**
  1. pause
  2. `full_volume`
  3. shuffle and repeat off
  4. `session.start`
  5. `PUT /me/player/play` with a `device_id` matched by hostname
  6. follow events
  7. detect the end
  8. `session.stop`
  9. restart the client if the session hasn't gone idle within ~8 s
- **Container:**
  - Set a fixed `hostname` (e.g. `spotibackup`) so the Connect device name is stable.
  - Keep the client's own folder under `/config` so the login survives restarts.
- **Followed playlists:** no track count (403), so the UI shows "n recorded" without a total. End detection relies on MPRIS/context instead.
- **Spotify-made playlists** (Discover Weekly, Daily Mixes) can't be listed through the API.
  - Option: the user pastes their links, and playback works by URI.
  - This is untested for Spotify-made playlists.
- **Web API login** expires every 6 months. The UI must show the date and offer a reconnect.
- **Format:** no lossless on Linux, so offer AAC 256 (default), AAC 320 and MP3, and hide or label FLAC.
- **Working files:** Spytify keeps working WAVs and its duplicate index in `<output>/.spytify/`. A take stopped with `now` leaves its WAV there until the next track; the controller should clean up stale ones.
- **Spytify feature request:** close the last take when the player pauses at the end of a context, e.g. paused for N s after the declared length. That would remove the client restart.

## Not tested yet

- A full multi-track playlist run, e.g. "Old-School", 16 tracks, about an hour. The prototype only stopped playlists after their first track.
- Autoplay off really stopping at the end of a playlist. Albums ended in `Paused`, as expected.
- Spotify-made playlists by URI.
- The NAS: UGOS Docker app fields, `/volume6/Music`, overnight runs.
