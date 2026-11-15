# spotivault live events: `WS /api/events`

One WebSocket carries every live update, for every page. This file is its contract. The REST side is [openapi.yaml](openapi.yaml), and schema names below (`RunSummary`, `QueueItem` and so on) point into its `components.schemas`.

**Pending S0:** step S0 answered Q2, Q3, Q9, Q10 and Q13. The client payloads follow the answers. Where Q9 or Q10 would still change a payload, the event says "Pending S0" and takes the cautious answer until S5 builds the Library.

## Connection

- **URL:** `ws://<host>:8080/api/events`. No subprotocol, no auth in M1 (plan D11).
- **Origin:** a browser page from another site is refused before the handshake (HTTP 403). Allowed: no `Origin` header, the same host and port, or both on loopback (`localhost`, `127.0.0.1`, `[::1]`, any port), which covers a Vite dev server proxying to a local controller.
- **Direction:** server to client only. Messages the client sends are ignored, except WebSocket pings.
- **Frames:** one JSON text frame per event.
- **Keep-alive:** the server sends a WebSocket ping every 20 s. A client that hears nothing for 45 s reconnects.
- **Reconnecting:** with backoff, 1 s doubling to 15 s at most. Every new connection starts with a fresh `hello`, so there's no replay and no `since`.
- **Slow clients:** the server keeps up to 256 unsent events per connection. If that fills, it closes the socket with code `1013` ("try again later"), and the client reconnects and gets a new `hello`. The one exception is `level`, which is dropped instead (see [Level throttling](#level-throttling)).
- **Close codes:** `1013` for a slow client, `1011` when the `hello` snapshot fails or a ping goes unanswered, and `1012` when the controller is stopping. The client reconnects on all three. (`WS /vnc` closes with `1013` while there's no screen yet.)

## Envelope

```json
{"seq": 1834, "type": "item.state", "at": "2026-11-15T00:42:10.512Z", "data": {…}}
```

| Field | Type | Meaning |
|---|---|---|
| `seq` | integer or null | Counts up by 1 for each event the controller publishes, from 1 at controller start. Null only for `level`. |
| `type` | string | The event type, from the tables below. |
| `at` | string | When the event happened, RFC 3339 in UTC with milliseconds. |
| `data` | object | The payload. Its shape depends on `type`. |

**Rules for `seq`:**
- **Per controller process.** It restarts at 1 when the controller restarts. `hello.boot_id` tells the client that happened.
- **No gaps on one connection.** Every event goes to every client, so after `hello` the client sees `hello.seq + 1`, `+ 2` and so on. A gap means a bug: the client reloads its state through REST and logs it.
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
| `run.state` | `RunSummary`, plus `previous_state` | The run's state changes, a stop is asked for, the run pauses or resumes, or its counters change. Counter changes are batched: at most one `run.state` per second for counters alone. |
| `run.queue` | `{run_id, queue: [QueueItem]}` | The queue's order or membership changes: items added by Back up now, removed, re-queued after an interruption, or carried over. Always the whole queue. |
| `item.state` | `{run_id, item: QueueItem, previous_state}` | An item moves to another state, including the phases of the current item (`planning` … `finishing`). |
| `run.finished` | `{run: HistoryRow}` | A run ends, or a missed, skipped or held row is written. History refreshes its list. |

**`run.state` when a run ends:** the last one has `state: "idle"`, with the ended run in the other fields, and comes right before `run.finished`.

```json
{"seq": 1835, "type": "run.state", "at": "2026-11-15T01:00:00.020Z", "data": {
  "id": 42, "trigger": "scheduled", "state": "paused", "previous_state": "running",
  "started_at": "2026-11-15T00:00:00Z", "window_end": "2026-11-15T07:00:00+01:00",
  "paused_reason": "device_moved", "stop_mode": null,
  "counters": {"recorded": 12, "skipped_duplicate": 230, "skipped_other": 0, "failed": 1, "bytes_added": 41943040}}}
```

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
| `backlog` | `Backlog` | After each item, and after each catalog refresh that changes it. |

### Spytify, relayed

The controller relays the recorder's events for the current item. It adds `run_id` and `item_id`, renames `id` to `take_id`, and adds what it knows from the Web API. Spytify's own `log`, `track.keepable`, `target.state` and `settings.changed` aren't relayed; they go to the log.

| Type | `data` | Notes |
|---|---|---|
| `track.started` | `{run_id, item_id, take_id, artist, title, album, length_ms, cover_url, track_id, position, planned}` | `artist` is the first artist, as MPRIS gives it. `track_id` and `position` come from matching the take to the item's track list (plan D10: `mpris:trackid` first, then `GET /me/player`); null when it didn't match. `planned` is false for a track the controller is about to jump over. |
| `track.finished` | `{run_id, item_id, take_id, track_id, path, duration_ms, bytes, counted, low_volume, pause_fade, partial}` | Spytify's `track.finished` has no title, so it's matched to `track.started` by `take_id`. `path` is relative to the music folder. `counted` is false for a take that doesn't count as recorded (`low_volume`, `pause_fade` or `partial`); the track stays missing. |
| `track.skipped` | `{run_id, item_id, take_id, reason, path, track_id}` | `reason` is Spytify's: `duplicate`, `too_short`, `ad`, `incomplete`, `seeked`, `low_quality` or `silent`. `path` is set for `duplicate`, relative to the music folder. |
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
| `device.moved` | `{run_id, item_id, device: {id, name, type}, discarded_take_id}` | Playback moved to another device mid-run. The current take is discarded, the item becomes `interrupted`, and the run pauses (`run.state` with `paused_reason: "device_moved"`). Also sent with `item_id` and `discarded_take_id` null when a run starts while another device is playing (D6, `paused_reason: "device_busy"`). |
| `error` | `{source, code, message, fatal, withdrawn, run_id, item_id, facts}` | A red alert. See below. |

**`error` fields:**

| Field | Type | Meaning |
|---|---|---|
| `source` | `spytify` or `controller` | Who raised it. |
| `code` | string | For `spytify`, Spytify's `ErrorCode`: `output_dir`, `disk_full`, `temp_file`, `write`, `ring_overflow`, `capture_stalled`, `capture_silent`, `capture_low_quality`, `player_volume_low`, `read`, `encode`, `rename` or `counter_full`. For `controller`: `recorder_exit`, `recorder_timeout`, `steering_guard`, `loop_guard`, `context_changed`, `webapi`, `storage` or `client_restarted`. |
| `message` | string | English, for the alert and the log. |
| `fatal` | boolean | True when the current item can't continue. It ends `partial`, and the run moves to the next item. |
| `withdrawn` | boolean | Spytify withdraws `capture_silent`, `capture_low_quality` and `player_volume_low` by sending them again with no message. The controller relays that as `withdrawn: true`, and the UI removes the alert. |
| `run_id`, `item_id` | integer, string or null | Set during a run. |
| `facts` | object or null | Spytify's facts (no names or paths), or the controller's. For the log. |

### Library and Albums

| Type | `data` | When |
|---|---|---|
| `library.item` | `LibraryItem` | Its status, counts or `progress` change, or a catalog refresh changes it. During a run, at most one per item per second. |
| `album.item` | `Album` | The same, for an album. |

Pending S0 (Q9): if Liked Songs can't be played as a context, its `library.item` carries `playback_note: "liked_not_playable"`. Pending S0 (Q10): a linked playlist's `name` and `cover` may be null.

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
| Library | `library.item`, `run.state` |
| Albums | `album.item`, `run.state` |
| History | `run.finished` |
| Player | `run.state` (view-only), `client.status` |
| Settings | `client.status`, `connection` |

Every client gets every event; this table is only a guide.
