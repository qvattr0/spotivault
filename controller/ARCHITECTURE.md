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
| `services.ports.webapi` | `devices()`, `player_state()`, `play(...)`, `pause(...)`, `seek(...)`, `set_shuffle(...)`, `set_repeat(...)`, each with `scope=ApiScope("run", run_id)` | S6's playback calls. They go on the playback lane, ahead of waiting catalog calls, and count against the run. Errors: `ports.WebApiError` and its subclasses; NotConnected and ConnectionExpired are raised before anything is sent; RateLimited is raised at once while a long hold lasts. |
| `services.catalog` | `await refresh(trigger="run", run_id=...)` → `RefreshResult` | S6, at each run's start (awaited; it waits for a refresh already going). The only refresh that reads linked playlists' `snapshot_id` (D13), before any track list. `RefreshResult.snapshots_unread`: the tracked followed and linked playlists whose `snapshot_id` it couldn't read; S6 plays those whole, whatever `d13_up_to_date()` says (design.md § Run flow step 1). |
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
| `ports.py` | The Protocols, their value types and their errors. | foundation |
| `services.py` | `Services`, `build_services`, the lifecycle, the hello placeholders (only `status` is still one: S6). | foundation |
| `events.py` | The event bus: envelope, seq, hello, bounded queues, `level` throttling. | foundation |
| `errors.py` | `ApiError`, the error envelope and every exception handler. | foundation |
| `store/` | SQLite: one worker thread, an async API, migrations. `001_initial.sql` is `contracts/schema.sql`; `002_s5_catalog.sql` is S5's. | foundation, S5 |
| `loopwatch.py` | The event-loop lag watchdog (over 250 ms: a warning). | foundation |
| `unbuilt.py` | The stand-in for the real recorder (S6) in real mode. | foundation |
| `api/models.py` | Pydantic models generated from `openapi.yaml`. Never edited by hand. | foundation |
| `api/deps.py`, `api/params.py` | `ServicesDep`, and the shared path and query parameters. | foundation |
| `api/routers/*.py` | One router per area. S5 filled those for the Web API, Spotify, library, albums, covers, backlog. S6 fills `status`, `runs` and `schedule`. | S4, S5, S6 |
| `settings.py` | Settings, layout validation, the `--set` mapping, and the settings keys the controller reads itself (`run_order`, `webapi_burst_threshold`). | settings-storage-setup |
| `storage.py` | The storage check; `LocalStorageProbe`. | settings-storage-setup |
| `container.py` | Read-only container facts. | settings-storage-setup |
| `setup.py` | The wizard's step states. | settings-storage-setup |
| `client/` | Install, status, login, checklist, `LocalClientControl`, `JeepneyMpris`. | client |
| `web/` | `WS /api/events`, the `WS /vnc` bridge, the SPA, and `guard.py`: the Host check on every request and the Origin check on changes (403 `forbidden`). | web |
| `desktop.py` | `LocalDesktop`: X, PulseAudio and VNC for health and `/vnc`. | web |
| `logs.py` | Logging setup. | web |
| `fake/` | The fake world (`world.py`): catalog, player, MPRIS, client, recorder, Web API, image CDN, volumes, and a desktop with a VNC screen. Scenarios `fresh`, `demo` and `wizard`. `seed.py` ties it to the controller's stored token. `recorder.py` is the fake recorder. | fake, S5 |
| `webapi/` | The real Web API port (`client.py`), its token (`tokens.py`), scheduler and usage log (`scheduler.py`, `usage.py`), the allowed endpoints (`endpoints.py`), the stored connection (`auth_store.py`), PKCE (`pkce.py`) and response parsing (`parse.py`). | S5 |
| `catalog/` | The catalog refresh (`refresh.py`), the Library (`library.py`, `links.py`), Albums (`albums.py`), covers (`covers.py`), the shared track-list writer (`tracks.py`). | S5 |
| `connection.py`, `matching.py`, `windows.py`, `backlog.py`, `imagecdn.py` | The Web API connection; Spytify's track key and index; schedule windows; the backlog estimate; the real image CDN port. | S5 |

## What's left to build

- **S5 is built:** the Web API port, the connection, the catalog refresh, the Library, Albums, covers (thumbnails), matching and the backlog. Tested on the mock Spotify and the fake world only; the real-account check is still to do. Every S5 endpoint answers; nothing in S5 answers 501.
- **S6:**
  - `api/routers/status.py`, `runs.py` and `schedule.py`, and the real recorder port that replaces `UnbuiltRecorder`. The fake one is `fake/recorder.py`. Until then those endpoints answer 501 with the error envelope.
  - **Removing an item or album** doesn't take it out of the current run's queue yet.
  - **Albums' `unavailable_at`** isn't set yet.
  - **No removal event:** removing an item or album sends no event yet.
  - **Cover files** next to the `.m3u` are deferred (Q14 and Q15).
- **Open for the user** (left as built; each is in the spec, see `docs/`):
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
- **The `needs` marker:** `@pytest.mark.needs("<part>")` skips a test while another part is still a stub. S5 is built, so no test is skipped now. Three S5 tests still carry the marker (`test_catalog_refresh_mock.py`, `test_s5_wiring.py`, `test_spotify_endpoints.py`); it does nothing now, and can go in a cleanup.
- **The blocked-loop guard:** every test's loop runs in asyncio debug mode, and a callback slower than 100 ms fails the test. Build heavy things (apps, parsed files) in sync fixtures, not inside the test's coroutine. A test that blocks on purpose takes `@pytest.mark.allow_slow_callbacks`. After collection, conftest.py freezes what's loaded (`gc.freeze()`), so the garbage collector's full passes stay short under load.
- **Helpers:**
  - `spotify_mock.SpotifyMock`: a mock Spotify on httpx.MockTransport, for the real Web API port. The fixtures `spotify_mock` and `mock_webapi` (the real port on it, in place of the fake one), and `connect(services, mock)` to store a working token.
  - **The real port waits on the FakeClock:** catalog calls in a row are 250 ms apart, and retries wait 5 s and more, so a test that never moves the clock hangs. Run such calls with `spotify_mock.run(fake_clock, call)` (or `drive(fake_clock, *calls)`), which moves the clock to each sleeper's deadline. A test that doesn't check the spacing can set `api.scheduler.catalog_spacing_s = 0.0` on the port instead.
  - `asgi_ws.websocket_connect(app, path)`: a WebSocket client on the test's own loop.
  - `contract.assert_schema(name, value)` and `contract.assert_response(response, path)`: check against `openapi.yaml`.
  - `portcheck.assert_implements(cls, protocol)`: a port implementation's signatures match its Protocol. Check every implementation you build or change with it, in your own test file (`tests/test_ports.py` covers the foundation's).
- **The contract test** (`tests/test_contract_routes.py`) checks that every path, method, operationId, parameter and request body in `openapi.yaml` is served, and nothing else is, except the WebSockets and the SPA. It also calls every operation with the contract's examples and checks the answer's status and body against the contract. A built endpoint must answer a status the contract lists for it in the `fresh` scenario. It keeps working as endpoints get built.
