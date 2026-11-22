<img src="docs/brand/logo.svg" width="96" alt="spotivault logo">

# spotivault

spotivault backs up your Spotify playlists, Liked Songs and saved albums as music files. It's one Docker image with a web UI. Inside it, the Spotify Linux client plays each playlist or album on a virtual screen, and [Spytify](https://github.com/spytify/spytify) 2.0.2 records what it plays, one file per track. Tracks it already has aren't recorded again.

**Status: M1,** the first version that does the whole job end to end. It runs on Docker Desktop for now. The NAS install (UGOS) comes in M2, and ready-made images on Docker Hub in M3. Until then, you build the image from this repository.

> **Spotify's terms:** recording breaks Spotify's terms of use, and accounts that used recording software have been suspended. Use a separate Premium account. Whether private copies are legal depends on your country.

> **LAN only:** the web UI has no password yet. `UI_PASSWORD` isn't enforced in M1: if you set it, the controller only logs a warning. Anyone who can reach port 8080 can use the UI and the client's screen. Never publish the port to the internet.

## What you need

- **Docker** on an amd64 (x86_64) machine. M1 is tested on Docker Desktop. The Spotify Linux client has no ARM build.
- **Spotify Premium.**
- **A phone with Spotify,** to log the container's client in by QR code.
- **A Spotify developer app** of your own, for the Web API. The setup wizard shows how to make one.
- **At least 2 GB free** in the music folder. A run won't start with less.

## Quick start

### With Docker Compose

From a clone of this repository:

```bash
docker compose up -d --build
```

Then open <http://localhost:8080>. [docker-compose.yml](docker-compose.yml) builds the image as `spotivault:dev`, names the container `spotivault-m1`, and keeps its data in `./data/config` and `./data/music` (git-ignored). It publishes port 8080 on `127.0.0.1` only. Set `TZ` there to your time zone.

### With docker run

```bash
docker build -t spotivault:dev .
docker run -d --name spotivault \
  --shm-size 1g --stop-timeout 60 --restart unless-stopped \
  -e TZ=UTC -e UMASK=000 -e DEVICE_NAME=spotivault \
  -p 127.0.0.1:8080:8080 \
  -v "$PWD/data/config:/config" -v "$PWD/data/music:/music" \
  spotivault:dev
```

To reach the UI from other computers on your LAN, publish `8080:8080` instead of `127.0.0.1:8080:8080`.

### What the container needs

| Setting | Compose / docker run | Why |
|---|---|---|
| **Port 8080** | `ports` / `-p` | The web UI, its API, and the client's screen through `/vnc`. It's the only port. |
| **`/config`** | a folder or volume | The database, the Spotify client and its login, the Web API token and the logs. It stays private: mode 0700, owned by uid 1000. |
| **`/music`** | your music folder | The recordings, the `.m3u` playlists and Spytify's index (`.spytify/`). uid 1000 must be able to write there. A new, empty folder that Docker made is handed to it. |
| **Shared memory** | `shm_size: 1g` / `--shm-size 1g` | The client is built on Chromium, which passes data through `/dev/shm`. Docker's default 64 MB is too small. |
| **Stop grace period** | `stop_grace_period: 60s` / `--stop-timeout 60` | On a stop, the controller stops the run and marks the item it was recording Interrupted, within 40 s. Docker's default 10 s would kill it first. |

### Environment variables

| Variable | Default | What it does |
|---|---|---|
| `TZ` | `UTC` | The time zone that schedule windows follow. A tz database name, such as `America/New_York`. |
| `UMASK` | `000` | 3 or 4 octal digits, for the files written in `/music` only. `000` lets everyone read and write them; `022` lets others only read them. `/config` stays private whatever it is. |
| `DEVICE_NAME` | `spotivault` | The client's name as a Spotify Connect device ("Playing on …"). At most 64 bytes, with no `/`. Changing it after setup is untested. |
| `UI_PASSWORD` | not set | **Not enforced in M1.** If it's set, the controller only logs a warning at start-up. |
| `SPOTIVAULT_ALLOWED_HOSTS` | empty | More names the UI may be reached by, separated by commas: your own domain, or a reverse proxy's. An IP address, `localhost`, a name without a dot, and names ending in `.local`, `.lan`, `.internal`, `.home.arpa` or `.localhost` always work. Any other name gets 403. |
| `SPOTIVAULT_LOG_LEVEL` | `INFO` | The controller's log level: `DEBUG`, `INFO`, `WARNING` or `ERROR`. |

A bad `TZ`, `UMASK` or `DEVICE_NAME` stops the container at start, with the reason in its log.

**The rest:** the image sets its own (`HOME`, `DISPLAY`, `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`, `PULSE_SERVER`, `SPYTIFY_*`, `S6_*`, `SPOTIVAULT_IMAGE_VERSION`). The other `SPOTIVAULT_*` variables are for development and tests ([controller/ARCHITECTURE.md § Environment](controller/ARCHITECTURE.md#environment)). `spotify-install` also reads `SPOTIFY_REPO` and `SPOTIFY_KEYRING`, to test against another repository.

## First run: the setup wizard

The web UI sends you to a nine-step wizard. A reload or a restart resumes it where you left off.

1. **Welcome:** the terms notice above.
2. **Spotify client:** the container installs the Linux client from Spotify's repository into `/config`, checking every download. It takes about 20 s.
3. **Log in:** the client's screen shows a QR code. Scan it with the Spotify app on your phone.
4. **Client settings:** a checklist of the client's settings that change the sound, such as crossfade and volume normalization. Change them on the client's screen beside it.
5. **Web API:** make a Spotify developer app with the redirect URI `http://127.0.0.1:8888/callback`, and paste its Client ID. Authorize, then paste back the address your browser ends up on. The error page there is expected.
6. **Output:** checks that `/music` is mounted and writable, and picks the format (AAC 256 by default).
7. **What to back up:** all your own playlists and Liked Songs, or pick them later in the Library.
8. **Albums:** all your saved albums, or pick them later in Albums.
9. **Done:** Back up now, or Open Library.

**After setup:**
- **Runs:** Run now on the Dashboard backs up every tracked playlist, and the Queued and Partial albums. The Dashboard shows the run live. Recording is real time.
- **Files:** tracks are saved as `Artist/Album/01 - Title.m4a` (Settings › Files changes the layout), and each playlist gets an `.m3u` in `Playlists/`.
- **History:** every run, with its tracks, and the Logs tab.
- **Schedule:** the Schedule page isn't in M1. A schedule is set through the API, with `PUT /api/schedule` ([web-ui.md § Schedule endpoints](docs/web-ui.md#schedule-endpoints)).

## Docs

Start with [docs/features.md](docs/features.md): every feature, its spec, its status and the build order.

| Doc | What's in it |
|---|---|
| [docs/design.md](docs/design.md) | The architecture, the container, the run flow, the Web API rules and covers. |
| [docs/web-ui.md](docs/web-ui.md) | Every page and its states, the REST and WebSocket endpoints, user flows and open questions. |
| [contracts/](contracts/) | The API contract: `openapi.yaml`, `events.md`, `schema.sql` and test vectors. |
| [controller/ARCHITECTURE.md](controller/ARCHITECTURE.md) | The Python controller: how to run and test it, its modules and its rules. |
| [web/README.md](web/README.md) | The React UI: its scripts, the mock backend, conventions and pages. |
| [docs/upstream/spytify-bugs.md](docs/upstream/spytify-bugs.md) | The Spytify bugs that affect spotivault, and the workarounds. |
| [docs/testing/e2e.md](docs/testing/e2e.md) | The manual end-to-end checklist, and its results. |
| [prototype/](prototype/) | The feasibility prototype and its findings. The image replaced it. |

## Development

| Part | Where | Built with |
|---|---|---|
| **Controller** | [controller/](controller/) | Python 3.12 on asyncio, FastAPI, uv |
| **Web UI** | [web/](web/) | React 19, TypeScript, Vite; Node 22.18 or later |
| **Image** | [Dockerfile](Dockerfile), [image/](image/) | `ubuntu:24.04`, s6-overlay, `spytifyd` built from source |

**Fake mode** runs the controller on a simulated client, player, recorder and Web API: no Spotify account, no Docker. It starts set up, with a library, and keeps its data in `controller/.dev/`. `SPOTIVAULT_FAKE_SCENARIO=wizard` walks the wizard from a fresh start instead.

```bash
cd controller && uv sync && uv run python -m spotivault --fake --port 8181
```

**The web UI** runs on Vite's dev server, with a mock backend. Its scenarios and controls are in [web/README.md § Mock backend](web/README.md#mock-backend).

```bash
cd web && npm install && npm run dev    # http://localhost:5173
```

`SPOTIVAULT_BACKEND=http://localhost:8181 npm run dev` uses the fake-mode controller instead of the mock.

**Tests:** CI ([ci.yml](.github/workflows/ci.yml)) runs these on pull requests and on main. It pushes no image.

```bash
(cd controller && uv sync --locked && uv run ruff check && uv run ruff format --check && uv run pytest)
(cd web && npm ci && npx playwright install chromium && npm run check && npm run e2e:controller)
docker build -t spotivault:ci . && image/test/smoke.sh spotivault:ci --install
```

- **`npm run check`:** the web UI's generated tokens and API types are current, and no colour is typed outside its two colour files. Then its lint, typecheck, unit tests, build, and Playwright tests against the mock.
- **`npm run e2e:controller`:** Playwright against the controller in fake mode.
- **`smoke.sh --install`:** starts the image, installs the real client, and checks the container.
- **Also in CI:** shellcheck on the image's scripts, and [contracts.yml](.github/workflows/contracts.yml), which lints the contract and checks its test vectors.

## Status

| Milestone | What |
|---|---|
| **M1** (now) | The whole job on Docker Desktop: the setup wizard, Library, Albums, runs, the Dashboard, the Player, History and Settings. |
| **M2** | The NAS: the UGOS install, permissions and overnight runs. |
| **M3** | The production version, published on Docker Hub. |

**Not in M1:** the Schedule page, the UI password, notifications, History's Tracks tab and custom covers. [docs/features.md](docs/features.md) has the status of every feature.
