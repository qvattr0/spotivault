# spotivault controller

The controller is the web UI's server and the brain of the container: the REST and WebSocket API, the client manager, the run engine and the scheduler. It's Python 3.12 on asyncio, with FastAPI, uvicorn, httpx, jeepney and the stdlib `sqlite3` ([design.md § Stack](../docs/design.md#stack)).

The API's shapes come from [contracts/](../contracts/): `openapi.yaml` (REST), `events.md` (`WS /api/events`) and `schema.sql` (the database). **The contract wins over the code.** Where a contract and a spec in `docs/` disagree, the spec wins: report it, don't diverge silently.

## Running it

Everything runs from `controller/`. uv is at `~/.local/bin/uv`; the venv is `controller/.venv`, on the system's Python 3.12 (the same as `ubuntu:24.04`'s).

| Task | Command |
|---|---|
| Install or update the venv | `uv sync` |
| Tests | `uv run pytest` |
| Lint | `uv run ruff check` |
| Format | `uv run ruff format` |
| Dev server, fake mode | `uv run python -m spotivault --fake --port 8181`, then `curl http://127.0.0.1:8181/api/health` |
| Dev server, walking the wizard | `SPOTIVAULT_FAKE_SCENARIO=wizard uv run python -m spotivault --fake --port 8181` |
| Dev server with the web UI | Start the dev server above, then `cd web && SPOTIVAULT_BACKEND=http://localhost:8181 npm run dev`: the UI at http://localhost:5173, against this controller. The dev proxy sends the controller's Host, and rewrites Origin to the controller's only for the dev page's own requests, so the request guard lets the UI through and still refuses other sites ([web/README.md](../web/README.md)). |
| The UI against fake mode, end to end | `cd web && npm run e2e:controller`: builds the UI, starts this controller on a free port, and runs [web/e2e-controller/](../web/e2e-controller/). |
| Regenerate the API models | `uv run python scripts/gen_models.py` (`--check` only compares) |

- **Fake mode** simulates the Spotify client, its player, the recorder, the Web API, the volumes and the screen. It keeps its data in `controller/.dev/` (git-ignored). It's what the UI is developed against (S7, S8).
  - **Scenarios** (`SPOTIVAULT_FAKE_SCENARIO`): `demo` (the default) starts set up, with the client logged in, the Web API connected and a library. `wizard` starts fresh, and the client logs itself in 20 s after it starts (a click on the fake VNC screen does it at once). `fresh` is a new container, as the tests use it.
  - **Speed** (`SPOTIVAULT_FAKE_SPEED`): the simulated world runs that many times faster, to watch whole runs.
  - Delete `controller/.dev/` to start again from nothing.
- **In the container**, s6 runs `python -m spotivault` as the `app` user on port 8080, in real mode.
- **In the image** (the [Dockerfile](../Dockerfile), owned by image-ci):
  - **The venv** is `/opt/spotivault/venv`, built from `uv.lock` without the dev group, on Ubuntu's Python 3.12. The package is installed as a wheel and byte-compiled; `app` can't write there. s6 runs `/opt/spotivault/venv/bin/python -P -m spotivault` ([its run script](../image/rootfs/etc/s6-overlay/s6-rc.d/controller/run)).
  - **The web root**, `/usr/local/share/spotivault/web`, holds noVNC's core in `novnc/` (`core/`, `vendor/` and the licences, pinned by sha256). `/vnc.html` is the controller's own copy, `web/static/vnc.html`, which imports `novnc/core/rfb.js` from there. The UI build (S7) goes in the same folder and must keep `novnc/`.
  - **A new runtime dependency** goes in `pyproject.toml` and `uv.lock`; the image picks it up from the lock file. A new system tool goes in the Dockerfile's controller runtime layer (`python3`, `x11-utils` for `xwininfo`).
- **Exit codes:** 2 for a bad setting, 1 when a background task failed (s6 then restarts it), 0 for a clean stop.

## Environment

`config.py` reads these once, at start-up. Nothing else reads `os.environ`.

| Variable | Default | Meaning |
|---|---|---|
| `TZ` | `UTC` | The schedule's time zone. Set in the UGOS Docker app. |
| `UMASK` | `000` | 3 or 4 octal digits. Applies to `/music` only, through the recorder. |
| `DEVICE_NAME` | `spotivault` | The Spotify Connect device name. |
| `UI_PASSWORD` | unset | Not enforced in M1 (plan D11). Only reported, and never logged. |
| `SPOTIVAULT_FAKE` | `0` | **New.** `1` turns on fake mode, like `--fake`. |
| `SPOTIVAULT_HOST` | `0.0.0.0` | **New.** The address to listen on. `--host` overrides it. |
| `SPOTIVAULT_PORT` | `8080` | **New.** The port. `--port` overrides it. |
| `SPOTIVAULT_CONFIG_DIR` | `/config` (fake: `./.dev/config`) | **New.** The config volume. |
| `SPOTIVAULT_MUSIC_DIR` | `/music` (fake: `./.dev/music`) | **New.** The music volume. |
| `SPOTIVAULT_WEB_ROOT` | `/usr/local/share/spotivault/web` | **New.** The built web UI (`index.html`, `assets/`) and noVNC's core (`novnc/core/`, `novnc/vendor/`), which `/vnc.html` imports. `/vnc.html` itself ships in the package (`web/static/`); a copy in the web root wins. Layout and caching: `web/spa.py`. |
| `SPOTIVAULT_LOG_LEVEL` | `INFO` | **New.** `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `SPOTIVAULT_IMAGE_VERSION` | `dev` | **New.** The image's version, for Settings › Container. Set when the image is built. |
| `SPOTIVAULT_VNC` | `127.0.0.1:5900` | **New.** The VNC server that `WS /vnc` bridges to. |
| `SPOTIVAULT_ALLOWED_HOSTS` | empty | **New.** More names, separated by commas, the UI may be reached by: your own domain, a reverse proxy's. IP addresses, `localhost`, names without a dot and `.local`, `.lan`, `.internal` and `.home.arpa` names always work ([web/guard.py](src/spotivault/web/guard.py)). The tests set `spotivault.test`. |
| `SPOTIVAULT_FAKE_SCENARIO` | `demo` (tests: `fresh`) | **New.** Fake mode's starting point: `fresh`, `demo` or `wizard` ([fake/world.py](src/spotivault/fake/world.py)). |
| `SPOTIVAULT_FAKE_SPEED` | `1` | **New.** Fake mode's clock runs this many times faster than real time. |

Read as the image already sets them: `XDG_RUNTIME_DIR` (recorder sockets), `DISPLAY`, `DBUS_SESSION_BUS_ADDRESS` (MPRIS; defaults to `unix:path=$XDG_RUNTIME_DIR/bus`), `PULSE_SERVER`, `SPYTIFY_TARGET_MPRIS` (the client's MPRIS name), `SPYTIFY_FFMPEG` and `SPYTIFY_CONFIG`.

## How it fits together

```
__main__.py ─ load_config() ─ build_services(config) ─ create_app(services) ─ uvicorn
                                   │
                 Services: config, ports, store, bus, loopwatch, feature modules
                                   │
       ports (real or fake): clock, mpris, client, recorder, webapi, storage, desktop
```

- **Ports** (`ports.py`) are `typing.Protocol` interfaces for everything outside the controller. Each has a real implementation and a fake one (`fake/`). Code above them never knows which it has.
- **Services** (`services.py`) is built once. It holds the config, the ports (`services.ports.mpris` and so on), the store, the event bus and one object per feature module (`services.settings`, `services.client`, …).
- **Feature modules** take the Services object in their constructor and register what they need:

  ```python
  services.bus.add_snapshot("client", self.status)  # their part of the WS hello
  services.add_startup("client", self.start)  # awaited once, after the store opens
  services.add_background("client.watch", self.watch)  # a task from start-up to shutdown
  services.add_shutdown("client", self.stop)  # awaited at shutdown, newest first
  ```

- **Routers** (`api/routers/`, one per area) get the Services object with `services: ServicesDep` and raise `ApiError` for error answers. An endpoint a later step builds raises `not_built("operationId")`: 501 with the error envelope.
- **The lifespan** is `services.running()`: it opens the store, runs the start-up hooks, then the background tasks in one `TaskGroup`. A background task that fails is logged with its traceback and stops the controller, so no error is ever lost. If the database can't be opened, the controller still serves, and `GET /api/health` answers 503.

### What the built modules offer

What S5 and S6 call. Each module's docstring has the details.

| Module | Call | For |
|---|---|---|
| `services.settings` | `await recorder_settings("missing_only" \| "whole")` | S6, at each item's start: the `(key, value)` pairs for `--set`. FLAC and WAV get no bitrate; `output.playlist=false`, because the controller writes the `.m3u`. The pure version is `settings.build_recorder_settings()`. |
| | `await get_value(key)`, `await set_value(key, value)` | S6's `run_order`, and any setting without its own endpoint. |
| | `add_listener(fn)` | `fn(keys)` is awaited after a PUT saves those keys (S5: `auto_track_owned`). |
| `services.storage` | `await check()` → `Storage` | The pre-run check (S6): refuse unless `.ok`; `storage.storage_problem(storage)` gives the message. |
| `services.setup` | `await is_complete()` | S6: refuse a run with `setup_incomplete`. |
| | `await mark_done("webapi" \| "albums")`, `await mark_failed("webapi", message)` | S5: step 5 once the token works and our device is listed; step 8 after `POST /api/albums`. |
| | `await refresh()` | After a fact behind a step changes. `complete()` finishes the wizard (`POST /api/setup/complete`). |
| | `await restart()` | "Run setup again". It refuses while `runs` has a row with `kind = 'run'` and `state <> 'ended'`, so S6 must keep that row current. |
| `services.client` | `await status()`, `await refresh()` | The client's `ClientStatus`, as last polled or read now. |
| | `await checklist()`, `await drifted_rows()` | The pre-run check (S6): refuse while `drifted_rows()` isn't empty. |
| | `await set_run_active(active)` | S6, when a run starts and when it ends, failures included. It drives `restartable` and the 409s of install and restart. |
| | `add_listener(fn)` | `fn()` is awaited after the status or the checklist changes. |
| `container` | `await spytifyd_version(config.spytifyd_path)` | S6's `Recorder.version()`. |
| `logs` | `redact(text, secrets=())` | Any text that might hold a token (S5's Web API errors). Every log line already goes through it. |
| `web.sockets` | `origin_allowed(origin, host, allowed_hosts)` | Any new WebSocket (`websocket_origin_allowed(websocket)` passes the config's names). The Host is already checked by `web.guard` for every request. |

**Restarting the client** (`services.client.restart()`): s6's control pipes belong to root, so the controller can't use `s6-svc` as `app`. It quits the client over MPRIS, kills its processes after 15 s if they're still there, and s6 starts it again, as the `spotify` service does on a stop. A Quit with no answer gets the 15 s too, since the client may be on its way out; only `MprisNoClient` (no bus, or nobody owns the name) means it's killed at once. The smoke test checks it on the real client.

## Module map

| Module | What | Built by (S4) |
|---|---|---|
| `__main__.py` | `python -m spotivault`: arguments, logging, uvicorn (`uvicorn_config()`: wsproto, pings every 20 s, no per-message deflate). | foundation |
| `app.py` | `create_app(services)`: every router, both WebSockets, the SPA last. | foundation |
| `config.py` | The environment, checked. | foundation |
| `clock.py` | `SystemClock`, and `iso_ms()`: the RFC 3339 UTC millisecond format of the database and events. | foundation |
| `ports.py` | The Protocols, their value types and their errors. | foundation |
| `services.py` | `Services`, `build_services`, the lifecycle, the hello placeholders. | foundation |
| `events.py` | The event bus: envelope, seq, hello, bounded queues, `level` throttling. | foundation |
| `errors.py` | `ApiError`, the error envelope and every exception handler. | foundation |
| `store/` | SQLite: one worker thread, an async API, migrations. `001_initial.sql` is `contracts/schema.sql`. | foundation |
| `loopwatch.py` | The event-loop lag watchdog (over 250 ms: a warning). | foundation |
| `unbuilt.py` | Stand-ins for the real Web API (S5) and recorder (S6) in real mode. | foundation |
| `api/models.py` | Pydantic models generated from `openapi.yaml`. Never edited by hand. | foundation |
| `api/deps.py`, `api/params.py` | `ServicesDep`, and the shared path and query parameters. | foundation |
| `api/routers/*.py` | One router per area. | the module's builder; S5 and S6 fill the rest |
| `settings.py` | Settings, layout validation, the `--set` mapping. | settings-storage-setup |
| `storage.py` | The storage check; `LocalStorageProbe`. | settings-storage-setup |
| `container.py` | Read-only container facts. | settings-storage-setup |
| `setup.py` | The wizard's step states. | settings-storage-setup |
| `client/` | Install, status, login, checklist, `LocalClientControl`, `JeepneyMpris`. | client |
| `web/` | `WS /api/events`, the `WS /vnc` bridge, the SPA, and `guard.py`: the Host check on every request and the Origin check on changes (403 `forbidden`). | web |
| `desktop.py` | `LocalDesktop`: X, PulseAudio and VNC for health and `/vnc`. | web |
| `logs.py` | Logging setup. | web |
| `fake/` | The fake world (`world.py`): catalog, player, MPRIS, client, recorder, Web API, volumes, and a desktop with a VNC screen. Scenarios `fresh`, `demo` and `wizard`. | fake |

## What's left to build

S4's ownership rules are retired; a later step that splits work between agents sets its own.

- **S5:** `api/routers/spotify.py`, `library.py`, `albums.py`, `backlog.py` and `webapi.py`, and the real Web API port that replaces `UnbuiltWebApi` in `unbuilt.py`. The fake one is `fake/webapi.py`.
- **S6:** `api/routers/status.py`, `runs.py` and `schedule.py`, and the real recorder port that replaces `UnbuiltRecorder`. The fake one is `fake/recorder.py`.
- Until then those endpoints answer 501 with the error envelope.

**Keep these stable**, because services.py builds them: the constructor `XService(services)` of each feature module, and the real port classes `LocalClientControl(config, mpris)`, `JeepneyMpris(config)`, `LocalStorageProbe()` and `LocalDesktop(config)`.

## Conventions

**asyncio: never block the event loop** ([design.md § Stack](../docs/design.md#asyncio-never-block-the-event-loop)). One blocking call freezes the API, both WebSockets, the `/vnc` bridge and the engine's steering.

| Never, in async code | Instead |
|---|---|
| `requests`, `urllib`, a sync `httpx.Client` | `httpx.AsyncClient` |
| `subprocess.run`, `os.system`, `dbus-send` | `asyncio.create_subprocess_exec`; jeepney's asyncio router |
| `time.sleep` | `await services.clock.sleep()` (or `asyncio.sleep`) |
| `sqlite3` | `services.store` (its one worker thread) |
| File reads, folder walks, `os.stat` on volumes | `asyncio.to_thread` |

- **Routes are `async def`.** Ruff's `ASYNC` rules flag blocking calls inside them.
- **Tasks:** start them through `services.add_background`, or in a `TaskGroup`. Never a bare `create_task` that nobody awaits.
- **Time:** ask `services.clock`, never `datetime.now()`, so tests can use the fake clock. Write times with `clock.iso_ms()`.

**The database:**
- `await store.fetchone/fetchall/fetchval/execute(sql, params)` for one statement.
- `await store.transaction(fn)` runs `fn(conn)` on the database thread inside `BEGIN IMMEDIATE … COMMIT`, rolled back if it raises. Keep `fn` short and plain.
- A schema change is a new migration, `store/migrations/002_<what>.sql`. Never edit `001_initial.sql`: a test keeps it identical to `contracts/schema.sql`.

**Events:** publish only after the change is committed: `services.bus.publish("client.status", model)`. The type must be one of `events.EVENT_TYPES`. The hello's five keys (`setup`, `status`, `connection`, `client`, `backlog`) start as placeholders in services.py; the owning module replaces its key with `add_snapshot`.

**The API:**
- Request and response types come from `api/models.py`. When the contract changes, regenerate the models: never edit them.
- Error codes are the contract's `ErrorCode` values. A wrong one fails in tests, because the envelope is built with the generated model.
- A Web API error a router doesn't catch becomes the matching envelope (`not_connected`, `connection_expired`, `rate_limited`, `spotify_unavailable`). `NoAccess` and `NotFound` are answers, which routers usually handle themselves.

**Code style:** plain, explicit, type-hinted code that the maintainer can edit. Short docstrings on anything that isn't obvious. No metaprogramming. `ruff format` formats everything; lines are 100 characters.

## Tests

- **No outside world:** tests never touch the network, real Spotify, Docker or the running containers. They run on fake ports. `world_of(services.ports)` gives the FakeWorld behind them, to change the world from the outside (`world.player.take_over("Pixel 9")`); `tests/fake_helpers.py` has `make_world`, `recorder_spec` and `Notes`.
- **Fixtures** (`tests/conftest.py`): `config_dir`, `music_dir`, `web_root` (temporary folders), `env`, `config`, `fake_clock`, `services`, `app`, `running_app` (lifespan entered) and `client` (an `httpx.AsyncClient` on the app).
- **The blocked-loop guard:** every test's loop runs in asyncio debug mode, and a callback slower than 100 ms fails the test. Build heavy things (apps, parsed files) in sync fixtures, not inside the test's coroutine. A test that blocks on purpose takes `@pytest.mark.allow_slow_callbacks`. After collection, conftest.py freezes what's loaded (`gc.freeze()`), so the garbage collector's full passes stay short under load.
- **Helpers:**
  - `asgi_ws.websocket_connect(app, path)`: a WebSocket client on the test's own loop.
  - `contract.assert_schema(name, value)` and `contract.assert_response(response, path)`: check against `openapi.yaml`.
  - `portcheck.assert_implements(cls, protocol)`: a port implementation's signatures match its Protocol. Check every implementation you build or change with it, in your own test file (`tests/test_ports.py` covers the foundation's).
- **The contract test** (`tests/test_contract_routes.py`) checks that every path, method, operationId, parameter and request body in `openapi.yaml` is served, and nothing else is, except the WebSockets and the SPA. It also calls every operation with the contract's examples and checks the answer's status and body against the contract. It keeps working as endpoints get built.
