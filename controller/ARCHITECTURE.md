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
  - **Scenarios** (`SPOTIVAULT_FAKE_SCENARIO`): `demo` (the default) starts set up, with the client logged in, the Web API connected and a library. On a fresh `.dev`, the wizard is completed at start-up through its own actions (`fake/demo.py`), so Run now works at once. `wizard` starts fresh, and the client logs itself in 20 s after it starts (a click on the fake VNC screen does it at once). `fresh` is a new container, as the tests use it.
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

Read as the image already sets them: `XDG_RUNTIME_DIR` (recorder sockets), `DISPLAY`, `DBUS_SESSION_BUS_ADDRESS` (MPRIS; defaults to `unix:path=$XDG_RUNTIME_DIR/bus`), `PULSE_SERVER`, `SPYTIFY_TARGET_PROCESS` (the client's process name, default `spotify`), `SPYTIFY_TARGET_MPRIS` (the client's MPRIS name), `SPYTIFY_FFMPEG` and `SPYTIFY_CONFIG`. The recorder passes five `SPYTIFY_*` on to spytifyd: these four, and `SPYTIFY_SOCKET` (each item's own socket). The display, bus and sound ones go too (`recorder/process.py` `command_line`).

## How it fits together

```
__main__.py ─ load_config() ─ build_services(config) ─ create_app(services) ─ uvicorn
                                   │
                 Services: config, ports, store, bus, loopwatch, feature modules
                                   │
       ports (real or fake): clock, mpris, client, recorder, webapi, storage, desktop, cdn
```

- **Ports** (`ports.py`) are `typing.Protocol` interfaces for everything outside the controller. Each has a real implementation and a fake one (`fake/`). Code above them never knows which it has. Modules reach a port at call time (`self.services.ports.webapi`), never through a reference kept from their constructor: tests swap ports.
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
  - **Shutdown order:** the shutdown hooks (newest first), then the background tasks are cancelled and awaited, then the ports' HTTP clients close (`webapi`, `cdn`), then the store. A refresh still going never meets a closed client.

### What the built modules offer

What S6 calls, and what the S5 modules call each other through. Each module's docstring has the details.

| Module | Call | For |
|---|---|---|
| `services.settings` | `await recorder_settings("missing_only" \| "whole")` | S6, at each item's start: the `(key, value)` pairs for `--set`. FLAC and WAV get no bitrate; `output.playlist=false`, because the controller writes the `.m3u`. The pure version is `settings.build_recorder_settings()`. |
| | `await get_value(key)`, `await set_value(key, value)` | S6's `run_order`, `webapi_burst_threshold` (the usage log), and any setting without its own endpoint. |
| | `add_listener(fn)` | `fn(keys)` is awaited after a PUT saves those keys (S5: `auto_track_owned`). |
| `services.storage` | `await check()` → `Storage` | The pre-run check (S6): refuse unless `.ok`; `storage.storage_problem(storage)` gives the message. |
| `services.setup` | `await is_complete()` | S6: refuse a run with `setup_incomplete`. |
| | `await mark_done("webapi" \| "albums")`, `await mark_failed("webapi", message)` | S5: step 5 once the token works and our device is listed; step 8 after `POST /api/albums`. The setup router: step 8 on `POST /api/setup/albums/later` ("I'll choose in Albums"). |
| | `await refresh()` | After a fact behind a step changes. `complete()` finishes the wizard (`POST /api/setup/complete`). |
| | `await restart()` | "Run setup again": steps 2 to 9 back to `todo` (the answer), then the live checks at once, so steps 2, 3, 4 and 6 turn done again in their own `setup.state`. It refuses while `runs` has a row with `kind = 'run'` and `state <> 'ended'`, so S6 must keep that row current. |
| `services.client` | `await status()`, `await refresh()` | The client's `ClientStatus`, as last polled or read now. |
| | `await checklist()`, `await drifted_rows()` | The pre-run check (S6): refuse while `drifted_rows()` isn't empty. |
| | `await set_run_active(active)` | S6, when a run starts and when it ends, failures included. It drives `restartable` and the 409s of install and restart. |
| | `add_listener(fn)` | `fn()` is awaited after the status or the checklist changes. |
| `container` | `await spytifyd_version(config.spytifyd_path)` | S6's `Recorder.version()`. |
| `logs` | `redact(text, secrets=())` | Any text that might hold a token (S5's Web API errors). Every log line already goes through it. |
| `web.sockets` | `origin_allowed(origin, host, allowed_hosts)` | Any new WebSocket (`websocket_origin_allowed(websocket)` passes the config's names). The Host is already checked by `web.guard` for every request. |
| `services.ports.webapi` | `devices()`, `player_state()`, `play(...)`, `pause(...)`, `seek(...)`, `set_shuffle(...)`, `set_repeat(...)`, each with `scope=ApiScope("run", run_id)` | S6's playback calls. They go on the playback lane, ahead of waiting catalog calls, and count against the run. Errors: `ports.WebApiError` and its subclasses; NotConnected and ConnectionExpired are raised before anything is sent; RateLimited is raised at once while a long hold lasts. |
| `services.catalog` | `await refresh(trigger="run", run_id=...)` → `RefreshResult` | S6, at each run's start (awaited; it waits for a refresh already going). The only refresh that reads linked playlists' `snapshot_id` (D13), before any track list. `RefreshResult.snapshots_unread`: the followed and linked playlists, tracked or not, whose `snapshot_id` it didn't read (an untracked linked one never is); S6 plays those whole, whatever `d13_up_to_date()` says (design.md § Run flow step 1). |
| | `request_refresh("page_open" \| "setup" \| "item_added")` → bool | Sync, never raises. `page_open` is throttled to once every 15 min. A queued refresh is dropped if a run is going when its turn comes (read from the `runs` table). |
| | `await last_refresh_at()` | When the last refresh finished. |
| `services.connection` | `await connection()`, `await held_reason()` | S6: the pre-run check, held scheduled runs (`not_connected`, `connection_expired`; `expiring` holds nothing), `GET /api/schedule/next`. |
| `services.matching` | `await index()`, `invalidate()` | S6: planning reads the index; call `invalidate()` after each item, when new files are written. |
| | `await item_counts(ids)`, `await recorded_track_ids()`, `await d13_up_to_date(id)`, `await observed_all_in_index(id)` | S6's planning (D13) and the item's end. |
| `services.backlog` | `await update()` → `Backlog` | S6, after each run item. Publishes `backlog` when a figure changed. |
| `services.library` | `await item(id)`, `await publish(id)` | S6: an item's progress. `publish` sends at most one `library.item` per item per second and merges the rest. |
| `services.albums` | `await album(id)`, `await publish(id)` | The same for albums (`album.item`). |
| `services.webapi_usage` | `await finish_scope(ApiScope("run", run_id))` → `ScopeSummary` | S6, when a run ends: the counts for `runs.api_*`, and the "Web API: …" summary line. |
| | `await requests_last_30s()` | S6's `run_metrics`: the rolling 30 s counter. |
| `windows` | `weekly_windows`, `window_instances`, `await load_hours(store)` | S6's scheduler: the same windows the backlog's finish date walks. |
| `services.runs` | `status()`, `active()` → `ActiveRun`, `recorder_pid()`, `current()`, `create_run(items)`, `stop(mode)`, `resume()`, `remove_queued(item_id)`, `start_scheduled(window, *, trigger)`, `end_window()`, `set_window_end(end)`, `closing` | The run engine's routers, the scheduler (`start_scheduled` raises RuntimeError while a run goes or once `closing`; `set_window_end` when a PUT moves the end of the window in progress), the hello's `status` and the metrics (`active()`, `recorder_pid()`). Hooks: `recover()`, `serve()`, `shutdown()` (sets `closing`). |
| `services.schedule` | `get()`, `put(update)`, `next()`, `tick()` | The scheduler engine: its router and `GET /api/schedule/next`. Hooks: `start()`, `watch()`. |
| `services.history` | `list_runs(*, cursor, filter, limit)`, `last_run()`, `run(run_id)`, `run_item_tracks(run_id, item_id)`, `history_row(run_id)` | History: its router, and the run engine and the scheduler (`run.finished`). |
| `services.files` | `write_m3u(item_id)` → `Path \| None`, `cleanup_stale(folders=None)` → `CleanupResult`, `recorder_killed()`, `fix_modes(paths)` → int; `m3u_file_name(name)`, `m3u_entry(m3u_path, track_path)` | The item engine (the `.m3u` and the file modes at an item's end; `.spytify/` before each recorder start with `folders=[]`; `recorder_killed()` after a recorder ended by a signal) and start-up recovery (the whole music folder). |
| `services.metrics` | `sample(run_id)`, `store(sample)`; hook `watch()` | Run metrics, one sample every 60 s during a run. |
| `ports.recorder` | `start(spec)` → `RecorderSession` (`SpytifyRecorder`), `version()`, `kill_orphans()` | The item engine. A session has `call(...)`, `notifications()`, `wait()`, `terminate(...)`, `kill()`, `events_file()`, `pid` and `returncode`. Specs: `recorder/process.py`'s docstring. |

**Restarting the client** (`services.client.restart()`): s6's control pipes belong to root, so the controller can't use `s6-svc` as `app`. It quits the client over MPRIS, kills its processes after 15 s if they're still there, and s6 starts it again, as the `spotify` service does on a stop. A Quit with no answer gets the 15 s too, since the client may be on its way out; only `MprisNoClient` (no bus, or nobody owns the name) means it's killed at once. The smoke test checks it on the real client.

**Shared files:** several modules call these, so a change to one means running its callers' tests too. `test_contract_routes.py` covers the API. Keep the constructors stable, because `services.py` builds them: `XService(services)` for each feature module, and the real port classes `LocalClientControl(config, mpris)`, `JeepneyMpris(config)`, `LocalStorageProbe()`, `LocalDesktop(config)`, `SpotifyWebApi(config, clock, store, auth, *, transport=None)` and `HttpImageCdn(*, transport=None, ...)`.

- `ports.py`: `ImageCdn`, `FetchedImage`, the image errors, `spotify_image_url_allowed`, `WebApi.aclose`, `Ports.cdn`.
- `webapi/endpoints.py`: the only endpoints allowed (= the `api_endpoints` rows), their lanes and URLs, `REDIRECT_URI`, `SCOPES`, `endpoint_for`.
- `webapi/auth_store.py`: `AuthStore`, the `spotify_auth` row, `AuthRow.state(now)`, the 6-month expiry, listeners.
- `imagecdn.py`: `HttpImageCdn`, the real `ImageCdn`: Spotify's image hosts over https only, no redirects, 4 MB cap, 15 s timeout, JPEG or PNG.
- `catalog/tracks.py`: `replace_item_tracks` (writes `tracks` and `item_tracks` in the caller's transaction), `unplayable_reason`.
- `matching.py`: `go_lower`, `go_trim`, `track_key`, `web_track_key`, `RecordedIndex`, `ItemCounts`, `read_recorded_index`.
- `windows.py`: `DAYS`, `Hours`, `WeeklyWindow`, `Window`, `weekly_windows`, `window_instances`, `load_hours`.
- `catalog/covers.py`: `CoverUpdate`, `cover_url`.
- `connection.py`: `our_device`, `ConnectionService.connection`, `held_reason`.
- `catalog/refresh.py`: `RefreshTrigger`, `RefreshResult`, `refresh`, `request_refresh`, `last_refresh_at`.
- `store/migrations/002_s5_catalog.sql`: `followed_playlists`, `api_warnings`, `items.full_path`. A schema change is a new migration.
- `api/models.py` and `contracts/`: regenerated from the contract; never hand-edited.

## Module map

| Module | What | Built by |
|---|---|---|
| `__main__.py` | `python -m spotivault`: arguments, logging, uvicorn (`uvicorn_config()`: wsproto, pings every 20 s, no per-message deflate). | foundation |
| `app.py` | `create_app(services)`: every router, both WebSockets, the SPA last. | foundation |
| `config.py` | The environment, checked. | foundation |
| `clock.py` | `SystemClock`, and `iso_ms()`: the RFC 3339 UTC millisecond format of the database and events. | foundation |
| `ports.py` | The Protocols, their value types and their errors. The recorder's port is real from S6 (`recorder/`). | foundation, S5, S6 |
| `services.py` | `Services`, `build_services`, the lifecycle, the hello placeholders (`status` has none: the run engine registers it). | foundation, S6 |
| `events.py` | The event bus: envelope, seq, hello, bounded queues, `level` throttling. | foundation |
| `errors.py` | `ApiError`, the error envelope and every exception handler. | foundation |
| `store/` | SQLite: one worker thread, an async API, migrations. `001_initial.sql` is `contracts/schema.sql`; `002_s5_catalog.sql` is S5's; `003_s6_runs.sql` is S6's. | foundation, S5, S6 |
| `loopwatch.py` | The event-loop lag watchdog (over 250 ms: a warning). | foundation |
| `api/models.py` | Pydantic models generated from `openapi.yaml`. Never edited by hand. | foundation |
| `api/deps.py`, `api/params.py` | `ServicesDep`, and the shared path and query parameters. | foundation |
| `api/routers/*.py` | One router per area. S5 filled those for the Web API, Spotify, library, albums, covers, backlog. S6 fills `status`, `runs`, `history` and `schedule`. | S4, S5, S6 |
| `settings.py` | Settings, layout validation, the `--set` mapping, and the settings keys the controller reads itself (`run_order`, `webapi_burst_threshold`). | settings-storage-setup |
| `storage.py` | The storage check; `LocalStorageProbe`. | settings-storage-setup |
| `container.py` | Read-only container facts. | settings-storage-setup |
| `setup.py` | The wizard's step states. | settings-storage-setup |
| `client/` | Install, status, login, checklist, `LocalClientControl`, `JeepneyMpris`. | client |
| `web/` | `WS /api/events`, the `WS /vnc` bridge, the SPA, and `guard.py`: the Host check on every request and the Origin check on changes (403 `forbidden`). | web |
| `desktop.py` | `LocalDesktop`: X, PulseAudio and VNC for health and `/vnc`. | web |
| `logs.py` | Logging setup. | web |
| `fake/` | The fake world (`world.py`): catalog, player, MPRIS, client, recorder, Web API, image CDN, volumes, and a desktop with a VNC screen. Scenarios `fresh`, `demo` and `wizard`. `seed.py` ties it to the controller's stored token. `demo.py`: the demo scenario completes the wizard at its first start (fresh `.dev`), so Run now works. `recorder.py` is the fake recorder, on Spytify 2.0.2's exact protocol (`recorder/protocol.py`). | fake, S5, S6 |
| `webapi/` | The real Web API port (`client.py`), its token (`tokens.py`), scheduler and usage log (`scheduler.py`, `usage.py`), the allowed endpoints (`endpoints.py`), the stored connection (`auth_store.py`), PKCE (`pkce.py`) and response parsing (`parse.py`). | S5 |
| `catalog/` | The catalog refresh (`refresh.py`), the Library (`library.py`, `links.py`), Albums (`albums.py`), covers (`covers.py`), the shared track-list writer (`tracks.py`). | S5 |
| `connection.py`, `matching.py`, `windows.py`, `backlog.py`, `imagecdn.py` | The Web API connection; Spytify's track key and index; schedule windows; the backlog estimate (its pure part runs on a thread, from S6); the real image CDN port. | S5, S6 |
| `recorder/` | The real recorder port: `protocol.py` (Spytify 2.0.2's protocol, typed), `process.py` (`SpytifyRecorder`, `SpytifySession`), `rpc.py`, `events_file.py`. | S6 |
| `engine/` | The run engine: `states.py` and `types.py` (shared); `item.py`, `item_takes.py` (track results, files, the relayed `track.*`), `item_outcome.py` (the outcome rules), `planning.py`, `steering.py` (one item); `run.py`, `queue.py`, `precheck.py`, `recovery.py` (runs, `services.runs`). | S6 |
| `schedule.py`, `history.py`, `files.py`, `metrics.py` | The scheduler engine (`services.schedule`); History (`services.history`); the `.m3u` and stale files (`services.files`); run metrics (`services.metrics`). | S6 |

## What's left to build

- **S5 is built:** the Web API port, the connection, the catalog refresh, the Library, Albums, covers (thumbnails), matching and the backlog. Tested on the mock Spotify and the fake world only; the real-account check is still to do. Every S5 endpoint answers; nothing in S5 answers 501.
- **S6 is built:** the real recorder port, the item and run engines, the scheduler engine, History, the `.m3u` writer, the stale-file cleanup and the run metrics. Every endpoint answers; none answers 501. Tested on the fakes, the simulator and a stub spytifyd. The real `spytifyd --fake` tests run only when `SPOTIVAULT_TEST_SPYTIFYD` and `SPOTIVAULT_TEST_FFMPEG` name the binaries. On the image's build (spytifyd 2.0.2 with its ffmpeg), 13 pass and `test_umask_reaches_tagged_files` is an expected failure (spytify-bugs.md #7); two of them check that `session.stop {now: false}` in the album-end wait saves the last take and `{now: true}` rejects it. The check on the real client is still to do.
  - **Removing an item or album** from the Library doesn't take it out of the current run's queue yet (`DELETE /api/runs/current/items/{id}` does).
  - **No removal event:** removing an item or album sends no event yet.
  - **Cover files** next to the `.m3u` are deferred (Q14 and Q15).
  - **Contract gaps** (not changed; the contract is the user's to decide): events.md lists `error` codes for only some pre-run failures; `HistoryRow.reason` and the `runs.reason` comment in schema.sql don't list `webapi`, `not_connected` or `setup_incomplete`; openapi.yaml's listRuns has no 422.
  - **A missing binary** has no exit code, so it reads as `killed` and fails the item, not the run. A "can't be run" cause in `recorder/protocol.py` would fix it.
  - **Spytify's own logs** in `/config/logs/spytify/` have no retention rule (web-ui.md Q23).
  - **Tests:** `test_schedule.py` uses stand-ins (`FakeRuns`, `FakeHistory`) for the run engine and History. Using the real ones is open. `test_ws_server.py::test_shutdown_closes_with_1012` failed once under load in one full run (not an S6 file) and passed in the others.
- **Open for the user** (left as built; each is in the spec, see `docs/`):
  - **S6's decisions** (web-ui.md Open questions 17 to 23): the container's stop during a run (Failed or Stopped), items that never started (Stopped or a new badge), a track listed twice, a whole item's time limit, an hour turned on mid-window, episodes the plan jumps over, and Spytify's logs.
  - **Client restart as the fallback** (design.md § Run flow step 6): the spec says it, and nothing does it on a timeout yet.
  - **"Recorded" in the backlog** is a track whose key is in Spytify's index. design.md § Backlog estimate says History's per-track records, keyed by track ID. See the settled answers below.
  - **The finish date** can go past the 21-day window horizon on a slow schedule. The contract allows `finish_at` null only for Manual only, or when nothing is left.
  - **Cover downloads:** each changed cover costs two CDN requests, a thumbnail and a full copy. design.md says "one CDN request per changed cover" and "the UI never loads a full-size file". The contract has `size=full`, and migration 002 has `items.full_path`.
  - **`retry_after_s`:** the code stores any answer's `Retry-After`, 5xx included. `schema.sql`'s comment says "from a 429's". The comment is in migration 001, so it's unchanged.

## Settled and cautious answers

The answers the built code takes. Each one is also in the spec where it matters to a user. A question that's still open is built with the cautious answer, and reported.

- **Q9 and Q10 are settled** in openapi.yaml (S0's answers): `LibraryItem.playback_note` is gone (Liked Songs plays as a context; `items.playback_note` stays NULL); `PlaylistPreview.name` and `owner` are always strings, `total` is null for a linked playlist.
- **The backlog's "recorded"** is the tracks whose key is in Spytify's index. History's files are all in that index, and it's what a run would actually skip, so the estimate matches the runs.
- **A followed playlist you collaborate on** keeps kind `followed` with `item_access` 1 (openapi.yaml `LibraryKind`, and the backlog vectors), where schema.sql's comment says `owned`.
- **`fields`** goes on `GET /playlists/{id}` and `/items`, where Spotify documents it; design.md's "`images(url)` in /me/playlists' fields" isn't sent, since that endpoint has no `fields`, and its answer carries `images` anyway.
- **Linked playlists' `snapshot_id`** is read only by a run's own refresh, so a page-open refresh with nothing changed stays within 3 requests.
- **Untracked playlists** aren't fetched: until tracked, an owned one shows `/me/playlists`' `items.total` (every entry, not just playable ones). Tracking it asks for a refresh.
- **A followed playlist's `total`** is `/me/playlists`' `items.total` (web-ui.md's "32 / 35 recorded"), every entry counted. openapi.yaml's `LibraryItem.total` says so.
- **Disconnected or no Client ID** holds scheduled runs as `not_connected`; `expiring` doesn't hold them.
- **The + modal without a connection** answers 409 `not_connected` or `connection_expired`, like every endpoint; resolve and add also list 503 (`rate_limited`, `spotify_unavailable`).
- **Retries and waits:** a 5xx with Retry-After waits the longer of the two (design.md § Requests). A 429 waits exactly its Retry-After, or 5, 10 and 20 s without one. A Retry-After over 120 s raises RateLimited at once instead of waiting, and a 429 holds every lane, since Spotify's limits are per app. While such a hold lasts, every other call is refused too: new ones, and ones already waiting for their turn (the scheduler's `max_hold_s`). 429s, 5xx, timeouts and network errors share one budget of 3 retries per call, and the resend after a 401 goes on with what's left of it.
- **Expiry:** the state is `expired` from `expires_at`, or once Spotify answers `invalid_grant` (`invalid_grant_at`). The date holds scheduled runs, but only `invalid_grant` refuses a request, before one is sent. A catalog refresh past the date still runs. Any other 400 from the token endpoint, such as `invalid_client`, is a WebApiError with its status.
- **A refresh racing a reconnect:** `AuthStore.save_refreshed` and `mark_invalid_grant` take the refresh token the request used, and write only while it's still stored (one statement). A reconnect in step 5 while a refresh waits to retry is never overwritten or marked expired.
- **PKCE:** `access_denied` is checked before the state. `finish_auth` uses up the pending attempt before the code exchange, so a failed exchange needs Authorize again.
- **Devices:** `GET /api/spotify/devices` applies step 5's device rule, which is what Retry does.
- **Liked Songs** is made once step 5 stores the account (an AuthStore listener in refresh.py), so step 7's `PATCH /api/library/liked` works before the first refresh ends. It starts tracked only while `auto_track_owned` is on, like your own playlists.
- **Library:** "Created by you" includes Liked Songs. Turning `auto_track_owned` off before setup is complete also untracks Liked Songs and the playlists it had tracked on its own (refresh.py's docstring). A link to one of your own playlists that the listing hasn't seen yet previews as kind `linked` with total null, since PlaylistPreview has no `owned`; adding it stores it as owned.
- **Events:** `library.item` and `album.item` are throttled to one per item per second at all times, not only during a run. The album publish's docstring says "during a run"; the code doesn't check for one.
- **Albums:** an album's status puts `unavailable` before `recorded`. The Partial filter also takes unavailable albums that have recorded tracks.
- **Fake mode:** `GET /api/webapi/usage` is always empty there, because the fake Web API writes no usage rows.

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

**Events:** publish only after the change is committed: `services.bus.publish("client.status", model)`. The type must be one of `events.EVENT_TYPES`. The hello's five keys (`setup`, `status`, `connection`, `client`, `backlog`) each have an owning module that replaces its placeholder with `add_snapshot`; `status` is the last one, until S6.

**The Web API:**
- Only the endpoints in `webapi/endpoints.py`, the ones design.md § Web API usage lists. A new one is a spec change first, then a row there. Never Spotify's internal endpoints.
- Use the 2026 field names. Track listings take `market=from_token`, so `is_playable` comes back. The playlist endpoints take `fields`, naming only what's stored.
- Web API errors are the client's exceptions. The client's docstring walks through the request path step by step.

**Secrets:** the access token, refresh token, PKCE verifier and auth code never reach a log line, an event, an API answer, an exception message or the usage log. The usage log holds endpoint templates only, never ids. `logs.redact` is the safety net, not the plan.

**The API:**
- Request and response types come from `api/models.py`. When the contract changes, regenerate the models: never edit them.
- Error codes are the contract's `ErrorCode` values. A wrong one fails in tests, because the envelope is built with the generated model.
- A Web API error a router doesn't catch becomes the matching envelope (`not_connected`, `connection_expired`, `rate_limited`, `spotify_unavailable`). `NoAccess` and `NotFound` are answers, which routers usually handle themselves.

**Ports and modules:**
- Ports are reached at call time: `self.services.ports.webapi` and `.cdn`, never a reference kept from the constructor. Tests swap them.
- Check each port implementation you build or change with `portcheck.assert_implements(cls, protocol)`, in your own test file.
- A feature module registers its hooks in its constructor, as described under How it fits together.

**Code style:** plain, explicit, type-hinted code that the maintainer can edit. Short docstrings on anything that isn't obvious. No metaprogramming. `ruff format` formats everything; lines are 100 characters.

## Tests

- **No outside world:** tests never touch the network, real Spotify, Docker or the running containers. They run on fake ports. `world_of(services.ports)` gives the FakeWorld behind them, to change the world from the outside (`world.player.take_over("Pixel 9")`); `tests/fake_helpers.py` has `make_world`, `recorder_spec` and `Notes`.
- **Fixtures** (`tests/conftest.py`): `config_dir`, `music_dir`, `web_root` (temporary folders), `env`, `config`, `fake_clock`, `services`, `app`, `running_app` (lifespan entered) and `client` (an `httpx.AsyncClient` on the app).
- **Connecting a test's app:** on the fake ports, `await services.auth.set_client_id(...)` and `save_grant(...)` (any token strings) connect it. `world_of(services.ports).webapi` then steers the fake Web API: `failures`, `expired` and `catalog`. The fake CDN is `world.cdn` (`missing`, `failures`, `fetched`).
- **Skipped tests:** only `test_recorder_integration.py`'s, unless `SPOTIVAULT_TEST_SPYTIFYD` and `SPOTIVAULT_TEST_FFMPEG` name a real spytifyd and ffmpeg (the verify stage takes them from the built image).
- **Engine-run tests** swap `services.runs.make_item_engine` for a scripted item engine. A test that leaves a run going makes the app's shutdown wait up to 40 s of real time (the SIGTERM bound) unless it moves the fake clock: end runs before teardown.
- **The blocked-loop guard:** every test's loop runs in asyncio debug mode, and a callback slower than 100 ms fails the test. Build heavy things (apps, parsed files) in sync fixtures, not inside the test's coroutine. A test that blocks on purpose takes `@pytest.mark.allow_slow_callbacks`. After collection, conftest.py freezes what's loaded (`gc.freeze()`), so the garbage collector's full passes stay short under load.
- **S6's simulator:** the `sim` fixture (`tests/engine_sim.py`): a controller set up as after the wizard on the fake world, with an empty library, scripted on the fake clock. See § S6's parts, "The simulator".
- **Spytify's own schema:** `tests/spytify/proto-2.0.2.schema.json` is Spytify 2.0.2's `pkg/proto/schema.json` (MIT licence), unchanged. `tests/test_spytify_protocol.py` validates `recorder/protocol.py` and every payload the fake recorder sends against it, with no extra properties allowed.
- **Helpers:**
  - `spotify_mock.SpotifyMock`: a mock Spotify on httpx.MockTransport, for the real Web API port. The fixtures `spotify_mock` and `mock_webapi` (the real port on it, in place of the fake one), and `connect(services, mock)` to store a working token.
  - **The real port waits on the FakeClock:** catalog calls in a row are 250 ms apart, and retries wait 5 s and more, so a test that never moves the clock hangs. Run such calls with `spotify_mock.run(fake_clock, call)` (or `drive(fake_clock, *calls)`), which moves the clock to each sleeper's deadline. A test that doesn't check the spacing can set `api.scheduler.catalog_spacing_s = 0.0` on the port instead.
  - `asgi_ws.websocket_connect(app, path)`: a WebSocket client on the test's own loop.
  - `contract.assert_schema(name, value)` and `contract.assert_response(response, path)`: check against `openapi.yaml`.
  - `portcheck.assert_implements(cls, protocol)`: a port implementation's signatures match its Protocol. Check every implementation you build or change with it, in your own test file (`tests/test_ports.py` covers the foundation's).
- **The contract test** (`tests/test_contract_routes.py`) checks that every path, method, operationId, parameter and request body in `openapi.yaml` is served, and nothing else is, except the WebSockets and the SPA. It also calls every operation with the contract's examples and checks the answer's status and body against the contract. A built endpoint must answer a status the contract lists for it in the `fresh` scenario. It keeps working as endpoints get built.

## S6's parts

The run engine, the scheduler engine and History are in the module map and the offers table. This section holds what neither says: the state machines, who writes which rows, the events each part publishes, Spytify's protocol as the fake follows it, and the simulator.

The specs win over the code, and the contracts win for shapes: design.md § Run flow, § Container, § Risks; docs/upstream/spytify-bugs.md; web-ui.md § Dashboard, § Schedule, § History, § Player, Settings › Recording, Open questions; contracts/openapi.yaml (`status`, `runs`, `history`, `schedule`), events.md, schema.sql, vectors/schedule-windows.json; prototype/FINDINGS.md and probe.py `cmd_record`; Spytify's source at 2.0.2 for the protocol.

### Hooks and routers

- **Hooks:** each constructor registers its own: `runs.recover` (start-up), `runs` (background), `runs` (shutdown), `schedule` (start-up, after `runs.recover`), `schedule.tick` and `metrics` (background), and the hello's `status` snapshot.
- **The hello's `status`** belongs to engine-run (`RunEngine.status()`); services.py has no placeholder for it.
- **Routers:** `runs.py` (createRun, getCurrentRun, stopCurrentRun, resumeCurrentRun, removeQueuedItem) is included before `history.py` (listRuns, getLastRun, getRun, getRunItemTracks), so `/api/runs/current` is never read as a run id. Each endpoint calls one service method.
- **Shared pieces:** `engine/states.py`, `engine/types.py`, `recorder/protocol.py`, `store/migrations/003_s6_runs.sql` and the simulator (`fake/recorder.py`, `fake/player.py`, `fake/mpris.py`, `tests/engine_sim.py`) are used by several parts. A change to one means running every S6 test file.

### The state machines

engine/states.py holds them as tables, with `check_item_transition` and `check_run_transition` (InvalidTransition on a move the tables don't list). Its docstring has the pictures.

| Item state | Can move to |
|---|---|
| `up_next` | `planning`, `removed`, `stopped` |
| `interrupted` (waiting) | `planning`, `removed`, `stopped`, `carried_over` |
| `planning` | `preflight`, `up_to_date`, `unavailable`, `stopped`, `carried_over`, `failed`, `interrupted` |
| `preflight` | `preparing`, `up_next` (D6), `stopped`, `carried_over`, `failed`, `interrupted` |
| `preparing` | `starting`, `stopped`, `carried_over`, `failed`, `interrupted` |
| `starting` | `playing`, `stopped`, `carried_over`, `failed`, `interrupted` |
| `playing` | `finishing` only: once the recorder ran, its events are drained first |
| `finishing` | `done`, `partial`, `stopped`, `carried_over`, `failed`, `interrupted`, `unavailable` |
| `done`, `up_to_date`, `partial`, `stopped`, `carried_over`, `failed`, `unavailable`, `removed` | nothing (final) |

| Run state (`runs.state`) | Can move to |
|---|---|
| `starting` | `running`, `paused` (D6), `stopping`, `ended` |
| `running` | `finishing`, `paused`, `stopping`, `ended` |
| `finishing` | `running`, `paused`, `stopping`, `ended` |
| `paused` | `running` (Resume), `stopping` |
| `stopping` | `ended` |
| `ended` | nothing; the API shows it as `idle` |

- **Outcomes:** `run_outcome(end, item_states, failed_tracks)`: failed, stopped and window_ended follow how the run ended; a finished queue is `completed_with_issues` when an item ended partial, failed or unavailable, or a track failed.
- **Waiting items when a run ends:** `waiting_item_outcome`: stopped, except an interrupted item at a window's end, which is carried over.
- **Badges:** `item_badges(state, interrupted_count=, carried_over_in=, carried_over_out=)`.

### Events: who publishes what

| Event | Publisher |
|---|---|
| `run.state`, `run.queue`, `item.state`, `run.finished` (runs), `device.moved` | engine-run |
| `error` from the controller at run level: `client_restarted`, `storage` (pre-run), `webapi` (pre-run) | engine-run |
| `track.started`, `track.finished`, `track.skipped`, `session.state`, `level` (`bus.publish_level`, only while recording or stopping) | engine-item |
| `error` relayed from Spytify, and the controller's item-level ones: `recorder_exit`, `recorder_timeout`, `steering_guard`, `loop_guard`, `context_changed`, `webapi`, `storage` (preflight) | engine-item |
| `run.finished` for missed, skipped and held rows | schedule |
| `library.item`, `album.item` (`services.library.publish`, `services.albums.publish`), `backlog` (`services.backlog.update()` after each item) | engine-run |

### The database: who writes what

| Rows | Writer |
|---|---|
| `runs` (kind run), `run_items` (state, queue, counts, timings, reasons), start-up recovery | engine-run |
| `runs` of kind missed, skipped and held; `schedule_hours`; `meta.scheduler_seen_at`; the `run_order` setting | schedule |
| `track_results`, `files`, `observed_tracks`, and on `items`: `last_backup_at`, `completed_at`, `last_full_pass_snapshot`/`_at`, `unavailable_at`/`_reason` | engine-item |
| `items.m3u_path`, `run_metrics` | history-files-metrics |

**Migration 003** (`003_s6_runs.sql`): `run_items.timings` (JSON, `ItemTimings.to_json()`), `run_items.interrupted_by` (stall, takeover, shutdown), `run_items.error_code`, `run_items.skipped_other` (the skip split; `skipped` stays the total), `items.m3u_path`, `run_metrics.loop_lag_max_ms` (design.md § asyncio: the lag goes into the run metrics), and the index `runs_window` on `runs.window_start`.

### Spytify's protocol and the fake recorder

`recorder/protocol.py` types every method result and notification of Spytify 2.0.2, with Go's `omitempty`, the JSON-RPC and Spytify error codes, and `classify_exit(code, log_tail)` → `ExitVerdict(cause, action)` for the plan's exit-code table. The fake recorder builds every payload with it, and `tests/test_spytify_protocol.py` validates them against Spytify's own schema. What the fake does that S4's didn't:
- **Payloads as Spytify sends them:** `log` is `{level, msg, ts}` (levels error, info, debug); `error` is `{code, msg, fatal, …}` with string facts, withdrawn by an empty `msg`; `settings.changed` is `{values}`; `track.skipped` has `path` only for a duplicate; `track.keepable` is `{id, keepable}`; `track.started` carries `cover_url`, `source` and `cut`; `track.finished` carries `tagged`, `timings`, `counter`, and leaves false flags out.
- **Held takes:** a take cut short is `track.skipped incomplete`, then `track.keepable` true; its WAV stays in `.spytify/` at the exit (bug 4), until another track is saved.
- **`capture_stalled`** isn't fatal, and the session carries on, as in 2.0.2: the controller ends the item.
- **`start()`** returns once the --once session started: with no player it waits `wait_target_s`, then raises RecorderStartError (exit 1, `no_player`). Exit 2 and 1 come with spytifyd's log line, which `classify_exit` reads.
- **RPC:** `session.status`, `session.stop` (`{recorded, skipped, stopping}`), `events.recent`, `log.tail`, `core.shutdown`, `player.launch`, `settings.reset`, `player.control restart`; `settings.get` and `settings.set` on Spytify's full settings table, typed, with `rejected`; `core.info` with version `v2.0.2`, the target, and the eight Linux checks.
- **The counter prefix** moves on across items: it's saved in `$SPYTIFY_CONFIG` with a `settings.changed`.
- **Events file:** `{"method", "params"}` per line, as Go's `proto.Event`. The real reader (`recorder/events_file.py`) leaves out `level` records: up to 10 a second, a long item's would fill memory. The item engine parses only the `track.*` ones.
  - **The fake keeps no `level` records** (`levels_sent` counts them), so its `events_file()` and its `--events` file hold the same as the real reader's. Kept, they were written in place at the exit: 0.5 s with the event loop blocked for a 3-hour item in fake mode.

### The simulator (`tests/engine_sim.py`)

The `sim` fixture is a controller after the wizard (client installed, running and logged in; Web API connected; setup complete) on the fake world, with an empty library and the meter off. Every bus event is collected.

| Call | What |
|---|---|
| `sim.elsewhere()`, `sim.album(name, tracks, artist=)`, `sim.playlist(name, entries, tracks=, access=)` | Items in the fake account (FINDINGS' "Elsewhere": 5 tracks by fakename). |
| `await sim.refresh()`, `await sim.add_album(album)`, `await sim.add_playlist(playlist)`, `await sim.track(item_id)` | The catalog refresh; Albums' add; a followed or linked playlist by link; tracking. |
| `sim.prerecord(item, positions)`, `sim.recorded_keys()`, `sim.recorded_titles(item)`, `sim.music_files()` | Spytify's index and the music folder. |
| `sim.leave_player_on(item, index, position_ms)` | The player left paused mid-track by an earlier run (bug 2). |
| `sim.at(s, fn)`, `sim.take_over_at(s, device)`, `sim.stall_at(s, for_s=)`, `sim.capture_at(s, "silent" \| "stalled" \| "ok")`, `sim.autoplay()` | The world changed on the fake clock. |
| `await sim.job(item_id, attempt=, snapshot_unread=, run_id=, timeouts=)` | An `ItemJob`, with its `runs` and `run_items` rows. |
| `await sim.run_item(job, host=, control=, within=)` | Runs `ItemEngine` on the clock; `RecordingHost` records phases and counts. |
| `await sim.advance_until(cond, within=)`, `sim.clock` | Moving time. |
| `sim.events_of(*types)`, `sim.mpris_calls()`, `sim.webapi_calls()`, `sim.recorder_sessions()` | What happened. |
| `sim.world` | The FakeWorld: `player`, `recorder` (knobs: `album_end_race`, `ignore_sigterm`, `lose_final_notifications`, `start_failure`, `hang_methods`, `encode_s`, …), `mpris.metadata_lag_s`, `webapi.failures`, `client`, `storage`. |

The world encodes FINDINGS: a paused track past 300 ms counts as already playing; at the end of an album track 1 loads paused; the phantom `track.started` + `track.skipped` for it at the idle exit; the idle exit 20 s after the pause and the exit 8 s later; SIGTERM, a second SIGTERM, SIGKILL; stalls (`player.pause_by_itself`, `resume_by_itself`); takeovers; autoplay's radio context; MPRIS metadata arriving late.

### Settled and cautious answers (S6 foundation)

Each is the cautious reading where the specs are silent, and each is reported to the user.
- **SIGTERM mid-run:** Stop now; the current item ends `interrupted` (shutdown), and the run ends `failed` with reason `container_restarted`, the same as crash recovery.
- **A takeover counts as an interruption:** the second one in a run ends the item `partial` (design.md counts takeovers and stalls alike). After the first, Resume restarts the item at once with attempt 2.
- **Items left waiting when a run ends** become `stopped`; at a window's end an `interrupted` one is `carried_over`, since it was cut off too. History lists items that never ran after the ones that did.
- **A window with nothing tracked** starts no run and writes no row (History's skipped rows mean "the previous run was paused").
- **A start-up during a window** starts a run unless that window already has a run that didn't end `container_restarted` (a window you stopped by hand isn't restarted).
- **A whole item's time limit:** its last full pass's length, else items.total × 5 min, else 6 h, in the plan's 1.25 × length + 10 min.
- **Recovery's `ended_at`** is the last thing the run did, not the restart time.
- **Missed windows** are written for at most the last 21 days of downtime.
- **History's "Scheduled" filter** includes start-up runs.
- **Spytify's `{year}`-only template** is valid to Spytify; the controller's layout check refuses it before it reaches `--set`.

### Settled and cautious answers (S6 as built)

Where the specs are silent, the cautious reading was taken. Each is reported to the user.

**The recorder** (`recorder/`):
- **Signals:** SIGTERM goes to spytifyd alone, and SIGKILL to its whole group. A SIGTERM to the group would end `parec` and `ffmpeg` under the take it's meant to finish.
- **Its own spytifyd only:** `start()` checks the socket's peer (SO_PEERCRED). A spytifyd left on our socket path is never talked to: ours exits 1 "another spytifyd is listening" (`socket_in_use`), and the item engine retries once after `kill_orphans()`. `kill_orphans()` never touches the controller's own children.
- **Tasks:** the session's task and the connection's reader are owned and awaited by the session, not added through `services.add_background` (the port has no Services). A done-callback logs any failure.
- **Odd starts:** an exit 0 before the session showed returns the ended session (its events file tells what happened). A `.env` in the work dir refuses the start, and the file stays.
- **A dropped socket** (Spytify drops a client 512 lines behind) isn't reconnected: calls raise `RecorderGone`, and the events file recovers the lost events.
- **The events file** is read without its `level` records (see § Spytify's protocol). spytifyd still writes them, so a 24-hour item's file can reach about 150 MB in `/config/logs/spytify/`.
- **A start with no exit code** (a missing binary, a socket that never came) reads as `killed` in `classify_exit`, so it fails the item, not the run. A missing binary should fail the run; that needs a new cause in `protocol.py`.
- **File modes:** Spytify 2.0.2 leaves tagged files at 0600 (spytify-bugs.md #7). After each item, `services.files.fix_modes` gives the files it saved 0666 less UMASK. Folders stay at Spytify's 0755.

**One item** (`engine/item*.py`, `planning.py`, `steering.py`):
- **All planned tracks recorded:** a stop, takeover or stall after that ends the item `done`.
- **Autoplay:** a whole item whose context moved on ends `partial` and is never a clean D13 pass; the radio take it cuts is only skipped. A missing-only item just pauses when its plan is done.
- **The client leaving the session bus** mid-item is a stall: `interrupted`, re-queued once.
- **Errors:** a Web API error fails only the item, unless the connection is gone or expired (then the run). A failed jump sends a non-fatal `webapi` error, pauses, and the item ends `partial`. `classify_exit`'s fail-run verdict gives RunFailure `storage` for `output_dir`, else `recorder`. Spytify's failed `core.info` checks are only logged.
- **Counting:** phantom and repeat takes keep their `track_results` rows and events, with no `track_id` or `position` (so the Library's and Albums' "last result" of a track stays the counted take's), and aren't counted. An unplanned entry the plan jumps over (an episode, say) that Spytify started is counted under `skipped_other` (Spytify's `incomplete`).
- **Rows:** `last_backup_at` is set only for `done`, `up_to_date` and `partial`. `cleanup_stale(folders=[])` (`.spytify/` only) runs before every recorder start, and a stop is looked at again after it. It, `fix_modes` and `write_m3u` log their failures and never fail the item. `write_m3u` runs for up-to-date items too, so a reordered playlist's `.m3u` stays current.
- **D10's checks:** GET /me/player at track starts is spaced at least 5 s apart (a whole item's duplicate replay would otherwise send 2 a second). The 60 s check and the check on a pause are unchanged.
- **Late inputs:** a phantom take is told by Spytify's previous `session.state` (stream order). The context's end is a pause within 1.5 s of the start of the context's first track, by MPRIS's metadata (the item's first playable entry; a whole item's first track heard), checked again when MPRIS's metadata comes late; any other pause is a stall. A first entry that isn't a playable track (an episode) makes the end look like a stall: the item is retried, nothing is lost. GET /me/player's track id is used only when it names an entry with the same title.
- **Stops:** Stop now while finishing is sent as `session.stop {now: false}`: the last take waits for the idle exit, and Spytify's stop now would reject it. When `session.stop` doesn't get through (no answer, an error, or a dropped socket while spytifyd runs), signals stand in; for a stop after the take, the first SIGTERM's wait is at least the take's end + 30 s.
- **The play's 404:** the device list is read. Our device gone fails the run (`device_missing`); otherwise the first play's item is `unavailable` in this run only (no `items.unavailable_at`: the catalog refresh decides), and a jump's tracks stay missing.
- **A planned duplicate** (Spytify skips a planned take as `duplicate` while playing): steering jumps on to the next planned track, or pauses.
- **D13's clean pass** also needs the context heard to its end (`Steering.wrapped`: the end-of-context pause at the first track heard, or that track's phantom at the idle exit), and no counted take skipped `seeked`, `low_quality`, `silent` or `incomplete`. `too_short` and `ad` don't spoil it.
- **The loop guard** pauses on the second repeat in a row whose first-heard number is the previous repeat's + 1 (bug 1's replay); one repeat alone stays (a track listed twice). A guard never sets `wrapped`. **Open** (web-ui.md Q19): a run of two or more tracks listed again in the same order still trips it: that pass ends `partial`, never clean.
- **A whole item's time limit:** `session.stop {now: false}`, so the take playing finishes (design.md), then SIGTERM if spytifyd still runs 30 s after that take's end (web-ui.md Q20).

**The run** (`engine/run.py`, `queue.py`, `precheck.py`, `recovery.py`):
- **Resume** after a takeover or D6 pauses the other device that is playing (`PUT /me/player/pause`), so the item's own D6 check lets it start.
- **Run now** leaves out items with `unavailable_at` set; the run's own refresh clears it once a playlist answers again. Explicit `items` run whatever their tracking or availability. An untracked one with item access plays whole (its stored list wasn't refreshed); an untracked one without is never skipped by D13 (its snapshot_id wasn't read).
- **A stop while `starting`** cancels the pre-run check where it is (the client restart, the device wait, the catalog refresh), so a Stop or SIGTERM doesn't wait for it.
- **createRun while `stopping`** answers 409 `run_active`. The quick 409 checks also apply to items joining a running run.
- **Forced items:** the current item, and items that already ended or were removed in this run, aren't added again (one row per item per run), and are left out of `added`.
- **Attempt 2** gets its own log and events files (`<run>-<item>-2.log`, `.events.jsonl`). Attempt 1's recorded tracks and bytes stay counted; the retry's duplicate skips of them aren't counted again, and its failures replace attempt 1's.
- **A client that isn't running** (not logged out) is left to the device check: one restart through the client port (`ClientManager.restart` refuses during a run), then up to 60 s for the device to be listed.
- **Recovery** also sets takes still recording (`track_results.result` NULL) to failed `interrupted`.
- **A driver crash** ends the run `failed` with reason NULL. An item engine that raises fails that item; the run goes on.
- **D6 between items** sends `device.moved` with `item_id` null, as for D6 at the start.
- **`start_scheduled`** raises RuntimeError if a run is already going.
- **"Expect" on queue rows:** albums "n tracks"; playlists with a track list "n new" (planned once known, else missing at queue time); followed, linked and whole items "checking".
- **Run order** changed mid-run applies from the next item: waiting items are re-ordered, keeping a paused run's item first, forced items next and re-queued items last.
- **Events:** `error` is sent for the pre-run failures events.md lists (`storage`, `webapi`, `client_restarted`); the others (`setup_incomplete`, `setting_drifted`, `client_logged_out`, `connection_expired`, `not_connected`, `device_missing`, `recorder`) are told by `run.finished`'s `reason`.

**The scheduler** (`schedule.py`):
- **Coverage:** a window is decided once it has a `runs` row, or a run covered it: it overlapped the window and ended, didn't fail, and wasn't already stopping when the window opened (kept in memory). A run a restart cut off (`container_restarted`) doesn't decide its window, so a container restart restarts the window; a window stopped by hand isn't restarted.
- **The running window follows the grid:** each tick and each PUT, a scheduled or start-up run ends once now is in no active hour, else its window's end (and `runs.window_end`) becomes the end of the window now is in.
- **Held** reasons: `setup_incomplete`, `connection_expired`, `not_connected`, `client_logged_out` (a client that runs logged out, or isn't installed). A client that isn't running isn't held: the pre-run check restarts it and waits for its device, as for createRun.
- **Closing:** once the `runs` shutdown hook ran, the tick starts no run. Missed, skipped and held rows use trigger `scheduled` and have `ended_at` NULL, so their `duration_s` is null.
- **All 168 hours on** is one window anchored at Monday 00:00 of its week: one scheduled run a week.
- **A PUT** that turns on an hour inside a window already in progress starts a run for that window at the next tick (the literal rule: no row yet, no run going).
- **`run_order`** is written with the same SQL as `settings._write`, in the grid's transaction. A change to the settings' storage must change both.
- **The schedule's "next"** counts playlists to check without unavailable ones; albums queued are the Albums summary's queued plus partial.

**History, files and metrics:**
- **getRunItemTracks** leaves out a take still recording (the contract's `result` has no value for it); the live list comes from the WebSocket.
- **getLastRun's message:** failed takes first, else the item's reason, else a fixed phrase per state.
- **`.m3u`:** paths relative to the `.m3u` (design.md § Run flow step 7). A file the controller didn't write (no item's `m3u_path`) is never replaced or removed: the playlist takes " (<id6>)", then " (<id>)", else gets no `.m3u`. A recorded track that became unplayable stays listed. A whole item's: the last clean pass's order, then what later run items heard.
- **Run metrics:** a value that can't be read is NULL (a missing cache folder is 0 bytes). The first sample of a run has no CPU figure.
