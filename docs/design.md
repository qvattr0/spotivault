# spotivault design

spotivault is a single Docker image for a UGREEN NASync DXP4800+ (x86_64, UGOS Pro). It backs up your Spotify playlists, and optionally your saved albums, by recording them with [Spytify 2.0](https://github.com/spytify/spytify). A built-in web UI ([web-ui.md](web-ui.md)) controls it.

## Goals and non-goals

**Goals:**
- One image, installed through the UGOS Pro Docker app, with its ports, volumes and environment editable there.
- A web UI to choose what to back up, schedule or force runs, watch progress and set the format.
- Files in a NAS shared folder, with permissions left to that folder.

**Non-goals:** ARM hosts, more than one Spotify account.

## Feasibility summary

**Spytify:** `spytifyd` speaks newline-delimited JSON-RPC 2.0 on a Unix socket. The controller runs it once per item as `spytifyd --once --serve --idle-exit 20s`.
- **Actions:** `session.start`, `session.stop` and `session.status`; `settings.get` and `settings.set`; `player.control`; `log.tail`; `core.info`.
- **Pushed events:** `session.state`, `track.started`, `track.finished` (with the file path), `track.skipped` (duplicate, ad and so on), `level` and `error`.

**The Spotify client:**
- MPRIS over D-Bus gives local now-playing.
- Through the Web API it is a Connect device: playlists come from `GET /me/playlists`, and playback is started with `PUT /me/player/play`.

**One-time GUI steps:** done through noVNC: logging in, turning off crossfade, gapless playback and autoplay, and setting streaming quality.

**Recording order:** Spytify never records a track that was already playing when the session started. The controller starts the session before playback.

**Formats:** AAC (`.m4a`), MP3, FLAC or WAV, at 128, 160, 256 or 320 kbps. The default is AAC 256. The prototype found that the Linux client (1.3.4) streams at most Ogg Vorbis 320 kbps, with no Lossless, so FLAC and WAV add size without quality.

**Login:**
- **Client:** logs in by QR code scanned with the Spotify phone app, shown through noVNC. No browser is needed in the image.
- **Web API:** uses PKCE with the redirect `http://127.0.0.1:8888/callback`, and you paste the resulting address back. Refresh tokens expire 6 months after you authorize (Spotify, 2026-06-18), so the UI tracks the expiry and offers Reconnect.

**Base image:** Spotify Linux 1.2.77+ needs glibc 2.38+ (1.3.4 needs 2.39), so the image is Ubuntu 24.04 or Debian 13. It's Ubuntu 24.04: see [Container](#container).

**Developer app:** since March 2026, a Development Mode app needs a Premium owner and allows up to five users. The same change narrowed the Web API: see [Web API usage](#web-api-usage).

## Container

One image, built from the [Dockerfile](../Dockerfile) on `ubuntu:24.04`. s6-overlay v3 is PID 1 and supervises every service. Files baked into the image are in [image/rootfs/](../image/rootfs/).

| Service | Role |
|---|---|
| `init-spotivault` | A oneshot, run as root before the others. It checks the settings, prepares `/config`, `/music` and the runtime folders, then exits. |
| `xserver` | Xvfb, the virtual screen the client draws on (`:99`, 1280 × 800). |
| `wm` | matchbox-window-manager. The client's window fills the screen with no title bar. |
| `vnc` | x11vnc on `127.0.0.1:5900` only. The controller bridges it to the browser at `WS /vnc`. |
| `dbus` | The D-Bus session bus, for MPRIS and the client's IPC. |
| `pulseaudio` | A null sink at 44.1 kHz ([spotivault.pa](../image/rootfs/etc/pulse/spotivault.pa)). Spytify records from it with `parec`. |
| `spotify` | The Spotify client. It isn't in the image: `spotify-install` puts it in `/config`, and the service waits until it's there. |
| `controller` | Web UI and REST/WS API, run engine, scheduler, SQLite in `/config`. Python; see [Stack](#stack). Until S4 it's a stub: `/api/health`, `/vnc.html` and `WS /vnc` ([image/stub/](../image/stub/)). |

`spytifyd` is not a service. The controller starts it for each item (`--once --serve --idle-exit 20s`) and passes the recorder settings in at the start.

### Users and processes

- **`app` (uid 1000):** every service drops to it with `s6-setuidgid`, loggers included. `HOME` is `/config/home`. The image's `ubuntu` user is removed.
- **Root:** only s6's own supervision tree, which `/init` starts (`s6-svscan`, `s6-supervise`, the s6-rc fd holder), and the `init-spotivault` oneshot.
- **Logs:** each service has an `s6-log` that writes to docker's stdout, prefixed with the service name, and to `/config/logs/<service>/current` with timestamps. It keeps 10 files of 1 MB.
- **Shutdown:** the client ignores SIGTERM, SIGINT and SIGHUP. Its service quits it over MPRIS (`org.mpris.MediaPlayer2.Quit`) and kills it after 15 s. A clean quit also writes the client's `prefs` file. s6 gives the services 50 s to stop, inside the compose file's `stop_grace_period: 60s`.
- **Health check:** `curl http://127.0.0.1:8080/api/health`, every 30 s.

### Startup checks

`init-spotivault` stops the container with a clear message when a setting is wrong:

| Setting | Rule |
|---|---|
| `UMASK` | 3 or 4 octal digits. It applies to `/music` only; the controller sets it on the recorder. `/config` stays private (mode 0700, umask 077), because it holds the client's login and the tokens. |
| `TZ` | A zone in the image's tz database, such as `Europe/Berlin`. |
| `DEVICE_NAME` | 1 to 64 bytes, with no `/` and no control characters, because it becomes the client's hostname. |

It also:
- gives `/config` to `app`, and creates `home`, `logs`, `spotify` and `spytify` in it;
- keeps `/config/machine-id` for the life of `/config` (`/etc/machine-id` links to it);
- clears the client's Chromium `Singleton*` locks;
- gives `/music` to `app` only when it's an empty folder owned by root, which is what Docker creates for a new bind mount. Otherwise it leaves the folder's permissions alone and warns if `app` can't write there.

### The Spotify client

**Not in the image.** [`spotify-install`](../image/rootfs/usr/local/bin/spotify-install) puts it in `/config/spotify`. It runs as `app`, without apt and without root:
1. Download `InRelease` from Spotify's repository and check it with `gpgv` against the key baked into the image (`/usr/share/keyrings/spotify.gpg`). Only the signed text is used from then on.
2. Download `Packages` and check its sha256 and size against `InRelease`.
3. Pick the newest `spotify-client`, or the one given with `--version`.
4. Check the free space, download the `.deb` (179 MB) and check its sha256 and size.
5. Unpack it with `dpkg-deb -x`, and keep only `usr/share/spotify`.
6. List the client's libraries with the dynamic loader. A missing one fails with "update the image".
7. Move it to `versions/<version>`, switch the `current` link in one rename, and keep one previous version.

It prints one JSON object per line (`{"stage":"download","percent":42,…}`), which the controller relays to wizard step 2. The last line has stage `done` or `error`. `--check` only reports the installed and the available version. A lock stops two installs running at once. On Docker Desktop the whole install takes about 20 s.

**Running it:** the `spotify` service starts `/config/spotify/current/spotify --no-zygote --no-sandbox --disable-gpu` with the `DEVICE_NAME` shim preloaded. The client talks to PulseAudio directly through `libpulse`, so ALSA needs no plugins.

### What's in the image

The image is 281 MB uncompressed (95 MB compressed). The feasibility prototype was 1.43 GB (520 MB compressed; Docker Desktop shows 1.95 GB, the two added together).

| Part | How it's kept small |
|---|---|
| Spotify's libraries | The build installs `spotify-client` with `--no-install-recommends`, keeps what it pulled in, then purges the client. Its Recommends (`libavcodec`, for local files) stay out. |
| `spytifyd` | Built from source at tag 2.0.2 as a static Go binary, with `image/spytify/patches/*.patch` applied. The `.deb` would pull Mesa, GL and X for the desktop app. |
| ffmpeg | Built with Spytify's own `scripts/build-ffmpeg.sh`: only the encoders, filters and formats Spytify runs (4 MB). Spytify finds it through `SPYTIFY_FFMPEG`. |
| Screen and VNC | Xvfb + x11vnc. TigerVNC's `Xvnc` measured 56 MB more, because its package pulls Perl for a wrapper script. |
| Window manager | matchbox-window-manager, which adds nothing. openbox would add about 104 MB: it pulls Python, and Ghostscript and image codecs through imlib2. |
| Mesa | Its drivers and LLVM (about 180 MB) are left out with `dpkg` path-excludes. The client runs with `--disable-gpu` and has its own SwiftShader. `libgbm.so.1`, which it links, loads a driver only when used. |
| systemd | `dbus-x11` stands in for `dbus-user-session`, which GTK's dconf would otherwise pull, with systemd. |
| Placeholders | Two empty packages stand in for hard Depends that nothing here loads: `libasound2-plugins` (pulseaudio's; it pulls libavcodec, about 97 MB) and `tk` (x11vnc's, for its unused `-gui`). |
| Files | `dpkg` path-excludes for docs, man pages, translations, desktop icon themes (cursors kept) and GStreamer's ISO code tables. |
| Fonts | `fonts-dejavu-core`, which GTK pulls anyway. |

The excludes are in [spotivault-excludes](../image/rootfs/etc/dpkg/dpkg.cfg.d/spotivault-excludes).

### Configuration

- `EXPOSE 8080`. Only this port is published: noVNC goes through `WS /vnc`.
- `VOLUME /config /music`: map `/music` to `/volume6/Music`.
- `ENV`:
  - `TZ` (default `UTC`)
  - `UMASK` (default `000`)
  - `UI_PASSWORD` (optional): requires a password for the web UI. It can also be set in Settings.
  - `DEVICE_NAME` (default `spotivault`): the name of the Spotify Connect device ("Playing on …"). A small preloaded library ([hostname-shim.c](../image/hostname-shim.c)) sets it, because the client takes its name from `gethostname()`. Recreating the container keeps the login: tested with `--force-recreate` and with an image update, and the device kept its name and ID. That relies on a stable `/config/machine-id` and an unchanged `DEVICE_NAME`. Changing `DEVICE_NAME` is untested.
- `shm_size: 1g`: the client is Chromium, which passes data through `/dev/shm`.
- **Compose files:** [docker-compose.yml](../docker-compose.yml) builds from source for Docker Desktop, with data in `./data`. The one for the UGOS Docker app's Project feature comes in M2.
- Avoids host ports 9999 and 9443, which UGOS uses.

**Spytify defaults** (its booleans take `true` or `false`):
- `privacy.bug_tracker=false`. The image's `spytifyd` is built without a crash-report address, so it sends nothing either way.
- `recorder.duplicates=skip`
- `recorder.skip_duplicates_forward`: off for items played as missing tracks only, on for items played whole (see [Run flow](#run-flow-per-playlist-or-album))
- File naming from Settings › Files › Layout, passed in with the other recorder settings. The default is `{album_artist}/{album}/{track} - {title}`. How Spytify takes it is [open question 16](web-ui.md#open-questions).

## Stack

Chosen at Gate A of the M1 plan (2026-11-15). The sizes were measured on test builds on top of the S2 image, which is 274 MB without a controller.

| Part | Choice | Why |
|---|---|---|
| Controller | Python 3.12, from Ubuntu's `python3` package, on asyncio | The maintainer reads Python. probe.py's tested logic carries over. |
| Controller libraries | FastAPI (with pydantic), uvicorn (no extras), httpx, jeepney (D-Bus) and the stdlib `sqlite3` | About +62 MB on the image, worked out from the measured parts. FastAPI is used for its request validation and typed models. Starlette on its own measured about +48 MB. Any other library must be worth its size, measured as in S2. |
| Web UI | React 19, TypeScript, Vite | Built in a Node builder stage. Only the built files ship in the image, and the controller serves them. |
| UI packages | `openapi-typescript` (the typed client, from `contracts/openapi.yaml`), `lucide-react`, `@novnc/novnc`, self-hosted Figtree | |
| Tests | pytest for the controller, with the simulated player and recorder; Playwright for the UI, against fake mode | |

Go was the other finalist. It measured +11 MB and matches Spytify's track keys by construction, but Python is the language the maintainer can edit.

**Track keys:**
- **The rule:** Spytify lowercases with Go's `strings.ToLower` and trims with `strings.TrimSpace`. The controller uses probe.py's `go_lower` and `go_trim`, which match Go on every Unicode code point under Python 3.12 (all 1,112,064 checked at Gate A).
- **Python upgrades:** Python 3.13 and later use a newer Unicode version and would drift. `ubuntu:24.04` stays on 3.12. If the Python version ever changes, switch to a lowercase table generated from Go.
- **CI:** checks `contracts/vectors/track-keys.json` against Spytify's own Go code (`generate.py --go`; 34 of 34 agreed at Gate A), so the vectors aren't only checked against our own port.

**The contract stays the source:** FastAPI builds its API description from the code, but `contracts/openapi.yaml` is the spec. The pydantic models are generated from the contract (with `datamodel-code-generator`, at development time only), and a test compares FastAPI's `/openapi.json` with the contract, so the code can't drift from it.

**Spytify's protocol:** Python can't import Spytify's Go package `pkg/proto`. The controller's types follow `pkg/proto/schema.json`, and integration tests run against `spytifyd --fake`.

### asyncio: never block the event loop

The controller runs on one asyncio event loop: the REST API, both WebSockets, the `/vnc` bridge, the run engine and the scheduler. **One blocking call freezes all of them** until it returns. That's easy to miss in review, because the code still works in quick tests.

**Why it matters here:** the engine steers playback within about 2 s of a track starting. A stall of a few seconds can let the wrong track play or miss a pause, and the live UI and the VNC view freeze meanwhile.

| Blocks the loop, never use it there | Use instead |
|---|---|
| `requests`, `urllib`, a sync `httpx.Client` | `httpx.AsyncClient` |
| `subprocess.run`, `os.system`, `dbus-send` (as probe.py does) | `asyncio.create_subprocess_exec`; jeepney's asyncio router for D-Bus |
| `time.sleep` | `await asyncio.sleep` |
| `sqlite3` queries, folder walks, large file reads | One worker thread for the database; `asyncio.to_thread` for files |

**In FastAPI routes:** a route written as `def` runs in a worker thread, so blocking there is safe. A route written as `async def` runs on the loop itself, so one blocking call inside it freezes everything. Routes are `async def` and follow the table above.

**Checks:**
- **Lint:** ruff's `ASYNC` rules run in CI and flag blocking calls inside `async def`.
- **Tests:** run in asyncio debug mode, and a callback slower than 100 ms fails the test.
- **At runtime:** a watchdog measures how late the loop runs. Over 250 ms, it logs a warning, and the lag goes into the run metrics.

**A related trap, lost task errors:** an exception in a task that nobody awaits disappears silently. Every task starts in a `TaskGroup`, or has a done-callback that logs its exception.

## Run flow, per playlist or album

Tested in the prototype; the evidence is in `prototype/FINDINGS.md` ("Implications for the design" and the S0 section). An item is played one of two ways:
- **Missing tracks only:** albums, Liked Songs and playlists you own or collaborate on. The controller has the track list, so it plays only what isn't recorded yet.
- **Whole:** followed and linked playlists, which have no track list (see [Web API usage](#web-api-usage)).

1. **Plan.**
   - **Missing tracks only:** fetch the track list with `market=from_token`. Leave out entries with `is_playable: false`, local files, episodes and empty entries. Look each one up in Spytify's duplicate index (`/music/.spytify/recorded.jsonl`) by Spytify's own key: the first artist and the title, trimmed and lowercased the Go way. An entry counts only while its file exists. **Nothing missing:** the item is Up to date, and no recorder starts.
   - **Whole:** the item is Up to date without playing if its `snapshot_id` is the one from its last clean full pass **and** every track seen in that pass is still in the index. A deleted file forces a full pass. A clean full pass is one that ended normally, with no failed track and no interruption.
2. **Prepare the player:** pause, seek to 0, and turn shuffle and repeat off. Spytify won't record a track the player is paused on more than 300 ms in, and it misses a restart within 2 s of that point, so seeking to 0 first matters ([Spytify bugs](upstream/spytify-bugs.md) #2).
3. **Start the recorder:** `spytifyd --once --serve --idle-exit 20s` for this item, with every recorder setting passed as `--set` (see [Container](#container)). `recorder.skip_duplicates_forward` is **off** for missing-tracks-only items and **on** for whole items. With it on, Spytify presses Next on the paused track 1 at the end of an album ([Spytify bugs](upstream/spytify-bugs.md) #1), so whole items get a loop guard (a track seen twice in one item pauses the player). Then `player.control full_volume`.
4. **Play:** `PUT /me/player/play` with the container's `device_id`, the item's `context_uri` and an `offset`.
   - **The offset is by URI**, at the first missing track. `offset.position` counts only playable entries, so after an unplayable entry it lands on a later track.
   - **Liked Songs** is the context `spotify:user:<id>:collection`. The Web API then reports it as a playlist URI (`spotify:playlist:37i9dQZF1F…`), and the controller treats that as the same context.
5. **Steer:** on each `track.started`, identify the loaded track by MPRIS `mpris:trackid`, which names the context's own entry. `GET /me/player` can report a relinked track ID, and `linked_from` is gone. If the track is planned, it plays. If not, the controller jumps to the next missing track (another play with an `offset` by URI) or, when none is left, pauses. A jump costs about 2 s of a track that's never saved.
6. **End:** Spotify pauses at the end of an album or playlist, and the controller pauses when the plan is done. After 20 s of silence, `spytifyd` saves the last track and exits (`--idle-exit 20s`), about 20–27 s after the pause.
   - **No client restart is needed.**
   - **Read every event**, including those written as the process exits. The last take's `track.finished` arrives then, and the `--events` file holds it too.
   - **Pause the player** in case it started again, and recompute what's missing from the index. **Count distinct tracks, not events:** a phantom `track.started` + `track.skipped` for the paused track 1 is normal at the idle exit.
   - **A pause of more than 20 s in the middle of an item** ends it early. This happens when another device takes over or the network stalls. The controller re-queues the item once, and the tracks already recorded are skipped. A second interruption in the same run ends the item as Partial.
   - **The context moves on** (autoplay): the controller stops the session at once and ends the item.
   - **Timeouts:** if playback never starts, or the recorder outlives the end, the controller sends SIGTERM (finish the current track), then a second one (stop at once). Restarting the client is the fallback.
7. **Files:** write a `.m3u` for the playlist, in the Web API's track order, with paths relative to the `.m3u`. For a whole item, use the order the tracks were recorded in. Save its cover next to it (see [Playlist covers](#playlist-covers)).

The scheduler queues items. An item forced from the UI goes right after the current item. One item records at a time.

## Web API usage

Spotify narrowed the Web API for Development Mode apps in February 2026: new apps from 11 February, existing apps from 9 March. spotivault only uses endpoints that are still available ([migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)).

| Endpoint | Used for | Page size |
|---|---|---|
| `GET /me` | The display name ("Connected as …"). | — |
| `GET /me/playlists` | The playlist list, each with its owner, `snapshot_id` and `items.total`. | 50 |
| `GET /playlists/{id}/items` | A playlist's tracks. It replaces the removed `/playlists/{id}/tracks`. | 50 |
| `GET /playlists/{id}` | Name, owner and cover for a pasted link. | — |
| `GET /me/tracks` | Liked Songs, newest first. | 50 |
| `GET /me/albums` | Saved albums, each with its first page of tracks. | 50 |
| `GET /albums/{id}/tracks` | The rest of an album longer than that first page. | 50 |
| `GET /me/player/devices` and the player controls (`play`, `pause`, `shuffle`, `repeat`) | Finding the container's device and starting each item. | — |

**The 2026 rules that shape the design:**
- **Item access:** `/items` returns tracks only for playlists you own or collaborate on. Any other playlist returns 403. So followed and linked playlists have no track list until they're recorded. `/me/playlists` still gives a followed playlist's `items.total` (tested 2026-11-15, although the migration guide says it's left out). A linked playlist has no total: `GET /playlists/{id}` returns its name, owner, images and `snapshot_id`, with no `items`. A followed playlist you collaborate on has access and behaves like your own.
- **Renamed fields:** a playlist's contents moved from `tracks` to `items`, and each playlist entry's track from `track` to `item`. The controller reads only the new names there. **Library endpoints kept theirs:** `/me/tracks` entries still use `track`, and `/me/albums` entries use `album`, with the album's tracks under `album.tracks.items`.
- **Relinked tracks:** `GET /me/player` can report a relinked track ID instead of the playlist entry's own, and `linked_from` is gone. The controller identifies the loaded track by MPRIS `mpris:trackid`, and uses the player state only for the context and the device.
- **Offsets:** `offset.position` counts only playable entries, so the controller starts and jumps with `offset.uri`.
- **No batch lookups:** `GET /tracks?ids=` and `GET /albums?ids=` are gone. Everything the controller needs, `duration_ms` included, comes with the listings above, so it's stored when it's fetched.
- **Removed fields:** among others, `popularity` and `linked_from` on tracks, and `label` on albums. spotivault uses none of them.
- **Rate limits:** Spotify publishes no Development Mode numbers. Limits apply over a rolling 30 s window, plus quota buckets shared by every app on the developer account. A `429` carries `Retry-After`; see Requests below for how the controller handles it.

**Load:**
- Each request names only the fields it needs through the `fields` parameter: track ID, title, artists, album, cover, `duration_ms` and `is_local`.
- **Playlists:** the controller stores each one's `snapshot_id` and refetches its items only when that changes.
- **Liked Songs:** it has no `snapshot_id`. The controller reads from the newest page until it reaches a track it already has, then compares `total`. If the total doesn't match, it refetches the whole list.
- **Albums:** they don't change, so they're fetched once, when added.
- **Example:** a first fetch of 23 playlists with 3,000 tracks, 2,000 Liked Songs and 100 saved albums is about 110 requests. A refresh where nothing changed is a few.

**Requests:**
- **One at a time:** the controller sends one Web API request at a time, with a short pause between them (250 ms by default) during catalog refreshes. Playback calls during a run aren't delayed.
- **Retries:**
  - A `429` waits for `Retry-After`.
  - A `5xx`, a `503` or a timeout is retried after 5 s, and the delay doubles on each further attempt, up to 3 retries. If a `429` also carries `Retry-After`, the longer of the two wins.
  - A `401` refreshes the token once, then retries. A `403` or `404` is not retried: it's an answer (no item access, or the item is gone).
- **Counting:** the controller counts requests per catalog refresh and per run, with retries and `429`s counted separately. Each refresh and each run ends with one Controller log line, for example "Web API: 112 requests · 2 retried · 0 rate-limited". A rising rate-limited count is the early sign of a quota problem.

**Not used:** some tools, such as [zotify](https://github.com/Googolplexed0/zotify), log in as Spotify's own desktop client and call Spotify's internal endpoints. That gets around every Development Mode limit, followed playlists included. spotivault doesn't do this:
- it passes the controller off as Spotify's own client, which breaks the developer terms more directly than recording does;
- it raises the risk to an account that's used every night;
- the internal endpoints are undocumented and change without notice;
- it saves few requests here, because Liked Songs and albums cost the same either way.

## Backlog estimate

Recording happens in real time, so a backup takes about as long as the music still to record. The Dashboard's Full backup card, wizard step 9 and the Schedule preview all show this estimate, from one calculation (`GET /api/backlog`).

- **Catalog:** every tracked item's track list with `duration_ms`, kept in SQLite and refreshed as described in [Web API usage](#web-api-usage). It's refreshed at the start of each run, and when the Dashboard or Schedule page opens, at most once every 15 minutes.
- **What's recorded:** History's per-track records, keyed by Spotify track ID.
- **Time left:**
  - the sum of `duration_ms` over tracks not recorded yet, counting each track ID once however many items it's in;
  - plus about 35 s for each item with something to record: a few seconds to start, and the 25–30 s Finishing tail;
  - local files (`is_local`) and entries with no `item` are left out, because they can't be played.
- **Finish date:** the controller walks the schedule's active hours forward from now until the time left is used up. With Manual only, there's no date.
- **Unknown items:** followed and linked playlists have no track list, so their length is unknown. They're left out of the figure and counted separately, unless they're Up to date by their `snapshot_id` (see [Run flow](#run-flow-per-playlist-or-album) step 1). A followed playlist's track count is known from `/me/playlists`, so the UI can show it, but not its duration.
- **Accuracy:** duplicates are skipped in seconds, so they barely count. The same song can have a different track ID on a single and on its album; it's counted twice but recorded once, so the estimate leans slightly high.

## Playlist covers

Each playlist's cover is saved next to its `.m3u`, with the same base name: `Music/Playlists/<name>.m3u` and `Music/Playlists/<name>.jpg` (or `.png`). When the playlist is renamed, both files are renamed.

**Why you can upload your own:** Spotify doesn't keep a sharp copy of a playlist cover. Tested on 2026-11-15 against Spotify's image CDN, trying each size code:

| Cover | Sizes on the CDN | Largest |
|---|---|---|
| Uploaded in Spotify (`i.scdn.co/image/ab67706c0000<size><id>`) | `bebb` 640, `da84` 300, `d72c` 300 (smaller file). Every other code tried, `82c1` included, is a 404. | 640 × 640 |
| Grid of four album covers (`mosaic.scdn.co/<size>/<ids>`) | 60, 300, 640, 1280 | 1280 × 1280, built from four 640 px album covers |

Spotify's own upload endpoint takes a JPEG of at most 256 KB, so a sharper original isn't kept on Spotify's side. Album covers are different: the API gives 640 px, but the CDN has larger copies.

**Which cover is saved:**
1. **Your custom cover**, if you've set one. It's saved byte for byte: never re-encoded or resized.
2. **Otherwise, Spotify's cover**, at the largest size the CDN has, while "Save Spotify's covers" is on in Settings.
3. **Liked Songs never has a cover file,** and you can't set a custom cover for it. The UI shows the Liked Songs tile everywhere instead: the client's gradient heart, drawn in our own style ([web-ui.md § Design language](web-ui.md#design-language)).

**Spotify's cover:**
- **Source:** the `images` URL from `GET /me/playlists`, which the catalog refresh already fetches (`images(url)` is added to its `fields`). For a linked playlist, it comes from `GET /playlists/{id}`.
- **Largest size:** the controller rewrites the URL before downloading, following [Spotify's image CDN](#spotifys-image-cdn) below. If the rewritten URL fails, it downloads the URL as returned.
- **When:** at step 6 of the run flow, only when the image ID (the part after the size) has changed since the last download. A playlist with a new grid of covers gets a new ID, so it's downloaded again.
- **No stored URLs:** Spotify documents that playlist image URLs expire in less than a day, so a URL is used straight away and never kept as the cover.
- **Load:** one CDN request per changed cover. These go to `i.scdn.co` or `mosaic.scdn.co`, not the Web API, so they're not in the Web API request count.

**Your cover:**
- **Upload:** from the Library's detail view (see [web-ui.md § Detail view](web-ui.md#detail-view)). JPEG or PNG, up to 20 MB. The file keeps its type, so a PNG is saved as `<name>.png`.
- **Dropped in by hand:** an image you put in `Music/Playlists/` yourself, through the NAS share, with the playlist's base name also counts as a custom cover. The controller stores a hash of every cover file it writes, and never overwrites or deletes a file whose hash doesn't match.
- **Checks:** a cover that isn't square, or is under 640 px, is accepted with a warning. Players usually crop a non-square cover to the centre.
- **Never sent to Spotify:** uploading would need the extra `ugc-image-upload` scope, and Spotify would shrink it to a 256 KB JPEG anyway.
- **Removing it** goes back to Spotify's cover.

**Files:**
- **One cover file per playlist.** Switching between JPEG and PNG, or between Spotify's and yours, replaces the old file.
- **Kept:** like the `.m3u`, the cover stays when you stop tracking a playlist or remove it from the Library.
- **Written either way:** covers are saved whether or not "Write .m3u playlists" is on, so an upload is never lost.
- **SQLite** keeps, per playlist: the source (`custom`, `spotify` or none), the file name, its hash, its pixel size, and the Spotify image ID.
- **Thumbnails:** the UI never loads a full-size file. The controller keeps a 300 px thumbnail of each cover in `/config/cache/covers/`.

### Spotify's image CDN

The Web API returns one image URL per playlist and doesn't say which other sizes exist. The controller gets the largest size by rewriting that URL. **Spotify doesn't document this naming.** It was worked out by testing on 2026-11-15, and it can change without notice.

**An uploaded cover:** `https://i.scdn.co/image/ab67706c0000<size><id>`. The API may also return it on `image-cdn-ak.spotifycdn.com` or `image-cdn-fa.spotifycdn.com`, with the same path.

For example, `ab67706c0000bebbd17e192d4a08b8d87b6baa18` splits into:

| Part | Here | Meaning |
|---|---|---|
| Kind | `ab67706c` | A cover uploaded to a user's playlist. Other prefixes are other kinds of image: `ab67616d` is album art, and `ab67706f` is a playlist made by Spotify. |
| Padding | `0000` | Always `0000` so far. |
| Size | `bebb` | Four hex digits that pick the size. |
| Image ID | `d17e192d4a08b8d87b6baa18` | 24 hex digits that identify the image. It's the same across sizes, so it's what the controller compares to know whether a cover has changed. |

| Size code | Pixels | Notes |
|---|---|---|
| `bebb` | 640 × 640 | The largest. The controller always asks for this one. |
| `da84` | 300 × 300 | |
| `d72c` | 300 × 300 | A smaller, more compressed file than `da84`. |

Every other code tried returned 404, including `82c1`, the code that gives album art above 640 px. So 640 px is the largest copy of an uploaded cover.

**A grid of four album covers:** `https://mosaic.scdn.co/<size>/<ids>`. Spotify builds it from the first albums in the playlist, and `<ids>` is those four album image IDs joined together.
- `<size>` is the edge in pixels. 60, 300, 640 and 1280 exist, and 1000 and 2000 return 404.
- 1280 is a true 1280 px image: each quarter is a full 640 px album cover.
- The image ID the controller compares is the whole `<ids>` part. When the playlist's first albums change, it changes too.

**Rewriting:**
1. Uploaded cover: replace the four `<size>` digits with `bebb`.
2. Grid: replace `<size>` with `1280`.
3. Any other URL shape is downloaded as returned.

**When it stops working:**
- **Fallback:** if the rewritten URL returns 404 or isn't a JPEG, the controller downloads the URL as the API returned it. That's always a working image, at whatever size Spotify chose.
- **Logged:** each fallback writes a Controller warning, for example "Cover for Late Night Drive: larger size not found, saved as returned (300 × 300)". The catalog refresh's summary line counts them: "Covers: 4 saved · 1 at the size returned".
- **Re-checking by hand:** take a cover URL from a playlist, swap in each size code with `curl -o`, and read the pixel size of what comes back. If `bebb` or `/1280/` stops returning the largest image, update the tables above and the rewrite rules.

## Distribution

- **CI:** [.github/workflows/ci.yml](../.github/workflows/ci.yml) runs shellcheck, builds the amd64 image and runs the [smoke test](../image/test/smoke.sh) on every pull request and every push to main. It pushes nothing.
- **Docker Hub:** publishing comes in M3, with its secrets.

The smoke test runs the same way by hand: `docker build -t spotivault:ci .`, then `image/test/smoke.sh spotivault:ci --install`. It checks that the container turns healthy, that only s6 runs as root, that `WS /vnc` reaches VNC, the `spytifyd` version and the shim, fake recordings in AAC, MP3 and FLAC, that bad settings stop the container, the client install, and a quick stop.

## Terms of Service

This project breaks Spotify's terms:
- **User terms:** Spotify's user guidelines prohibit ripping and recording content.
- **Developer terms:** Spotify's developer terms forbid facilitating stream ripping.
- **Precedent:** accounts using recording software have been suspended before.

**Practical risks:**
- The Premium account is suspended or closed.
- The developer app is revoked.
- Nightly automated plays and skips look like artificial streaming.

Whether private copies are legal depends on the country, and this document doesn't cover it. The setup wizard shows this notice once. Using a separate Premium account lowers the risk to your main one.

## Risks to validate

Open questions are also tracked in [web-ui.md § Open questions](web-ui.md#open-questions).

The prototype settled these (details in `prototype/FINDINGS.md`):
- Login inside Xvfb works, by QR code.
- The client has no Lossless.
- The container is a Connect device.
- The end of an item is handled by Spytify's `--idle-exit 20s`: the last track is saved about 27 s after the pause.
- Recording works end to end.
- Followed playlists play by `context_uri`, although `/items` returns 403.

Step S0 of the M1 plan settled these (2026-11-15, Spytify 2.0.2):
- **Saved albums:** `/me/albums` and `/albums/{id}/tracks` answer 200.
- **Field names:** checked against live responses; see [Web API usage](#web-api-usage).
- **Liked Songs** plays as a context, and a playlist with unplayable entries records with offsets by URI.
- **Login detection**, the **runtime client install** and **`--disable-dev-shm-usage`** work as described in web-ui.md (Q2, Q13).
- **Linked playlists** (public, not followed) give their name, owner, cover and `snapshot_id`, and play by `context_uri` (Q10).

Spytify's own bugs, and what the controller does about them, are in [upstream/spytify-bugs.md](upstream/spytify-bugs.md).

Still to validate:
- **Cover sizes on the CDN:** the size rewrites in [Spotify's image CDN](#spotifys-image-cdn) rely on undocumented naming. Tested on public playlists on 2026-11-15; re-check before release, and whenever the fallback warning starts showing up.

## Component Rules

Rules for the components in `ui-design/spotivault.pen`. Follow them when editing the design file.

### Logo (`Logo/Mark` components)

- **Pick by size:** use the component that matches the size you need: `Logo/Mark` (140), `Logo/Mark 64` or `Logo/Mark 32`, or `Logo/Mark 16` for the favicon. Never resize an instance, because the smaller variants drop detail on purpose.
- **Fixed colours:** the parts use fixed hex colours, not tokens. Don't swap them for `$accent` or the surface tokens.
- **Source:** the geometry comes from `brand/make_logo.py`, so change it there first and copy the new geometry into the components. Full rules are in [brand/README.md](brand/README.md).

### Shapes vs. icons in a leading slot

Some components take either a **shape** or an **icon** in the same slot. A Lucide icon has built-in whitespace inside its box, while a shape doesn't. So the padding on an icon's side is 2 px smaller than on a shape's side, which makes both look the same distance from the edge.

### Status pill (`Pill` component)

| Leading element | Padding (top, right, bottom, left) |
| --- | --- |
| Shape: 6 px `Dot` ellipse (the component's default) | `3, 8, 3, 8` |
| Icon: 12 px Lucide icon, for example the dashed `circle-dot-dashed` for "Recording" | `3, 8, 3, 6` |

- When you swap a pill's dot for an icon, also override that instance's padding to `3, 8, 3, 6`. When you swap it back to a dot, remove the override.
