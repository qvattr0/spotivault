# spotivault features

The index of everything spotivault has to do: each feature, where its spec is, its status, what it waits on, and the order to build it in.

This file only points. The specs are:
- [design.md](design.md): architecture, the run flow, Web API rules, and component rules for the design file.
- [web-ui.md](web-ui.md): every page, its states, the REST and WebSocket endpoints, user flows and open questions.
- `ui-design/spotivault.pen`: the screens, in Pencil.

Don't copy spec text into this file. When a spec changes, change it in its own document, then update the row here.

## Status

| Status | Meaning |
|---|---|
| Specified | Written up, and agreed with the user. Ready to build. |
| Needs review | Written up, but the user hasn't reviewed it yet. |
| Drifted | The `.pen` design has moved on and the docs haven't caught up. Ask the user before building it. |
| Blocked | Waits on an open question that changes what gets built. |
| Built | Implemented and working. Add the code location in the Notes column. |

Open questions are numbered as in [web-ui.md § Open questions](web-ui.md#open-questions) (Q1–Q16). "Risk" means the list in [design.md § Risks to validate](design.md#risks-to-validate). Neither blocks a feature unless the Status column says so. Until a question is answered, build the more cautious answer, as web-ui.md says.

## Known gaps in the docs

- **The docs are ahead of the `.pen` file** in one place: the backup-length line on wizard step 9 isn't drawn yet.
- **Spytify bugs** that shape the design are tracked in [upstream/spytify-bugs.md](upstream/spytify-bugs.md).
- **README.md** is out of date: it calls this a Docker Compose project and links to `jwallet/spy-spotify`, where design.md uses [Spytify 2.0](https://github.com/spytify/spytify).

## Build order

Each phase needs the one before it. Within a phase, the order is a suggestion.

### Phase 1: Container

| Feature | Spec | Status | Waits on | Notes |
|---|---|---|---|---|
| Base image: Ubuntu 24.04 or Debian 13, amd64 | [design.md § Feasibility summary](design.md#feasibility-summary) | Built | | `ubuntu:24.04`: [Dockerfile](../Dockerfile). glibc 2.39, which client 1.3.4 needs. |
| Lean image: static `spytifyd` 2.0.2, minimal ffmpeg, the client's libraries without the client, trimmed packages | [design.md § What's in the image](design.md#whats-in-the-image) | Built | | [Dockerfile](../Dockerfile), [image/](../image/). 336 MB uncompressed with the Python controller (62 MB of it), 274 MB without; the prototype was 1.43 GB. |
| s6-overlay services: Xvfb and window manager, x11vnc and noVNC, D-Bus, PulseAudio null sink | [design.md § Container](design.md#container) | Built | | [image/rootfs/etc/s6-overlay/](../image/rootfs/etc/s6-overlay/). matchbox-window-manager instead of openbox, for size. The controller bridges `WS /vnc` and serves `/vnc.html` ([web/static/](../controller/src/spotivault/web/static/)), with noVNC's core in its web root. |
| Startup checks for `UMASK`, `TZ` and `DEVICE_NAME` | [design.md § Startup checks](design.md#startup-checks) | Built | | [init-spotivault](../image/rootfs/etc/s6-overlay/scripts/init-spotivault). |
| Client install script: checked download, versions, `ldd` check, JSON progress | [design.md § The Spotify client](design.md#the-spotify-client) | Built | | [spotify-install](../image/rootfs/usr/local/bin/spotify-install). About 20 s on Docker Desktop. |
| Spotify client installed into `/config` on first start | [design.md § Container](design.md#container), [web-ui.md § 2. Spotify client](web-ui.md#2-spotify-client) | Built | | [client/](../controller/src/spotivault/client/) (`manager.py`, `install.py`, `control.py`): the controller installs a missing client on its first start, one install at a time, and relays the progress as `client.install` events. The smoke test watches it: about 22 s on Docker Desktop. Q13 resolved: 387 MB in `/config`, over https. |
| `DEVICE_NAME` preload library and a stable `/config/machine-id` | [design.md § Container](design.md#container) | Built | | [hostname-shim.c](../image/hostname-shim.c), [init-spotivault](../image/rootfs/etc/s6-overlay/scripts/init-spotivault). The device kept its name and ID across `--force-recreate` and an image update. |
| UGOS setup: port 8080, volumes, env vars, `docker-compose.yml` | [design.md § Container](design.md#container) | Specified | | Avoid host ports 9999 and 9443. Port, volumes and env vars are in the image; the local [docker-compose.yml](../docker-compose.yml) is for Docker Desktop. The UGOS compose file is M2. |
| CI: image build and smoke test | [design.md § Distribution](design.md#distribution) | Built | | [ci.yml](../.github/workflows/ci.yml), [smoke.sh](../image/test/smoke.sh). Pushes nothing. A `controller` job runs ruff and pytest; the smoke test also calls the setup endpoints and watches `WS /api/events` during the client install. |
| Image publishing to Docker Hub | [design.md § Distribution](design.md#distribution) | Specified | | M3. |

### Phase 2: Controller core

| Feature | Spec | Status | Waits on | Notes |
|---|---|---|---|---|
| SQLite store in `/config` | [design.md § Container](design.md#container) | Built | | [controller/src/spotivault/store/](../controller/src/spotivault/store/): WAL, mode 0600, one worker thread, migrations; `001_initial.sql` is `contracts/schema.sql`. |
| Settings store and `/api/settings` | [web-ui.md § Settings endpoints](web-ui.md#settings-endpoints) | Built | | [settings.py](../controller/src/spotivault/settings.py): one JSON row per setting, the layout rules of `contracts/vectors/layouts.json`, and the recorder's `--set` list. Also built: `GET /api/storage` ([storage.py](../controller/src/spotivault/storage.py)), `GET /api/container` ([container.py](../controller/src/spotivault/container.py); its `music_source` is the shared folder's own path, such as `/Music`, since the container can't see `/volume6`; agreed with the user, to check on the NAS in M2), and the wizard's step states with `/api/setup`, `/tos`, `/restart` and `/complete` ([setup.py](../controller/src/spotivault/setup.py)). |
| Live event stream `WS /api/events` | Endpoint tables in each [web-ui.md](web-ui.md) section | Built | | One socket; every page's events go through it. [contracts/events.md](../contracts/events.md); [events.py](../controller/src/spotivault/events.py) (the bus) and [web/events_ws.py](../controller/src/spotivault/web/events_ws.py) (the socket): `hello` first, 1013 for a client 256 events behind, pings from uvicorn. Pages from another site are refused ([web/sockets.py](../controller/src/spotivault/web/sockets.py)). |
| Fake mode: simulated client, player, recorder, Web API and screen | [design.md § Fake mode](design.md#fake-mode) | Built | | [controller/src/spotivault/fake/](../controller/src/spotivault/fake/). For the tests, S6's simulator tests and the UI's development (`python -m spotivault --fake`). Scenarios: `fresh` (tests), `demo` (the dev server) and `wizard`. |
| Optional UI password and sessions | [web-ui.md § Security](web-ui.md#security) | Specified | | |
| Refusing other sites' pages: the Host check and the Origin check on changes | [web-ui.md § Security](web-ui.md#security) | Built | | [web/guard.py](../controller/src/spotivault/web/guard.py), with the WebSockets' rule in [web/sockets.py](../controller/src/spotivault/web/sockets.py). Decided in S4's review, not yet agreed with the user: names outside the home-network ones need `SPOTIVAULT_ALLOWED_HOSTS`. |
| Log collection, rotation and download | [web-ui.md § Logs tab](web-ui.md#logs-tab) | Specified | | Collection and rotation are built: the controller logs to stdout ([logs.py](../controller/src/spotivault/logs.py): secrets masked, never blocks the loop), and s6-log keeps 10 files of 1 MB in `/config/logs/controller/`. The Logs tab, `GET /api/logs` and the zip are deferred past M1. |

### Phase 3: Spotify and Spytify

| Feature | Spec | Status | Waits on | Notes |
|---|---|---|---|---|
| Web API login: PKCE, token storage, 6-month expiry, Reconnect | [design.md § Feasibility summary](design.md#feasibility-summary), [web-ui.md § 5. Connect the Spotify Web API](web-ui.md#5-connect-the-spotify-web-api) | Specified | | |
| Web API client: one request at a time, retries, request counting | [design.md § Web API usage](design.md#web-api-usage) | Specified | | Read only the 2026 field names; library endpoints kept `track` and `album`. |
| Catalog refresh: playlists by `snapshot_id`, Liked Songs, saved albums | [design.md § Web API usage](design.md#web-api-usage) | Specified | | |
| Client login detection | [web-ui.md § 3. Log in to Spotify](web-ui.md#3-log-in-to-spotify) | Built | | [client/status.py](../controller/src/spotivault/client/status.py), [client/control.py](../controller/src/spotivault/client/control.py). Q2 resolved: `Users/*-user/` plus the window title (`xwininfo`), not MPRIS. The smoke test checks the logged-out window on the real client, and Reset login screen (MPRIS Quit, then s6). The logged-in case is checked in the E2E (S9). |
| Client settings checklist and pre-run check | [web-ui.md § 4. Spotify client settings](web-ui.md#4-spotify-client-settings) | Specified | | Q3 resolved: 6 Auto rows from the prefs file; crossfade, gapless and autoplay are Confirm rows. The checklist is built ([client/checklist.py](../controller/src/spotivault/client/checklist.py), `GET /api/client/checklist`, `POST /api/setup/checklist/confirm`). The pre-run check comes with S6, through `ClientManager.drifted_rows()`. |
| `spytifyd` per item: JSON-RPC over the Unix socket | [design.md § Feasibility summary](design.md#feasibility-summary) | Specified | | |

### Phase 4: Run engine

| Feature | Spec | Status | Waits on | Notes |
|---|---|---|---|---|
| Run flow per playlist or album | [design.md § Run flow](design.md#run-flow-per-playlist-or-album) | Specified | | Missing tracks only, offsets by URI, MPRIS track identity; unchanged followed playlists are Up to date by `snapshot_id`. |
| Queue and run order, which you can reorder | [web-ui.md § Run order](web-ui.md#run-order) | Specified | | Stored with the schedule (`run_order`). |
| Stop, resume, device takeover and interrupted items | [web-ui.md § Running: queue-first](web-ui.md#running-queue-first), [§ Warnings during a run](web-ui.md#warnings-during-a-run) | Specified | | |
| Scheduler: weekly hour grid, windows, carry-over, missed runs | [web-ui.md § How runs follow the grid](web-ui.md#how-runs-follow-the-grid) | Specified | | |
| File layout for new recordings | [web-ui.md § Files](web-ui.md#files) | Specified | | Changing it never renames or re-records existing files. Spytify names the files (Q16 resolved). Validation and the `output.*` mapping are built ([settings.py](../controller/src/spotivault/settings.py)); recording with them is S6. |
| `.m3u` writing | [web-ui.md § Files](web-ui.md#files) | Specified | | |
| Playlist covers: Spotify's at the largest size, or your own | [design.md § Playlist covers](design.md#playlist-covers) | Needs review | Q14, Q15 | |
| Backlog estimate | [design.md § Backlog estimate](design.md#backlog-estimate) | Specified | | |
| Run and track history | [web-ui.md § History](web-ui.md#history) | Specified | | Kept forever. The Library and Albums read it to know what's recorded. |
| Notifications: browser and webhook | [web-ui.md § Notifications](web-ui.md#notifications) | Specified | Q12 | Browser notifications need HTTPS. |

### Phase 5: Web UI

| Feature | Spec | Status | Waits on | Notes |
|---|---|---|---|---|
| Design system: tokens and components | [web-ui.md § Design language](web-ui.md#design-language), [design.md § Component Rules](design.md#component-rules) | Specified | | Built from the `.pen` component set. |
| Shell: sidebar, bottom bar, expiry banner | [web-ui.md § Navigation](web-ui.md#navigation) | Specified | | |
| Setup wizard, steps 1–8 | [web-ui.md § Setup wizard](web-ui.md#setup-wizard) | Specified | | Step 8 is Albums. |
| Setup wizard, step 9 (Done) and its backup length | [web-ui.md § 9. Done](web-ui.md#9-done) | Needs review | | The backup-length line isn't drawn yet. |
| Library: list, grid, detail, + modal | [web-ui.md § Library](web-ui.md#library) | Specified | | Followed playlists show "n / total"; linked ones "n recorded". |
| Library: custom playlist covers | [web-ui.md § Detail view](web-ui.md#detail-view) | Needs review | | |
| Albums | [web-ui.md § Albums](web-ui.md#albums) | Specified | | |
| Dashboard: idle and running | [web-ui.md § Dashboard](web-ui.md#dashboard) | Specified | | |
| Dashboard: Full backup card | [web-ui.md § Idle](web-ui.md#idle) | Needs review | | |
| Schedule page and week-grid modal | [web-ui.md § Schedule](web-ui.md#schedule) | Specified | | |
| History: Runs, Tracks and Logs tabs | [web-ui.md § History](web-ui.md#history) | Specified | | |
| Settings page, with the Edit layout modal | [web-ui.md § Settings](web-ui.md#settings) | Specified | | |
| Player: noVNC view, view-only during runs | [web-ui.md § Player](web-ui.md#player) | Specified | | |
| Animations | [ui-design/animations.md](ui-design/animations.md) | Needs review | | One idea so far: the wizard stepper. |

## Not planned

These are decided, so don't build them:
- ARM hosts, and more than one Spotify account ([design.md § Goals and non-goals](design.md#goals-and-non-goals)).
- Playlists made by Spotify, such as Discover Weekly and Daily Mixes ([web-ui.md § What's in it](web-ui.md#whats-in-it)).
- Logging in as Spotify's own client to reach internal endpoints ([design.md § Web API usage](design.md#web-api-usage), "Not used").
- Uploading covers to Spotify, and cover files or custom covers for Liked Songs ([design.md § Playlist covers](design.md#playlist-covers)).
