# spotivault live events: `WS /api/events`

One WebSocket carries every live update, for every page. This file is its contract. The REST side is [openapi.yaml](openapi.yaml), and schema names below (`RunSummary`, `QueueItem` and so on) point into its `components.schemas`.

**S0's answers:** step S0 answered Q2, Q3, Q9, Q10 and Q13, and every payload follows them (Q9 and Q10 settled in S5: see Library and Albums).

## Connection

- **URL:** `ws://<host>:8080/api/events`. No subprotocol, no auth in M1 (plan D11).
- **Origin:** a browser page from another site is refused before the handshake (HTTP 403). Allowed: no `Origin` header, the same host and port, or both on loopback (`localhost`, `127.0.0.1`, `[::1]`, any port), which covers a Vite dev server proxying to a local controller.
- **Direction:** server to client, except the Logs tab's two messages ([Logs](#logs)): `logs.follow` and `logs.unfollow`. Anything else the client sends is ignored, as are WebSocket pings.
- **Frames:** one JSON text frame per event.
- **Keep-alive:** the server sends a WebSocket ping every 20 s. A client that hears nothing for 45 s reconnects.
- **Reconnecting:** with backoff, 1 s doubling to 15 s at most. Every new connection starts with a fresh `hello`, so there's no replay and no `since`.
- **Slow clients:** the server keeps up to 256 unsent events per connection. If that fills, it closes the socket with code `1013` ("try again later"), and the client reconnects and gets a new `hello`. The two exceptions are `level` and `log.lines`, which are dropped or merged instead (see [Level throttling](#level-throttling) and [Logs](#logs)).
- **Close codes:** `1013` for a slow client, `1011` when the `hello` snapshot fails or a ping goes unanswered, and `1012` when the controller is stopping. The client reconnects on all three. (`WS /vnc` closes with `1013` while there's no screen yet.)

## Envelope

```json
{"seq": 1834, "type": "item.state", "at": "2026-11-15T00:42:10.512Z", "data": {…}}
```

| Field | Type | Meaning |
|---|---|---|
| `seq` | integer or null | Counts up by 1 for each event the controller publishes, from 1 at controller start. Null only for `level` and `log.lines`. |
| `type` | string | The event type, from the tables below. |
| `at` | string | When the event happened, RFC 3339 in UTC with milliseconds. |
| `data` | object | The payload. Its shape depends on `type`. |

**Rules for `seq`:**
- **Per controller process.** It restarts at 1 when the controller restarts. `hello.boot_id` tells the client that happened.
- **No gaps on one connection.** Every event goes to every client (`log.lines` only to the ones that follow the logs, and with no `seq`), so after `hello` the client sees `hello.seq + 1`, `+ 2` and so on. A gap means a bug: the client reloads its state through REST and logs it.
- **Ordering against REST:** events are published after the state they describe is committed. So a REST read made after an event already shows that event's change.

**Unknown types** are ignored by the client. New types and new fields are additions; a field is never renamed or removed without a contract change.

## The `hello` snapshot

The first event on every connection. It holds everything the shell needs to draw, so the UI renders without extra requests.

```json
{
  "seq": 1833,
  "type": "hello",
  "at": "2026-11-15T00:42:09.001Z",
  "data": {
    "boot_id": "7f3c9a10-5b2e-4c55-9d0e-2f1a6b7c8d90",
    "version": "0.1.0",
    "setup": {…},
    "status": {…},
    "connection": {…},
    "client": {…},
    "backlog": {…}
  }
}
```

| Field | Schema | Notes |
|---|---|---|
| `boot_id` | string | Changes on every controller start. If it differs from the last `hello`, the client drops cached state. |
| `version` | string | The controller version. |
| `setup` | `Setup` | As `GET /api/setup`. |
| `status` | `Status` | As `GET /api/status`. |
| `connection` | `Connection` | As `GET /api/spotify/connection`. For the expiry banner. |
| `client` | `ClientStatus` | As `GET /api/client/status`. |
| `backlog` | `Backlog` or null | The last estimate, or null before the first one. Reading it never starts a refresh. |

`hello.seq` is the seq of the last event already reflected in the snapshot. The next event has `hello.seq + 1`.

## Events

### Run and queue

| Type | `data` | When |
|---|---|---|
| `run.state` | `RunSummary`, plus `previous_state` | The run's state changes, a stop is asked for, the run pauses or resumes, the window's end moves, or its counters or its time left change. While an item records, those two are batched: at most one `run.state` per second for counters and time left alone. A new time left while no item records (paused, or between items) goes out at once. The time left goes out when it moved by 5 s or more from what the last one shows (its count-down; paused, the figure itself), or its `unknown_items` changed (`RunTimeLeft`), so not every second. |
| `run.queue` | `{run_id, queue: [QueueItem]}` | The queue's order or membership changes: the queue is built after the pre-run check, items are added by Back up now, removed, or re-queued after a stall, or the run order setting changes. Always the whole queue. Items that end with the run (Stopped, Carried over) come as `item.state` instead. |
| `item.state` | `{run_id, item: QueueItem, previous_state}` | An item moves to another state, including the phases of the current item (`planning` … `finishing`). |
| `run.finished` | `{run: HistoryRow}` | A run ends, or a missed, skipped or held row is written. History refreshes its list. |

**`run.state` when a run ends:** the last one has `state: "idle"`, with the ended run in the other fields, and comes right before `run.finished`.

```json
{"seq": 1835, "type": "run.state", "at": "2026-11-15T01:00:00.020Z", "data": {
  "id": 42, "trigger": "scheduled", "state": "paused", "previous_state": "running",
  "started_at": "2026-11-15T00:00:00Z", "window_end": "2026-11-15T07:00:00+01:00",
  "paused_reason": "device_moved", "stop_mode": null,
  "counters": {"recorded": 12, "skipped_duplicate": 230, "skipped_other": 0, "failed": 1, "bytes_added": 41943040},
  "time_left": {"seconds": 1874, "unknown_items": 1, "as_of": "2026-11-15T01:00:00.020Z"}}}
```

**Time left** (`time_left`): this run's own, not the backlog's. Null while the run starts and in the last `run.state`. While the run records, the UI counts it down from `as_of`; while it's paused, as here, it stands still at what the run records once resumed. A scheduled run's is never more than what's left of its window.

```json
{"seq": 1836, "type": "item.state", "at": "2026-11-15T01:00:00.031Z", "data": {
  "run_id": 42, "previous_state": "playing",
  "item": {"item_id": "4glBZ0bZMgkmFyi6TD4h69", "kind": "album", "name": "Elsewhere",
           "cover": "/api/albums/4glBZ0bZMgkmFyi6TD4h69/cover?size=thumb", "state": "interrupted",
           "attempt": 1, "planned": 2, "expect": {"kind": "tracks", "count": 2},
           "counts": {"recorded": 1, "skipped": 0, "failed": 1}, "badges": [], "reason": "Playback moved to Pixel 9."}}}
```

### Backlog

| Type | `data` | When |
|---|---|---|
| `backlog` | `Backlog` | The estimate is worked out again after each run item, each catalog refresh and each album added. It's sent when a figure changed; `as_of` alone doesn't count. |

### Spytify, relayed

The controller relays the recorder's events for the current item. It adds `run_id` and `item_id`, renames `id` to `take_id`, and adds what it knows from the Web API. Spytify's own `log`, `track.keepable`, `target.state` and `settings.changed` aren't relayed; they go to the log.

| Type | `data` | Notes |
|---|---|---|
| `track.started` | `{run_id, item_id, take_id, artist, title, album, length_ms, cover_url, track_id, position, planned}` | `artist` is the first artist, as MPRIS gives it. `track_id` and `position` come from matching the take to the item's track list (plan D10: `mpris:trackid` first, then `GET /me/player`, then the title); null when it didn't match, and for a take that doesn't count, such as the phantom take at the idle exit or a repeat. `position` counts from 1. `planned` is false for a track the controller is about to jump over. |
| `track.finished` | `{run_id, item_id, take_id, track_id, path, duration_ms, bytes, counted, low_volume, pause_fade, partial}` | Spytify's `track.finished` has no title, so it's matched to `track.started` by `take_id`. `path` is relative to the music folder. `counted` is false for a take that doesn't count as recorded (`low_volume`, `pause_fade` or `partial`); the track stays missing. `track_id` is null as in `track.started`. |
| `track.skipped` | `{run_id, item_id, take_id, reason, path, track_id}` | `reason` is Spytify's: `duplicate`, `too_short`, `ad`, `incomplete`, `seeked`, `low_quality` or `silent`. `path` is set for `duplicate`, relative to the music folder. `track_id` is null as in `track.started`. |
| `level` | `{peak_dbfs, rms_dbfs, channels}` | The level meter. `channels` is `[{peak_dbfs, rms_dbfs}]`, left then right. Throttled; see below. No `run_id`. |
| `session.state` | `{run_id, item_id, state}` | `state` is a `SessionState`: `idle`, `waiting`, `recording`, `ad`, `paused` or `stopping`. The pill shows Waiting, Recording, Paused or Stopping. |

```json
{"seq": 1840, "type": "track.started", "at": "2026-11-15T00:42:10.512Z", "data": {
  "run_id": 42, "item_id": "4glBZ0bZMgkmFyi6TD4h69", "take_id": "20261113-060012-002",
  "artist": "fakename", "title": "Last Hours", "album": "Elsewhere", "length_ms": 88421,
  "cover_url": "https://i.scdn.co/image/ab67616d0000b273a5a8fb8d51934d96766181d9",
  "track_id": "0bYg9bo50gSsH3LtXe2SQn", "position": 5, "planned": true}}
```

```json
{"seq": 1851, "type": "track.finished", "at": "2026-11-15T00:43:44.130Z", "data": {
  "run_id": 42, "item_id": "4glBZ0bZMgkmFyi6TD4h69", "take_id": "20261113-060012-002",
  "track_id": "0bYg9bo50gSsH3LtXe2SQn", "path": "fakename/Elsewhere/05 - Last Hours.m4a",
  "duration_ms": 87300, "bytes": 2855116, "counted": true,
  "low_volume": false, "pause_fade": false, "partial": false}}
```

```json
{"seq": null, "type": "level", "at": "2026-11-15T00:42:11.600Z", "data": {
  "peak_dbfs": -3.1, "rms_dbfs": -17.4,
  "channels": [{"peak_dbfs": -3.1, "rms_dbfs": -17.2}, {"peak_dbfs": -3.4, "rms_dbfs": -17.6}]}}
```

#### Level throttling

Spytify sends `level` at most every 100 ms, and only while its session is `recording` or `stopping`. The controller passes it on under these rules:

1. **At most 10 a second:** one `level` per 100 ms. If Spytify sends more, the controller merges them: the highest `peak_dbfs` (overall and per channel) and the latest `rms_dbfs`.
2. **Only while recording:** none outside the `recording` and `stopping` session states. After the last one, the meter falls to silence on its own.
3. **Volatile:** `seq` is null. It isn't stored, isn't in `hello`, and isn't counted in the 256-event buffer.
4. **Latest wins per connection:** if a client hasn't been sent the previous `level` yet, the new one replaces it. A slow client gets fewer meter updates, never a closed socket.

### Warnings

| Type | `data` | When |
|---|---|---|
| `device.moved` | `{run_id, item_id, device: {id, name, type}, discarded_take_id}` | Playback moved to another device mid-run. The current take is discarded, the item becomes `interrupted` (`partial` if it was already interrupted in this run), and the run pauses (`run.state` with `paused_reason: "device_moved"`). `discarded_take_id` is null when no take was recording. Also sent with `item_id` and `discarded_take_id` null when another device is playing as a run starts, or as its next item is about to start (D6, `paused_reason: "device_busy"`). When the controller can't tell which device it is, `device` is `{id: null, name: "another device", type: "Unknown"}`. |
| `error` | `{source, code, message, fatal, withdrawn, run_id, item_id, facts}` | A red alert. See below. |

**`error` fields:**

| Field | Type | Meaning |
|---|---|---|
| `source` | `spytify` or `controller` | Who raised it. |
| `code` | string | For `spytify`, Spytify's `ErrorCode`: `output_dir`, `disk_full`, `temp_file`, `write`, `ring_overflow`, `capture_stalled`, `capture_silent`, `capture_low_quality`, `player_volume_low`, `read`, `encode`, `rename` or `counter_full`. For `controller`: `recorder_exit`, `recorder_timeout`, `steering_guard`, `loop_guard`, `context_changed`, `webapi`, `storage` or `client_restarted`. |
| `message` | string | English, for the alert and the log. |
| `fatal` | boolean | True when the current item can't continue. It ends early, and its `item.state` says how. The run moves to the next item, unless the cause also ends the run (`run.finished` says why). Spytify's `capture_silent` and `capture_stalled` end the item `partial` whatever their `fatal` says (plan D12). |
| `withdrawn` | boolean | Spytify withdraws `capture_silent`, `capture_low_quality` and `player_volume_low` by sending them again with no message. The controller relays that as `withdrawn: true`, and the UI removes the alert. |
| `run_id`, `item_id` | integer, string or null | Set during a run. The pre-run check's errors have `item_id` null and `fatal` false. `storage` and `webapi` come with a failed check, which ends the run. The exception is a `webapi` error while the check waits for our device after a restart: it reads the list again until its 60 s are over. `client_restarted` says the client was restarted because our device wasn't listed, and the run goes on if it shows up. The other pre-run failures send no `error`: `run.finished`'s `reason` tells them. |
| `facts` | object or null | Spytify's facts (no names or paths), or the controller's. For the log. |

### Logs

History's Logs tab follows the logs live. A connection gets `log.lines` only after it asks for them, so the logs aren't read while no Logs tab is open.

**The client's messages** (text frames, JSON):

```json
{"type": "logs.follow", "follow_id": 3, "filter": {"source": ["controller", "spytify"], "level": ["warning", "error"], "run": 42, "q": "timeout"}}
{"type": "logs.unfollow"}
```

| Message | Meaning |
|---|---|
| `logs.follow` | Start following, or change the filter. `filter`'s fields are `GET /api/logs`'s parameters, and each may be left out or null: `source` and `level` are lists (left out: every source, and every level but `debug`), `run` a run id, `q` a search. `follow_id` (an integer, or a string of up to 64 characters; optional) comes back in each `log.lines`, so the client can drop a batch that was on its way under the filter before. A message that doesn't fit this is ignored. |
| `logs.unfollow` | Stop. Closing the socket stops it too. |

The follow lasts as long as the connection: after a reconnect, send `logs.follow` again, after the `hello`.

**The event:**

| Type | `data` | When |
|---|---|---|
| `log.lines` | `{lines: [LogLine], dropped, follow_id}` | New lines that match the connection's filter, oldest first, at most twice a second. `dropped` counts the matching lines left out of this batch (see below). `follow_id` is the one `logs.follow` gave, or null. |

```json
{"seq": null, "type": "log.lines", "at": "2026-11-15T01:05:02.400Z", "data": {
  "lines": [{"id": "1794704702310000000-0-controller", "at": "2026-11-15T01:05:02.310Z", "source": "controller",
             "service": "controller", "level": "warning", "message": "runs: playback moved to Pixel 9", "run_id": null}],
  "dropped": 0, "follow_id": 3}}
```

**Rules:**
1. **Batched:** the controller looks for new lines every 0.5 s, and sends each following connection one `log.lines` with the ones its filter matches. Nothing is sent when nothing matched.
2. **The first batch** comes at once after `logs.follow`: the matching lines of the last 10 s. A page read through `GET /api/logs` and the follow can cross, so a line can come both ways: the client drops it by `id`.
3. **Capped:** at most 200 lines per event, the newest. Older ones in the batch are counted in `dropped`. So are lines the controller skipped because a log grew too fast to read in one go (an estimate, from their size), so a batch can hold no lines and only a `dropped` count. They're still in the files: `GET /api/logs` reads them.
4. **Volatile:** `seq` is null. It isn't stored, isn't in `hello`, and isn't counted in the 256-event buffer.
5. **Merged per connection:** if a client hasn't been sent the previous `log.lines` yet, the new lines join it, under the same 200-line cap. A slow client gets a `dropped` count, never a closed socket. A batch for an earlier `follow_id` that hasn't gone out is dropped.
6. **Masked:** as in `GET /api/logs`.
7. **Debug lines** go out only to a filter whose `level` asks for `debug`.
8. **A run's filter:** the controller's, the client's and the system's lines pass while that run goes on (and 5 s after it ends); Spytify's lines pass when they're from one of the run's item logs.

### Library and Albums

| Type | `data` | When |
|---|---|---|
| `library.item` | `LibraryItem` | Its status, counts or `progress` change, or a catalog refresh changes it. At most one per item per second, during a run or not: changes within the second are merged into one sent at its end. |
| `album.item` | `Album` | The same, for an album. |

**Removing an item or album** from the Library sends no event in M1.

**Settled in S5:** Q9, Liked Songs plays as a context, so `LibraryItem` has no playback note. Q10, a linked playlist's name, owner and cover come from `GET /playlists/{id}`, so its `name` is always known; its `cover` is null only while no thumbnail is cached, like any other item's.

### Catalog refresh

| Type | `data` | When |
|---|---|---|
| `catalog.refresh` | `{refresh_id, trigger, state, outcome, items_changed, items_added, suggestions_added, reason}` | A catalog refresh starts or ends. The Library's Refresh button (`POST /api/library/refresh`) waits for its `ended`. |

**`catalog.refresh` fields:**

| Field | Type | Meaning |
|---|---|---|
| `refresh_id` | integer or null | The refresh. Null for one that was asked for but didn't run. |
| `trigger` | string | Why it ran: `run` (a run's start), `page_open` (a read of `GET /api/backlog`, at most once every 15 minutes), `setup`, `item_added` (an item was tracked or added), or `manual` (the Refresh button). |
| `state` | `started` or `ended` | |
| `outcome` | string or null | Null while `started`. Then `ok`; `partial` when some track lists couldn't be read; `failed` when the playlist listing couldn't be read; `skipped` when it didn't run, because a run was going when its turn came or the Web API wasn't connected. |
| `items_changed` | integer or null | Library items it changed, new ones included. Null while `started`. |
| `items_added` | integer or null | New Library items: playlists you created since the last refresh. Null while `started`. |
| `suggestions_added` | integer or null | Playlists you follow that the last listing didn't have, and that aren't in the Library: new suggestions in the + modal. Null while `started`. |
| `reason` | string or null | Why it was `failed` or `skipped`, as an `ErrorCode` (openapi.yaml); null otherwise. See below. |

**`reason` values:**

| Value | Outcome | When |
|---|---|---|
| `run_active` | `skipped` | A run was going when its turn came. |
| `not_connected` | `skipped` or `failed` | No Client ID or no token. |
| `connection_expired` | `skipped` or `failed` | Spotify answered `invalid_grant`, before or during this refresh. Reconnect; waiting won't help. |
| `rate_limited` | `failed` | Spotify kept asking to wait while the playlist listing was read. |
| `spotify_unavailable` | `failed` | Spotify didn't answer the listing after the retries, or answered with another error. |
| `internal` | `failed` | An error in the controller. |

- **Order:** `started` comes once the refresh begins. `ended` comes after the `library.item` events of the items it changed, and after its `backlog` event. An item sent less than a second earlier gets its `library.item` after `ended`, merged by the once-a-second limit.
- **A refresh that doesn't run** sends only `ended`, with `refresh_id` null and outcome `skipped`. A page open's refresh that the 15-minute limit drops sends nothing.

```json
{"seq": 2210, "type": "catalog.refresh", "at": "2026-11-15T09:30:02.418Z", "data": {
  "refresh_id": 57, "trigger": "manual", "state": "ended", "outcome": "ok",
  "items_changed": 2, "items_added": 1, "suggestions_added": 0, "reason": null}}
```

### Setup, client and connection

| Type | `data` | When |
|---|---|---|
| `setup.state` | `Setup` | A step changes state. |
| `client.install` | `ClientInstall`, plus `log_line` | Install progress: each phase change, each new log line, and download progress at most twice a second. `log_line` is the new line, or null. |
| `client.status` | `ClientStatus` | Any field changes, except install progress (`client.install` carries that) and the window title alone (it changes with every track): the client is installed, starts or stops, logs in or out, an install starts or ends, or a run starts or ends (`restartable`). |
| `connection` | `Connection` | The Web API connection changes: connected, disconnected, `expiring` (4 weeks before), `expired`, or `invalid_grant`. The banner follows it. |

**Settled in S0:**
- **Q13** (client install timing): the install takes about 18 s, so `client.install` follows it as a wizard step.
- **Q2** (login detection): `client.status.logged_in` is true when a `Users/*-user/` folder exists and the client's window has a title other than plain "Spotify". MPRIS isn't a signal. `login_signals` carries all three readings.
- **Q3** (reading client settings): there's no checklist event. The UI re-reads `GET /api/client/checklist`, which also serves Re-check.

```json
{"seq": 12, "type": "client.install", "at": "2026-11-15T09:13:40.250Z", "data": {
  "state": "installing", "phase": "download", "progress": 0.41,
  "bytes_done": 73400320, "bytes_total": 179306496, "version": "1.3.4.258", "previous_version": null,
  "error": null, "log_tail": ["InRelease signature OK", "Packages sha256 OK"],
  "started_at": "2026-11-15T09:13:02Z", "finished_at": null, "log_line": null}}
```

## Which pages listen to what

| Page | Events |
|---|---|
| Shell (sidebar, bottom bar, banner) | `hello`, `run.state`, `item.state`, `track.started`, `session.state`, `connection`, `setup.state` |
| Setup wizard | `setup.state`, `client.install`, `client.status`, `connection`, `backlog` |
| Dashboard | `run.state`, `run.queue`, `item.state`, `run.finished`, `backlog`, `track.*`, `level`, `session.state`, `device.moved`, `error` |
| Library | `library.item`, `run.state`, `catalog.refresh` |
| Albums | `album.item`, `run.state` |
| History | `run.finished`; the Logs tab, `log.lines` |
| Player | `run.state` (view-only), `client.status` |
| Settings | `client.status`, `connection` |

Every client gets every event, except `log.lines`; this table is only a guide.
