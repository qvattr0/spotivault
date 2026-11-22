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

**Formats:** Spytify writes AAC (`.m4a`), MP3, FLAC or WAV, at 128, 160, 256 or 320 kbps. Settings › Recording offers AAC 256 (the default), AAC 320 and MP3 320, with FLAC and WAV under "More formats". The prototype found that the Linux client (1.3.4) streams at most Ogg Vorbis 320 kbps, with no Lossless, so FLAC and WAV add size without quality.

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
| `controller` | Web UI and REST/WS API, run engine, scheduler, SQLite in `/config`. Python ([controller/](../controller/)); see [Stack](#stack). s6 runs `/opt/spotivault/venv/bin/python -P -m spotivault`. It also serves the `/vnc.html` page, with noVNC's core from its web root, `/usr/local/share/spotivault/web`. |

`spytifyd` is not a service. The controller starts it for each item (`--once --serve --idle-exit 20s`) and passes the recorder settings in at the start. The full command is `--once --serve --idle-exit 20s --wait-target 60s --log-file … --events …`, with one `--set key=value` per recorder setting (see [Spytify 2.0.2's settings](#configuration) below). The rest is fixed in [recorder/process.py](../controller/src/spotivault/recorder/process.py) (`command_line`):
- **Socket:** its own per item, `$XDG_RUNTIME_DIR/spytify-<run>-<n>.sock`. The controller talks only to a `spytifyd` it started.
- **Environment:** only what `command_line` lists, never the controller's own: `HOME`, a fixed `PATH`, `LANG`, `TZ`, `XDG_RUNTIME_DIR`, the display, bus and sound addresses, `SPYTIFY_SOCKET`, `SPYTIFY_CONFIG` (`/config/spytify/config.toml`), `SPYTIFY_FFMPEG` (`/usr/local/bin/ffmpeg`), and the client's process and MPRIS names.
- **Process:** its own process group, with `UMASK`. Its working folder is an empty one, because Spytify loads a `.env` file from there.
- **Files:** its log and events files are `/config/logs/spytify/<run>-<item>.log` and `.events.jsonl`, one pair per item, and a second attempt gets `-2` in its name.

### Users and processes

- **`app` (uid 1000):** every service drops to it with `s6-setuidgid`, loggers included. `HOME` is `/config/home`. The image's `ubuntu` user is removed.
- **Root:** only s6's own supervision tree, which `/init` starts (`s6-svscan`, `s6-supervise`, the s6-rc fd holder), and the `init-spotivault` oneshot.
- **Logs:** each service has an `s6-log` that writes to docker's stdout, prefixed with the service name, and to `/config/logs/<service>/current` with timestamps. It keeps 10 files of 1 MB. See [Logs](#logs).
- **Shutdown:** the client ignores SIGTERM, SIGINT and SIGHUP. Its service quits it over MPRIS (`org.mpris.MediaPlayer2.Quit`) and kills it after 15 s. A clean quit also writes the client's `prefs` file. s6 gives the services 50 s to stop, inside the compose file's `stop_grace_period: 60s`.
  - **A run going:** on SIGTERM the controller does Stop now, within 40 s. The current item ends Interrupted, its cut take counts as Skipped, and the run ends Failed, "container restarted" ([web-ui.md Q17](web-ui.md#open-questions)).
- **Restarting the client** (wizard step 3's Reset login screen, the Player's Restart client): s6's control pipes belong to root, so the controller, as `app`, can't use `s6-svc`. It does what the service does on a stop: MPRIS Quit, then a kill after 15 s if the client is still there. s6 then starts the client again, in a few seconds.
- **Login detection:** the controller reads the client's main window title with `xwininfo -root -tree` (x11-utils). The logged-out client's window is `"Spotify": ("spotify" "Spotify")`, 1280 × 800.
- **Health check:** `curl http://127.0.0.1:8080/api/health`, every 30 s with a 5 s timeout, after a 60 s start period ([health.py](../controller/src/spotivault/api/routers/health.py)).
  - **Unhealthy:** the controller doesn't answer, or can't open its database (503).
  - **`degraded`:** the screen (Xvfb) or the sound server (PulseAudio) doesn't answer. The container stays healthy, so the UI can still show what's wrong.

### Startup checks

`init-spotivault` stops the container with a clear message when a setting is wrong:

| Setting | Rule |
|---|---|
| `UMASK` | 3 or 4 octal digits. It applies to `/music` only: the controller sets it on the recorder and the `.m3u` files, and after each item it gives the recorded files 0666 less `UMASK`, since Spytify leaves tagged files at 0600 ([Spytify bugs](upstream/spytify-bugs.md) #7). `/config` stays private (mode 0700, umask 077), because it holds the client's login and the tokens. |
| `TZ` | A zone in the image's tz database, such as `Europe/Berlin`. |
| `DEVICE_NAME` | 1 to 64 bytes, with no `/` and no control characters, because it becomes the client's hostname. |

It also:
- gives `/config` to `app`, and creates `home`, `logs`, `logs/init`, `spotify` and `spytify` in it;
- writes its own messages to `/config/logs/init/current` too, in s6-log's format, kept to its last 1000 lines;
- keeps `/config/machine-id` for the life of `/config` (`/etc/machine-id` links to it);
- clears the client's Chromium `Singleton*` locks;
- gives `/music` to `app` only when it's an empty folder owned by root, which is what Docker creates for a new bind mount. Otherwise it leaves the folder's permissions alone and warns if `app` can't write there.

### Logs

Everything History › Logs shows, and the zip holds, is in `/config/logs` ([web-ui.md § Logs tab](web-ui.md#logs-tab)). The Logs tab and the retention below moved into M1 on 2026-11-22. The controller reads the logs in [logview/](../controller/src/spotivault/logview/).

| Log | Where | A line |
|---|---|---|
| Each s6 service: `controller`, `spotify` (the client), `dbus`, `pulseaudio`, `vnc`, `wm`, `xserver` | `<service>/current`, and `@<tai64n>.s` once rotated | `2026-11-15 00:05:02.310000000  <text>`: s6-log's `T`, in UTC, since s6-log runs without `TZ`. The controller's text is `LEVEL logger: message`. |
| The start-up checks | `init/current` | The same format, written by `init-spotivault`. It runs as root, but writes there (and the machine ID) as `app`, which owns `/config`: an `app` process could have swapped the file for a link to one of root's. |
| Spytify, one per item | `spytify/<run>-<item>.log`, `-2` for a second attempt | `2026-11-15T01:05:02.310000000+01:00 info  capture: …`, in the container's `TZ`. |
| Spytify's raw events | `spytify/<run>-<item>.events.jsonl` | Read by the controller at the item's end. Never shown, and not in the zip. |

- **Reading:** off the event loop. A page merges every file newest first, opening a file only when the merge reaches it; it reads at most 8 MB. A line's `id` is its time, service and place, and is the paging cursor.
- **Live:** only while a Logs tab follows (`logs.follow` on `WS /api/events`). The controller then looks for new lines every 0.5 s, follows rotation by inode (every file rotated between two looks included), and sends each follower the lines its filter matches, 200 at most per batch ([events.md § Logs](../contracts/events.md#logs)). The matching runs off the event loop. Lines left out, and lines skipped because a log grew by more than 4 MB at once, are counted in `dropped`, so the tab offers to read them. A look that fails is logged and tried again; it never stops the controller.
- **Masking:** every line goes through the controller's redaction (`logs.redact`) on the way out, on the page, live and in the zip. The client's and Spytify's output was never masked when written.
- **Retention:** 14 days or 50 MB for all of `/config/logs`, whichever comes first. At start-up and every hour, the controller deletes rotated and Spytify files last written over 14 days ago, then, while the files it may delete pass 50 MB together, the oldest: Spytify's events files first, then the logs. Never deleted, and not counted in the 50 MB: s6-log's `current` files, the files of a run still going, and the rotated s6-log files written since that run started. Counting them would only take everything else: one long item's events file can pass 50 MB. The 14 days and the zip's 7 are real time, since they're compared with the files' last-write times. s6-log rotates by size only, so its own limit stays: 10 files of 1 MB per service.
- **Fake mode** has no s6-log, so the controller writes `logs/controller/current` itself, in the same format, with the fake world's time ([logs.py](../controller/src/spotivault/logs.py)). Its times never go back: a restart starts the world's clock again from real time, behind what a faster world wrote, so a line gets no earlier time than the last one in the file. The fake recorder writes Spytify's item logs.

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

The image is 337 MB uncompressed (112 MB compressed), as recorded for S5's build, before the web UI's 0.9 MB was added. The controller is 62 MB of it: 39 MB of Python and 23 MB of venv. Without one, the S2 image was 274 MB. The feasibility prototype was 1.43 GB (520 MB compressed; Docker Desktop shows 1.95 GB, the two added together).

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
| Controller runtime | Ubuntu's `python3` (3.12): 24 MB installed, plus 12 MB of byte-compiled standard library. `python3-minimal` would be smaller, but it lacks `asyncio` and `sqlite3`. `x11-utils` adds `xwininfo`, for the client's window title (0.8 MB). |
| Controller venv | Built in a builder stage with uv, from `controller/uv.lock`, at `/opt/spotivault/venv` (23 MB, 8 MB of it bytecode). It's byte-compiled there, because the `app` user can't write to it. No pip, uv or caches ship. pydantic and pydantic-core are 9.6 MB of it. |
| noVNC | Only its `core` and `vendor` folders (0.8 MB), pinned by sha256, in the controller's web root. No websockify: the controller bridges `WS /vnc`. |
| Web UI | `npm ci` and `vite build` in a `webui` stage on a pinned Node 22.18 image. Only `web/dist` ships: `index.html` and its hashed assets (0.9 MB), beside noVNC's core in the web root. `node_modules`, the design drawings and test output stay out of the build context ([.dockerignore](../.dockerignore)). |

The excludes are in [spotivault-excludes](../image/rootfs/etc/dpkg/dpkg.cfg.d/spotivault-excludes).

### Configuration

- `EXPOSE 8080`. Only this port is published: noVNC goes through `WS /vnc`.
- `VOLUME /config /music`: map `/music` to `/volume6/Music`.
- `ENV`:
  - `TZ` (default `UTC`)
  - `UMASK` (default `000`)
  - `UI_PASSWORD` (optional): meant to require a password for the web UI. **Not enforced in M1** (plan D11): when it's set, the controller logs a warning at start-up, and `GET /api/container` reports it (`ui_password_env_set`). Settings doesn't show it yet. Keep the UI on your LAN until the password feature comes.
  - `DEVICE_NAME` (default `spotivault`): the name of the Spotify Connect device ("Playing on …"). A small preloaded library ([hostname-shim.c](../image/hostname-shim.c)) sets it, because the client takes its name from `gethostname()`. Recreating the container keeps the login: tested with `--force-recreate` and with an image update, and the device kept its name and ID. That relies on a stable `/config/machine-id` and an unchanged `DEVICE_NAME`. Changing `DEVICE_NAME` is untested.
- `shm_size: 1g`: the client is Chromium, which passes data through `/dev/shm`.
- **The controller's own variables** (`SPOTIVAULT_*`: port, folders, log level, fake mode) are for development and tests. They're listed in [controller/ARCHITECTURE.md § Environment](../controller/ARCHITECTURE.md#environment); the image needs none of them. One is for users: `SPOTIVAULT_ALLOWED_HOSTS`, to reach the UI by a name other than an IP address or a home-network name ([web-ui.md § Security](web-ui.md#security)).
- **Compose files:** [docker-compose.yml](../docker-compose.yml) builds from source for Docker Desktop, with data in `./data`. The one for the UGOS Docker app's Project feature comes in M2.
- Avoids host ports 9999 and 9443, which UGOS uses.

**Spytify 2.0.2's settings:** the controller passes these to each item's `spytifyd`, one `--set key=value` each, in this order ([settings.py](../controller/src/spotivault/settings.py), `build_recorder_settings`). Booleans take `true` or `false`. Every other setting keeps Spytify's default. A change saved in Settings applies from the next item.

| Setting | Spytify's default | What the controller passes |
|---|---|---|
| `output.dir` | `~/Spytify` | `/music` |
| `encode.format` | `mp3` | Settings › Recording's format: `aac` (the default), `mp3`, `flac` or `wav`. Always passed, since Spytify's own default is MP3 160. |
| `encode.bitrate_kbps` | `160` | 256 or 320. Left out for FLAC and WAV. |
| `output.group_by` | `artist/album` | The layout's folder part: `none`, `artist` for `{album_artist}`, or `artist/album` for `{album_artist}/{album}`. |
| `output.template` | `{album_artist} - {title}` | The layout's file name, after the last `/`. The default layout is `{album_artist}/{album}/{track} - {title}`. |
| `output.prefix` | `none` | The layout's Prefix: `none`, `counter` or `album_track` (Album track number). |
| `output.underscores` | `false` | The layout's "Underscores instead of spaces". |
| `output.ascii_filenames` | `false` | The layout's "Remove accents from file names". |
| `output.playlist` | `false` | `false`: the controller writes the `.m3u` itself. |
| `recorder.duplicates` | `skip` | `skip` |
| `recorder.skip_duplicates_forward` | `false` | `false` for items played as missing tracks only, `true` for items played whole (see [Run flow](#run-flow-per-playlist-or-album)). |
| `recorder.stop_with_player` | `false` | `false` |
| `tags.cover_size` | `medium` | `medium` |
| `privacy.bug_tracker` | `true` | `false`. The image's `spytifyd` is built without a crash-report address, so it sends nothing either way. |

The layout's rules, and how it maps to these settings, are [web-ui.md Q16](web-ui.md#open-questions) (resolved) and `contracts/vectors/layouts.json`. The controller never moves files: Spytify names them.

## Stack

Chosen at Gate A of the M1 plan (2026-11-15). The sizes were measured on test builds on top of the S2 image, which is 274 MB without a controller.

| Part | Choice | Why |
|---|---|---|
| Controller | Python 3.12, from Ubuntu's `python3` package, on asyncio | The maintainer reads Python. probe.py's tested logic carries over. |
| Controller libraries | FastAPI (with pydantic), uvicorn (no extras) with wsproto, httpx, jeepney (D-Bus) and the stdlib `sqlite3` | About +62 MB on the image, worked out from the measured parts; the S4 image measured +62 MB (Python 39 MB, the venv 23 MB). FastAPI is used for its request validation and typed models. Starlette on its own measured about +48 MB. uvicorn without extras has no WebSocket support, so `WS /api/events` and `WS /vnc` need wsproto (92 KB, pure Python, on the h11 uvicorn already uses; uvicorn sends the 20 s pings with it). Any other library must be worth its size, measured as in S2. |
| Web UI | React 19, TypeScript, Vite ([web/](../web/)) | Built in a Node builder stage. Only the built files ship in the image, and the controller serves them. |
| UI packages | `openapi-typescript` and `openapi-fetch` (the typed client, from `contracts/openapi.yaml`), `react-router`, `lucide-react`, `@novnc/novnc`, self-hosted Figtree and JetBrains Mono (`@fontsource`) | |
| Tests | pytest for the controller, on the fake world and the engine simulator, plus the real `spytifyd --fake` when its binaries are given. Vitest for the UI's parts and pages. Playwright for the UI, against a mock backend ([web/mock/](../web/mock/)) and against the controller in fake mode. | |

Go was the other finalist. It measured +11 MB and matches Spytify's track keys by construction, but Python is the language the maintainer can edit.

**Track keys:**
- **The rule:** Spytify lowercases with Go's `strings.ToLower` and trims with `strings.TrimSpace`. The controller uses probe.py's `go_lower` and `go_trim`, which match Go on every Unicode code point under Python 3.12 (all 1,112,064 checked at Gate A).
- **Python upgrades:** Python 3.13 and later use a newer Unicode version and would drift. `ubuntu:24.04` stays on 3.12. If the Python version ever changes, switch to a lowercase table generated from Go.
- **Checked against Go:** the keys in `contracts/vectors/track-keys.json` were also produced by Spytify's own Go code when the file was written (`generate.py --write --go`; 34 of 34 agreed at Gate A), so the vectors aren't only checked against our own port. CI recomputes the vectors from their inputs, and the controller's tests check its keys against them.

**The contract stays the source:** FastAPI builds its API description from the code, but `contracts/openapi.yaml` is the spec. The pydantic models are generated from the contract (with `datamodel-code-generator`, at development time only), and a test compares FastAPI's `/openapi.json` with the contract, so the code can't drift from it.

**Spytify's protocol:** Python can't import Spytify's Go package `pkg/proto`. The controller's types follow `pkg/proto/schema.json`, and integration tests run against `spytifyd --fake`.

### Fake mode

`python -m spotivault --fake` runs the controller against a simulated outside world instead of the container's. The tests use it, and so does the UI's development. The simulators follow the prototype's tested behaviour ([FINDINGS.md](../prototype/FINDINGS.md)) and the [Spytify bugs](upstream/spytify-bugs.md), so the run engine can be tested on them.

| Part | What it simulates |
|---|---|
| Player | The client's player and its MPRIS view. Tracks end in clock time. At the end of an album, track 1 loads paused. Another device can take playback over. The Web API reports relinked IDs and the Liked Songs alias. |
| Recorder | `spytifyd --once`: takes, duplicates, the idle exit with its phantom take, already-playing tracks, SIGTERM and SIGKILL, capture problems. It writes sparse files and Spytify's index into the music folder. |
| Client | The install, with `spotify-install`'s own progress lines (about 18 s), the login and the prefs file. |
| Web API | The S0 captures in `prototype/fixtures/webapi/`, filled out to their real totals, with the 2026 access rules. |
| Screen | A small VNC server behind `WS /vnc`. A click on its login screen stands in for scanning the QR code. |

- **Scenarios:** tests start from a fresh container. The dev server starts set up: the client installed and logged in, the Web API connected, and a library. `SPOTIVAULT_FAKE_SCENARIO=wizard` starts it fresh instead, for walking the setup wizard, with a client that logs itself in.
- **Time:** the simulators run on the controller's clock, so a test moves time by hand. `SPOTIVAULT_FAKE_SPEED` makes the dev server's world run faster, to watch whole runs.

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

Tested in the prototype; the evidence is in `prototype/FINDINGS.md` ("Implications for the design" and the S0 section). The run engine is [engine/](../controller/src/spotivault/engine/): `run.py` runs the queue, and `item.py` plays one item. An item is played one of two ways (plan D1):
- **Missing tracks only:** albums, Liked Songs and playlists you own or collaborate on. The controller has the track list, so it plays only what isn't recorded yet.
- **Whole:** followed and linked playlists, which have no track list (see [Web API usage](#web-api-usage)).

**Before the first item,** the pre-run check runs, in this order ([precheck.py](../controller/src/spotivault/engine/precheck.py)). A failed step ends the run Failed, with its reason.
- **Setup** is complete, and the Web API is connected.
- **The client** is installed and, while it runs, logged in.
- **Our device** is listed. If it isn't, the client is restarted once, and the device has 60 s to show up.
- **The Auto checklist rows** haven't drifted.
- **`/music`** is writable, with at least 2 GB free.
- **The catalog refresh.** It never fails the run: an item whose track list it couldn't read plays whole, or keeps its stored list.

**Another device playing** (plan D6): when the check finds one, the run starts Paused, and never takes playback from you. Resume pauses that device, then starts the item.

1. **Plan.** No Web API call here: the run's catalog refresh already stored every track list.
   - **Missing tracks only:** the stored track list, fetched with `market=from_token`. Leave out entries with `is_playable: false`, local files, episodes and empty entries. Look each one up in Spytify's duplicate index (`/music/.spytify/recorded.jsonl`) by Spytify's own key: the first artist and the title, trimmed and lowercased the Go way. An entry counts only while its file exists. **Nothing missing:** the item is Up to date, and no recorder starts.
     - **No list to trust:** an item whose list was never fetched, or that isn't tracked (the run's refresh doesn't fetch those, so its stored list may be old), plays whole instead. An empty or old list would look like "nothing missing". An item whose list this run's refresh couldn't read keeps the list stored before.
   - **Whole:** the item is Up to date without playing if its `snapshot_id` is the one from its last clean full pass **and** every track seen in that pass is still in the index. A deleted file forces a full pass. A clean full pass is one that ended normally and was heard to its end (Spotify went back to the playlist's first track), with no failed track, no track skipped for a reason a later pass could fix (seeked, low quality, silent, incomplete), and no interruption. A pass the loop guard paused is never clean.
     - **A fresh `snapshot_id`:** the run's own catalog refresh reads linked playlists' `snapshot_id` first, before any track list. If the refresh couldn't read an item's `snapshot_id` (the listing failed, Spotify stopped answering, or it's a linked playlist that isn't tracked: Back up now runs those too), the stored one may be stale, so the item plays whole.
   - **Unavailable:** an item removed from the Library, or found gone by the run's refresh, isn't played. Neither is an album with no track playable in your country.
2. **Check, then prepare the player.**
   - **Check:** our device must still be listed and `/music` must pass the storage check, or the run fails. If another device is playing, the item goes back to the head of the queue and the run pauses, as in D6 above.
   - **Prepare:** pause, seek to 0, and turn shuffle and repeat off. The pause is sent only when the check's `GET /me/player` shows something playing: with nothing playing, Spotify answers it 403 "Restriction violated". Spytify won't record a track the player is paused on more than 300 ms in, and it misses a restart within 2 s of that point, so seeking to 0 first matters ([Spytify bugs](upstream/spytify-bugs.md) #2).
3. **Start the recorder:** `spytifyd --once --serve --idle-exit 20s` for this item, with every recorder setting passed as `--set` (see [Container](#container)). `recorder.skip_duplicates_forward` is **off** for missing-tracks-only items and **on** for whole items. With it on, Spytify presses Next on the paused track 1 at the end of an album ([Spytify bugs](upstream/spytify-bugs.md) #1), and the whole playlist can play again, every track a duplicate. So whole items get a loop guard: two tracks in a row that come round again in the order they were first heard pause the player. One repeat alone doesn't: a playlist can list a track twice, and Spytify skips it and moves on. Then `player.control full_volume`.
4. **Play:** `PUT /me/player/play` with the container's `device_id`, the item's `context_uri` and an `offset`.
   - **The offset is by URI**, at the first missing track. `offset.position` counts only playable entries, so after an unplayable entry it lands on a later track.
   - **A 404 from the play:** Spotify answers 404 for a device it doesn't know, too. If our device isn't listed any more, the run fails (device missing). Otherwise the item is Unavailable in this run only; whether it's gone for good is the catalog refresh's to decide.
   - **Liked Songs** is the context `spotify:user:<id>:collection`. The Web API then reports it as a playlist URI (`spotify:playlist:37i9dQZF1F…`), and the controller treats that as the same context.
5. **Steer:** on each `track.started`, identify the loaded track by MPRIS `mpris:trackid`, which names the context's own entry. `GET /me/player` can report a relinked track ID, and `linked_from` is gone. If the track is planned, it plays. If not, the controller jumps to the next missing track (another play with an `offset` by URI) or, when none is left, pauses. A jump costs about 2 s of a track that's never saved. A planned track that Spytify skips as a duplicate (it's listed twice, or the keys differ) is jumped over the same way: with skip-forward off, it would play to its end unrecorded.
   - **Fallbacks** (plan D10): MPRIS's metadata can lag, so its track ID counts only once its title agrees with the take's. Otherwise `GET /me/player`'s track ID is used, but only when it names an entry with that title. When neither names an entry, the track is matched by its title.
   - **Steering guard:** a planned track that starts a second time pauses the player and ends the item, so a misfire can't loop.
6. **End:** Spotify pauses at the end of an album or playlist, and the controller pauses when the plan is done. After 20 s of silence, `spytifyd` saves the last track and exits (`--idle-exit 20s`), about 20–27 s after the pause.
   - **Telling the end from a stall:** Spotify ends a context by loading its first track and pausing within 1.5 s of its start. The controller checks the loaded track against MPRIS: the item's first playable track, or for a whole item the first track heard. A pause anywhere else is a stall, even at the start of a track.
   - **Stop now while the item is finishing:** playback is already over, and the last track, often played in full, waits for the idle exit to be saved. A stop now would make Spytify reject it, so the controller stops after this track instead, and the track is saved at the idle exit, well inside the 40 s shutdown bound.
   - **No client restart is needed.**
   - **Read every event**, including those written as the process exits. The last take's `track.finished` arrives then, and the `--events` file holds it too.
   - **Pause the player** in case it started again, and recompute what's missing from the index. **Count distinct tracks, not events:** a phantom `track.started` + `track.skipped` for the paused track 1 is normal at the idle exit.
   - **A pause nobody here asked for**, in the middle of an item, is a takeover or a stall. `GET /me/player`, read on the pause, tells them apart.
     - **Another device takes over** (it's the active device, on a pause or at a check): the controller stops the session at once, and never touches the player again, since pausing our client then could pause your phone. The take playing fails, the item ends Interrupted, and the run pauses ("Playback moved to …"). Resume pauses that device and runs the item again first.
     - **A stall** (the network, or the client): the item ends Interrupted when the recorder's idle exit ends the session, 20 s after the pause. It's re-queued once, at the end of the queue, and the tracks already recorded are skipped.
     - **A second interruption** of the same item in the same run, of either kind, ends it Partial.
   - **The context moves on** (autoplay): the controller stops the session at once and ends the item. A whole item then ends Partial, and its pass isn't a clean full pass.
   - **`GET /me/player` lags a play:** for a moment after the play, it can still report the context and device from before it. A real run read the album of two runs before, 1.3 s after the play answered. So until it has shown the container's device on the item's context once, a takeover by the device that was active before the play, or the context that was playing then, isn't acted on at once. Any other device or context can't be the old state, so it's acted on at once: autoplay's radio is still stopped at its first track. For the old state, if MPRIS names one of the item's tracks at a track's start or the 60 s check, the context hasn't moved on. Otherwise the controller reads it again 2 s later, 3 times at most, then acts on what it still reports. MPRIS never vouches at a pause: a takeover pauses our player, and the old state could hide it. For the same reason, a pause during the re-reads isn't taken for the end of the context until they're over. When Liked Songs was playing before the play, its alias is learned from a read naming the track playing now.
   - **Timeouts** (as built; the numbers are the defaults in `engine/types.py`, `Timeouts`):
     - **Recorder socket:** it must answer within 15 s, or the start fails with the recorder's exit code (see [Exit codes](#exit-codes)).
     - **Playback never starts:** after 30 s with no `track.started`, the controller plays the item again. After 90 s, it sends SIGTERM and the item fails (`recorder_timeout`).
     - **Finishing:** the recorder must exit within 20 s (the idle exit) plus 40 s of the end. Otherwise, SIGTERM.
     - **Whole item:** its time limit is 1.25 × its planned length + 10 min. The planned length is its last full pass, else its track count × 5 min, else 6 h. At the limit, the controller stops the recorder after this track (`session.stop {now: false}`): the take playing is finished, and the item ends Partial. If the recorder still runs 30 s after that take's end, SIGTERM.
     - **Pause nobody here caused:** the item ends Interrupted when the recorder's idle exit ends the session. A recorder still running 60 s after the pause gets SIGTERM.
     - **Stopping the recorder:** SIGTERM (it finishes the current take), then after 45 s SIGTERM again (it stops at once), then after 15 s SIGKILL. When SIGTERM stands in for a stop after this track (the socket didn't answer, or spytifyd dropped it), the first wait lasts at least until the take's end plus 30 s.
     - **Web API checks:** `GET /me/player` every 60 s during an item, at each track start (at least 5 s apart) and on each pause. Before it has caught up with the play, a mismatch that could be the state from before the play is read again every 2 s, 3 times at most, so a real takeover or context change waits 6 s at most.
     - **No client restart on a timeout:** an earlier version of this spec restarted the client as the fallback. That isn't built: a timeout fails the item, and only the pre-run check restarts the client, when our device isn't listed. Whether to add it is open for the user: see [controller/ARCHITECTURE.md](../controller/ARCHITECTURE.md#whats-left-to-build).
7. **Files** ([files.py](../controller/src/spotivault/files.py)): for a playlist or Liked Songs, never an album, and only while "Write .m3u playlists" is on, write `Music/Playlists/<name>.m3u`, in the Web API's track order, with paths relative to the `.m3u`. An Up to date item's is written again too, so a reordered playlist's stays current. A recorded track that has since become unplayable stays listed while its file is there. For a whole item, use the order the tracks were recorded in: the last clean full pass's, then the tracks recorded since. A file with the playlist's name that the controller didn't write is never replaced: the playlist gets the name with " (<first 6 characters of its id>)". After each item, its recorded files get the mode `UMASK` gives them, since Spytify leaves tagged files at 0600 ([Spytify bugs](upstream/spytify-bugs.md) #7).
   - **Its cover file** next to the `.m3u` (see [Playlist covers](#playlist-covers)) isn't built in M1. It waits on [web-ui.md Q14 and Q15](web-ui.md#open-questions).

The scheduler queues items. An item forced from the UI goes right after the current item. One item records at a time.
- **Run now** covers every tracked playlist, Liked Songs included, and the Queued and Partial albums. Unavailable items are left out.
- **Stop after this track** lets the take playing finish. **Stop now** discards it, and it counts as Skipped, not Failed: the next run records the track anyway.
- **A schedule window's end** stops the run after the current track, and the item it cuts is Carried over (plan D5). The window grid is set with `PUT /api/schedule`; its page comes after M1.

### Exit codes

The controller reads a `spytifyd` exit as one cause, and each cause has one action (`recorder/protocol.py`, `classify_exit`):

| Exit | Cause | What happens |
|---|---|---|
| 0 | `ok` | The session ended: an idle exit, a stop, or the player gone. |
| 2 | `bad_setting` | The run fails. A `--set` or the environment was refused. |
| 1, "another spytifyd is listening" on the socket | `socket_in_use` | Kill the leftover recorder, remove the socket and start once more. |
| 1, `session.start` error -32007 | `output_dir` | The run fails: the music folder can't be written to. |
| 1, `session.start` error -32002 | `ffmpeg` | The run fails: ffmpeg is missing. |
| 1, the log, events or config file can't be opened | `files` | The run fails. |
| 1, `session.start` error -32001 | `no_player` | The item fails: no player within 60 s (`--wait-target`). |
| 1, any other reason | `other` | The item fails. |
| Ended by a signal (SIGKILL) | `killed` | The item fails. |

A start that gives no exit code, such as a missing binary, reads as `killed`, so it fails the item and not the run. A cause for "can't be run" would fix that. It's open ([controller/ARCHITECTURE.md](../controller/ARCHITECTURE.md#whats-left-to-build)).

### Start-up recovery

When the container starts, it cleans up what a stop or a crash left behind, in this order. Each step stands alone: one that fails is logged, and the others still run.
1. **Unfinished runs** end `failed`, with reason `container_restarted`. Their counts are summed from their items. Their current item is Interrupted, their waiting items are Stopped, and a take still recording is failed `interrupted`. Nothing is published, since no client is connected yet.
2. **Orphan `spytifyd` processes** are killed.
3. **Stale sockets** under the runtime folder are removed.
4. **Stale files** in the music folder are removed: WAVs in `.spytify/` and Spytify's own `.part` files (`.mp3.part`, `.m4a.part`, `.flac.part`, `.wav.part`), older than 60 s. Another program's partial downloads and another Spytify's `.spytify` folder deeper in the share are left alone. Between items, only `.spytify/` is tidied; after a recorder was killed, the next cleanup walks the whole music folder once.
5. **The player** is paused, if it's playing.
6. **The client** is told that no run is going, so its restart and install are allowed again.

The scheduler starts after this. A window that a restart cut off starts again, unless its run was stopped by hand.

### Run metrics

While a run goes, one sample is written to `run_metrics` every 60 s (`metrics.py`). Each sample holds:
- **Spotify:** the RSS of every Spotify process, summed, and their CPU % over the last interval (100 = one core).
- **spytifyd:** its RSS and CPU %. NULL between items.
- **The controller:** its RSS and CPU %.
- **The client's cache:** the size of its cache folder.
- **Free space:** on `/music` and on `/config`.
- **Web API:** the requests in the last 30 s.
- **Loop lag:** the worst event-loop lag since the last sample, in ms.

A value that can't be read is NULL, and a failed sample is logged and skipped. The first sample of a run has no CPU figure.

## Web API usage

Spotify narrowed the Web API for Development Mode apps in February 2026: new apps from 11 February, existing apps from 9 March. spotivault only uses endpoints that are still available ([migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)).

| Endpoint | Used for | Page size |
|---|---|---|
| `POST https://accounts.spotify.com/api/token` | The PKCE code exchange, and refreshing the token. | — |
| `GET /me` | The display name ("Connected as …"). | — |
| `GET /me/playlists` | The playlist list, each with its owner, `snapshot_id` and `items.total`. | 50 |
| `GET /playlists/{id}/items` | A playlist's tracks. It replaces the removed `/playlists/{id}/tracks`. | 50 |
| `GET /playlists/{id}` | Name, owner, cover and `snapshot_id` for a pasted link, and a linked playlist's `snapshot_id` at a run's start. | — |
| `GET /me/tracks` | Liked Songs, newest first. | 50 |
| `GET /me/albums` | Saved albums, each with its first page of tracks. | 50 |
| `GET /albums/{id}/tracks` | The rest of an album longer than that first page. | 50 |
| `GET /me/player/devices` | Finding the container's device (wizard step 5, and the run's checks). | — |
| `GET /me/player` | During a run: another device playing (D6, takeovers), the context moving on (autoplay), and the fallback for the loaded track (D10). | — |
| The player controls: `PUT /me/player/play`, `pause`, `seek`, `shuffle` and `repeat` | Preparing the player and playing each item. Resume also pauses another device that's playing (D6). | — |

**This list is the whole allow-list.** [webapi/endpoints.py](../controller/src/spotivault/webapi/endpoints.py) builds every request from it, so the controller can't reach any other endpoint, Spotify's internal ones included. A new endpoint needs a change to this list first, then a migration for its `api_endpoints` row, then its entry in `endpoints.py`. `GET /me` and the listings run in the catalog lane, the device list and the player in the playback lane, and the token in a lane of its own (see Requests below). The scopes asked for are `playlist-read-private`, `playlist-read-collaborative`, `user-library-read`, `user-read-playback-state` and `user-modify-playback-state`.

**The 2026 rules that shape the design:**
- **Item access:** `/items` returns tracks only for playlists you own or collaborate on. Any other playlist returns 403. So followed and linked playlists have no track list until they're recorded. `/me/playlists` still gives a followed playlist's `items.total` (tested 2026-11-15, although the migration guide says it's left out). A linked playlist has no total: `GET /playlists/{id}` returns its name, owner, images and `snapshot_id`, with no `items`. A followed playlist you collaborate on has access and behaves like your own.
- **Renamed fields:** a playlist's contents moved from `tracks` to `items`, and each playlist entry's track from `track` to `item`. The controller reads only the new names there. **Library endpoints kept theirs:** `/me/tracks` entries still use `track`, and `/me/albums` entries use `album`, with the album's tracks under `album.tracks.items`.
- **Relinked tracks:** `GET /me/player` can report a relinked track ID instead of the playlist entry's own, and `linked_from` is gone. The controller identifies the loaded track by MPRIS `mpris:trackid`, and uses the player state only for the context and the device.
- **Offsets:** `offset.position` counts only playable entries, so the controller starts and jumps with `offset.uri`.
- **No batch lookups:** `GET /tracks?ids=` and `GET /albums?ids=` are gone. Everything the controller needs, `duration_ms` included, comes with the listings above, so it's stored when it's fetched.
- **Removed fields:** among others, `popularity` and `linked_from` on tracks, and `label` on albums. spotivault uses none of them.
- **Rate limits:** Spotify publishes no Development Mode numbers. Limits apply over a rolling 30 s window, plus quota buckets shared by every app on the developer account. A `429` carries `Retry-After`; see Requests below for how the controller handles it.

**Load:**
- **Fields:** the two playlist endpoints, `GET /playlists/{id}` and `/items`, ask only for what the controller stores, through the `fields` parameter. For a track that's its ID, title, artists, album, cover, `duration_ms`, `is_local` and `is_playable`. Spotify documents `fields` on those two only, so the other listings answer whole objects. Track listings add `market=from_token`, so `is_playable` comes back.
- **Playlists:** the controller stores each one's `snapshot_id` and refetches its items only when that changes.
- **Liked Songs:** it has no `snapshot_id`. The controller reads from the newest page until it reaches a track it already has, then compares `total`. If the total doesn't match, it refetches the whole list.
- **Albums:** they don't change, so they're fetched once, when added.
- **Example:** a first fetch of 23 playlists with 3,000 tracks, 2,000 Liked Songs and 100 saved albums is about 110 requests. A refresh where nothing changed costs at most 3 (a test checks it). A run's own refresh adds one per tracked linked playlist, for its `snapshot_id`.

**Requests:**
- **One at a time:** the controller sends one Web API request at a time, with a short pause between them (250 ms by default) during catalog refreshes. Playback calls during a run aren't delayed.
- **Retries:**
  - A `429` waits for `Retry-After`. Spotify's limits are per app, so the wait holds every lane, playback included. Without a `Retry-After`, it waits 5 s, 10 s, then 20 s.
    - A `Retry-After` over 120 s isn't waited out. The call fails at once with `rate_limited`, and while that hold lasts, other calls fail at once too: new ones, and ones already waiting for their turn.
  - A `5xx`, a `503` or a timeout is retried after 5 s, and the delay doubles on each further attempt, up to 3 retries. If a `5xx` also carries `Retry-After`, the longer of the two waits wins.
  - **One budget:** a call gets 3 retries in all, shared by `429`s, `5xx`s, timeouts and network errors. When they run out, the call fails with `rate_limited` (after a `429`) or `spotify_unavailable` (otherwise).
  - A `401` refreshes the token once, then retries. The resend goes on with what's left of the call's budget. A `403` or `404` is not retried: it's an answer (no item access, or the item is gone).
- **Counting:** the controller counts requests per catalog refresh and per run, with retries and `429`s counted separately. Each refresh and each run ends with one Controller log line, for example "Web API: 112 requests · 2 retried · 0 rate-limited". A rising rate-limited count is the early sign of a quota problem.
- **Usage log:** every attempt is a row in the database, kept 90 days: when, the endpoint *template* (`/playlists/{id}/items`, never an ID, a URL or a token), the status, the latency, the attempt number, `Retry-After`, the lane, and the refresh or run it was for.
  - **Warnings** in the Controller log: every `429`; more than 30 requests in 30 s (the `webapi_burst_threshold` setting); five `4xx` answers in a row from one endpoint (a `429` isn't counted); a refresh or run with more than twice the 7-day median of its kind, once three earlier ones exist to compare.
  - **Daily:** one summary line per endpoint for each UTC day, written once that day is over (a minute after midnight UTC). Rows older than 90 days are deleted then.
  - **Where the thresholds live:** `webapi_burst_threshold` is a row in the settings table, default 30. It isn't in Settings or `PUT /api/settings`, so nothing in the UI changes it. The other limits (five `4xx`s, twice the median, 90 days) are fixed in code.
  - **For later analysis:** `GET /api/webapi/usage?days=` returns the totals per endpoint per day and every `429`. No page shows it yet.

**Not used:** some tools, such as [zotify](https://github.com/Googolplexed0/zotify), log in as Spotify's own desktop client and call Spotify's internal endpoints. That gets around every Development Mode limit, followed playlists included. spotivault doesn't do this:
- it passes the controller off as Spotify's own client, which breaks the developer terms more directly than recording does;
- it raises the risk to an account that's used every night;
- the internal endpoints are undocumented and change without notice;
- it saves few requests here, because Liked Songs and albums cost the same either way.

## Backlog estimate

Recording happens in real time, so a backup takes about as long as the music still to record. The Dashboard's Full backup card, wizard step 9 and the Schedule preview all show this estimate, from one calculation (`GET /api/backlog`).

- **Catalog:** every tracked item's track list with `duration_ms`, kept in SQLite and refreshed as described in [Web API usage](#web-api-usage). It's refreshed at the start of each run, and when the Dashboard or Schedule page opens, at most once every 15 minutes. The Library's Refresh button refreshes it at once, whenever no run is going ([web-ui.md § Library › Header](web-ui.md#header)).
- **Items counted:** tracked playlists, Liked Songs included, and the albums on the Albums page. Unavailable items are left out.
- **What's recorded:** History's per-track records, keyed by Spotify track ID.
  - **As built, waiting on review:** S5 built it on Spytify's duplicate index (`recorded.jsonl`) instead: the tracks whose Spytify key is in it, the same test the run's planning uses ([Run flow](#run-flow-per-playlist-or-album) step 1). Every file History records is in that index, so the estimate agrees with what a run would record. It's open for the user ([controller/ARCHITECTURE.md](../controller/ARCHITECTURE.md#whats-left-to-build)).
- **Time left:**
  - the sum of `duration_ms` over tracks not recorded yet, counting each track ID once however many items it's in;
  - plus about 35 s for each item with something to record: a few seconds to start, and the 25–30 s Finishing tail;
  - local files (`is_local`), unplayable entries and entries with no `item` are left out, because they can't be played.
- **Finish date:** the controller walks the schedule's active hours forward from now until the time left is used up. With Manual only, there's no date.
- **Unknown items:** followed and linked playlists have no track list, so their length is unknown. They're left out of the figure and counted separately, unless they're Up to date by their `snapshot_id` and Spytify's index (plan D13; see [Run flow](#run-flow-per-playlist-or-album) step 1). A followed playlist's track count is known from `/me/playlists`, so the UI can show it, but not its duration.
- **Code:** [backlog.py](../controller/src/spotivault/backlog.py), checked against `contracts/vectors/backlog.json`. The estimate is worked out again after each catalog refresh, each album added and each run item, and a `backlog` event goes out when a figure changed.
- **Accuracy:** duplicates are skipped in seconds, so they barely count. The same song can have a different track ID on a single and on its album; it's counted twice but recorded once, so the estimate leans slightly high.
- **Not the run header:** while a run goes, the Dashboard's run header shows that run's own time left, not this estimate. It's worked out the same way over the run's queue only, from the stored durations: see [web-ui.md § Run header](web-ui.md#running-queue-first).

## Playlist covers

Each playlist's cover is saved next to its `.m3u`, with the same base name: `Music/Playlists/<name>.m3u` and `Music/Playlists/<name>.jpg` (or `.png`). When the playlist is renamed, both files are renamed.

**In M1, only the UI's cached covers are built** ([catalog/covers.py](../controller/src/spotivault/catalog/covers.py)), downloaded only from Spotify's image hosts. The cover files below, and custom covers, wait on [web-ui.md Q14 and Q15](web-ui.md#open-questions).

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
- **Source:** the `images` URL from `GET /me/playlists`, which the catalog refresh already fetches (its answer carries `images`; it takes no `fields`). For a linked playlist, it comes from `GET /playlists/{id}`.
- **Largest size:** the controller rewrites the URL before downloading, following [Spotify's image CDN](#spotifys-image-cdn) below. If the rewritten URL fails, it downloads the URL as returned.
- **When:** at step 7 of the run flow, only when the image ID (the part after the size) has changed since the last download. A playlist with a new grid of covers gets a new ID, so it's downloaded again.
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

- **CI:** two workflows. Neither pushes anything.
  - **[ci.yml](../.github/workflows/ci.yml),** on every pull request and every push to main: shellcheck; the controller's ruff and pytest; the web UI's `npm run check` (tokens, API types, colors, lint, typecheck, Vitest, the build, and Playwright on the mock) and its Playwright tests against the controller in fake mode; and, in a job of its own, the amd64 image build, then the [smoke test](../image/test/smoke.sh) with the client install.
  - **[contracts.yml](../.github/workflows/contracts.yml),** when `contracts/` or `prototype/probe.py` changes: Spectral lints `openapi.yaml`, the vectors are recomputed from their inputs, and `schema.sql` loads.
- **M1:** a local image only, built from source with [docker-compose.yml](../docker-compose.yml). M1 ends with the git tag `v0.1.0`, and no image is pushed.
- **Docker Hub:** publishing comes in M3, with its secrets.

The smoke test runs the same way by hand: `docker build -t spotivault:ci .`, then `image/test/smoke.sh spotivault:ci --install`. It checks that the container turns healthy, that only s6 runs as root, that `WS /vnc` reaches VNC and the web UI is served, the controller's venv, the setup endpoints of wizard steps 1, 2, 4 and 6, the `spytifyd` version and the shim, fake recordings in AAC, MP3 and FLAC, that bad settings stop the container, the client install with its progress on `WS /api/events`, a quick stop, and that `init-spotivault` writes `/config` as `app`.

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

Real runs on Docker Desktop settled these (2026-11-21 and 22, Spytify 2.0.2; details in [testing/e2e.md](testing/e2e.md)):
- **An album** records, and its re-run is Up to date in seconds.
- **A deleted file** records again, alone.
- **A phone takeover** pauses the run and names the phone, and Resume brings it back.
- **Both stop modes**, a `docker restart` mid-item, and a schedule window ending mid-item (Carried over).
- **A music folder `app` can't write** stops the run in its pre-run check.
- **The Web API load:** 250 requests over the session, with no 429s and no retries.

**Spytify's own bugs**, and what the controller does about them, are in [upstream/spytify-bugs.md](upstream/spytify-bugs.md). Nine are logged so far. No local patch is applied: [image/spytify/patches/](../image/spytify/patches/) holds none yet, and one is added only with the user's OK.

Still to validate:
- **Cover sizes on the CDN:** the size rewrites in [Spotify's image CDN](#spotifys-image-cdn) rely on undocumented naming. Tested on public playlists on 2026-11-15; re-check before release, and whenever the fallback warning starts showing up.
- **A playlist with a gap, and a followed playlist, on a real account:** an owned playlist with an unplayable entry in the middle, and a followed playlist that plays whole, then is skipped as unchanged (D13). S0 recorded a playlist with unplayable entries and played a followed playlist with probe.py, but neither has run through the controller yet, and D13's skip hasn't run on a real account ([testing/e2e.md](testing/e2e.md), S6 4 and S6 5).
- **The session's fixes in the real container:** they pass the tests and the smoke test, but no real run has used a rebuilt image yet.
- **Long unattended runs:** step S10 of the M1 plan, a 2–3 h scheduled run, then an analysis of its metrics.

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
