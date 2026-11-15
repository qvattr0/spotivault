-- spotivault controller database: /config/db/spotivault.db
--
-- SQLite 3.37+ (STRICT tables). Opened with:
--   PRAGMA journal_mode = WAL;  PRAGMA foreign_keys = ON;  PRAGMA busy_timeout = 5000;
-- The file is mode 0600: it holds the Web API tokens.
--
-- This is migration 1. Later migrations bump meta.schema_version and never edit this file's
-- tables in place. Shapes open questions Q9 and Q10 could still change are marked "Pending S0 (Qn)".
--
-- Conventions:
--   * Times are TEXT, RFC 3339 in UTC with milliseconds: '2026-11-15T00:42:10.512Z'.
--   * Booleans are INTEGER 0/1 with a CHECK.
--   * Spotify ids are TEXT base-62; Liked Songs is the item id 'liked'.
--   * Paths under the music folder are stored relative to it ('fakename/Elsewhere/05 - Last Hours.m4a'),
--     so a different host mapping of /music changes nothing.
--   * Durations are milliseconds (_ms), sizes are bytes (_bytes).

-- ------------------------------------------------------------------------------------------------
-- Setup and account
-- ------------------------------------------------------------------------------------------------

-- Small key/value facts: schema_version, boot history, the setup flags.
-- Keys used in M1: schema_version, tos_acknowledged_at, setup_completed_at, machine_id_checked_at.
CREATE TABLE meta (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL
) STRICT;

INSERT INTO meta (key, value, updated_at) VALUES ('schema_version', '1', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

-- Wizard steps 1 to 9 (GET /api/setup). "Run setup again" sets every step but 'tos' back to 'todo';
-- the steps then turn 'done' again from the live checks, without losing anything.
CREATE TABLE setup_steps (
  step       TEXT PRIMARY KEY CHECK (step IN ('tos', 'client', 'login', 'client_settings', 'webapi',
                                              'output', 'playlists', 'albums', 'done')),
  ordinal    INTEGER NOT NULL UNIQUE CHECK (ordinal BETWEEN 1 AND 9),
  state      TEXT NOT NULL DEFAULT 'todo' CHECK (state IN ('todo', 'active', 'done', 'failed')),
  message    TEXT,
  updated_at TEXT NOT NULL
) STRICT;

INSERT INTO setup_steps (step, ordinal, updated_at) VALUES
  ('tos', 1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  ('client', 2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  ('login', 3, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  ('client_settings', 4, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  ('webapi', 5, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  ('output', 6, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  ('playlists', 7, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  ('albums', 8, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  ('done', 9, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

-- Settings, one row per key, value as JSON. Keys and defaults (GET /api/settings):
--   format 'aac' · bitrate 256 · write_m3u true · save_spotify_covers true · auto_track_owned true
--   layout {"pattern":"{album_artist}/{album}/{track} - {title}","prefix":"none","underscores":false,"strip_accents":false}
--   run_order ["carried_over","liked","playlists","albums"]
--   webapi_burst_threshold 30   (usage-log warning: requests in 30 s)
-- The layout is validated before it's stored (vectors/layouts.json): a stored layout is always valid.
CREATE TABLE settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL CHECK (json_valid(value)),
  updated_at TEXT NOT NULL
) STRICT;

-- The Web API connection. One row (id = 1).
-- expires_at = authorized_at + 6 months, and refreshing never moves it (Spotify, 2026-06-18).
-- A 400 invalid_grant sets invalid_grant_at; the connection is then 'expired' whatever expires_at says,
-- and scheduled runs are held.
CREATE TABLE spotify_auth (
  id               INTEGER PRIMARY KEY CHECK (id = 1),
  client_id        TEXT CHECK (client_id IS NULL OR (length(client_id) = 32 AND client_id NOT GLOB '*[^0-9a-f]*')),
  access_token     TEXT,
  refresh_token    TEXT,
  token_expires_at TEXT,           -- the access token's own ~1 h expiry
  scopes           TEXT CHECK (scopes IS NULL OR json_valid(scopes)),
  user_id          TEXT,
  display_name     TEXT,
  authorized_at    TEXT,
  expires_at       TEXT,
  invalid_grant_at TEXT,
  updated_at       TEXT NOT NULL,
  CHECK ((access_token IS NULL) = (refresh_token IS NULL)),
  CHECK ((authorized_at IS NULL) = (expires_at IS NULL))
) STRICT;

-- A started PKCE authorization. The verifier never leaves the server. Rows older than
-- expires_at (15 minutes) are deleted; POST /api/spotify/auth/start replaces any pending row.
CREATE TABLE pkce_pending (
  state         TEXT PRIMARY KEY,
  code_verifier TEXT NOT NULL,
  client_id     TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL
) STRICT;

-- Spotify client installs into /config/spotify/versions/<version>. One row per attempt.
-- Q13, resolved in S0: the install takes about 18 s, so it's a wizard step with these phases.
CREATE TABLE client_install (
  id               INTEGER PRIMARY KEY,
  started_at       TEXT NOT NULL,
  finished_at      TEXT,
  state            TEXT NOT NULL CHECK (state IN ('installing', 'installed', 'failed')),
  phase            TEXT CHECK (phase IS NULL OR phase IN ('release', 'packages', 'download', 'unpack', 'libraries', 'switch')),
  version          TEXT,
  deb_sha256       TEXT,
  error_code       TEXT CHECK (error_code IS NULL OR error_code IN ('network', 'signature', 'checksum', 'disk_full', 'missing_libraries', 'unknown')),
  error_message    TEXT,
  is_current       INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1)),
  CHECK (state <> 'failed' OR error_code IS NOT NULL)
) STRICT;

-- At most one install is the `current` symlink.
CREATE UNIQUE INDEX client_install_one_current ON client_install (is_current) WHERE is_current = 1;

-- Step 4's checklist: the Confirm ticks, and the last reading of each Auto row.
-- Q3, resolved in S0: crossfade, gapless and autoplay are 'confirm' (stored on Spotify's servers); automix,
-- normalization, equalizer, mono, streaming_quality and auto_adjust_quality are 'auto', read from the prefs file.
CREATE TABLE checklist (
  row_id       TEXT PRIMARY KEY CHECK (row_id IN ('crossfade', 'gapless', 'automix', 'autoplay', 'normalization',
                                                  'equalizer', 'mono', 'streaming_quality', 'auto_adjust_quality', 'volume')),
  check_kind   TEXT NOT NULL CHECK (check_kind IN ('auto', 'confirm', 'set_for_you')),
  state        TEXT CHECK (state IS NULL OR state IN ('ok', 'needs_change', 'unknown')),  -- 'auto' rows only
  confirmed_at TEXT,                                                                      -- 'confirm' rows only
  checked_at   TEXT,
  CHECK (check_kind = 'auto' OR state IS NULL),
  CHECK (check_kind = 'confirm' OR confirmed_at IS NULL)
) STRICT;

-- ------------------------------------------------------------------------------------------------
-- Catalog
-- ------------------------------------------------------------------------------------------------

-- Every Library item and every added album, in one table so runs can reference both.
--   kind 'owned'    your playlist (also a followed playlist you collaborate on: item_access = 1)
--   kind 'liked'    Liked Songs, id 'liked'
--   kind 'followed' a playlist you follow; usually item_access = 0
--   kind 'linked'   a playlist added by link; usually item_access = 0
--   kind 'album'    an album added on the Albums page
-- Status pills are derived on read, never stored, except an album's completed_at, which is a
-- lifecycle fact ("recorded once"): a later failed file doesn't un-complete it.
CREATE TABLE items (
  id                      TEXT PRIMARY KEY CHECK (id = 'liked' OR (length(id) = 22 AND id NOT GLOB '*[^0-9A-Za-z]*')),
  kind                    TEXT NOT NULL CHECK (kind IN ('owned', 'liked', 'followed', 'linked', 'album')),
  uri                     TEXT NOT NULL,
  name                    TEXT NOT NULL,           -- Pending S0 (Q10): a linked playlist whose metadata
                                                   -- can't be read stores its id here until it's known
  owner_id                TEXT,
  owner_name              TEXT,
  artist                  TEXT,                -- albums: the first album artist
  year                    INTEGER,             -- albums: from release_date
  -- Tracking. Albums are always tracked while on the page; playlists follow the toggle.
  tracked                 INTEGER NOT NULL DEFAULT 0 CHECK (tracked IN (0, 1)),
  added_by                TEXT NOT NULL CHECK (added_by IN ('auto', 'user', 'setup')),
  added_at                TEXT NOT NULL,
  saved_at                TEXT,                -- albums: when you saved it in Spotify (modal order)
  removed_at              TEXT,                -- removed from the Library or Albums; kept for History
  -- What the Web API says.
  item_access             INTEGER NOT NULL DEFAULT 1 CHECK (item_access IN (0, 1)),  -- 0: /items is 403
  snapshot_id             TEXT,                -- playlists: refetch items only when this changes
  total                   INTEGER CHECK (total IS NULL OR total >= 0),  -- playable tracks; NULL when unknown
  liked_newest_added_at   TEXT,                -- liked: incremental refresh stops at a track it already has
  catalog_fetched_at      TEXT,
  changed_at              TEXT,                -- last time new tracks appeared ("most recently changed first")
  unavailable_at          TEXT,                -- 404 or 403 on something that worked before; files kept
  unavailable_reason      TEXT CHECK (unavailable_reason IS NULL OR unavailable_reason IN ('deleted', 'private', 'unfollowed', 'not_offered')),
  -- Pending S0 (Q9): set to 'liked_not_playable' if Liked Songs can't be played as a context.
  playback_note           TEXT CHECK (playback_note IS NULL OR playback_note = 'liked_not_playable'),
  -- Covers: no URLs are stored (playlist image URLs expire in under a day).
  image_id                TEXT,                -- the CDN image id; a change means a new cover
  cover_source            TEXT NOT NULL DEFAULT 'none' CHECK (cover_source IN ('custom', 'spotify', 'none')),
  thumb_path              TEXT,                -- under /config/cache/covers/
  -- History shortcuts, updated when a run item ends.
  last_backup_at          TEXT,
  completed_at            TEXT,                -- albums only: every track recorded once
  -- D13: a playlist without item access is "Up to date", and skipped, when snapshot_id equals
  -- last_full_pass_snapshot AND every row of observed_tracks for this item is still in Spytify's
  -- index with its file present. A deleted file forces a full pass. A full pass counts as clean only
  -- when the item ended 'done' with no failed take and no interruption; only then are these two
  -- columns and observed_tracks replaced.
  last_full_pass_snapshot TEXT,
  last_full_pass_at       TEXT,
  CHECK (kind = 'liked' OR id <> 'liked'),
  CHECK (kind <> 'album' OR (artist IS NOT NULL AND total IS NOT NULL)),
  CHECK (kind = 'album' OR completed_at IS NULL),
  CHECK (kind <> 'liked' OR cover_source = 'none'),
  CHECK (playback_note IS NULL OR kind = 'liked'),
  CHECK ((last_full_pass_snapshot IS NULL) = (last_full_pass_at IS NULL))
) STRICT;

CREATE INDEX items_kind ON items (kind) WHERE removed_at IS NULL;
CREATE INDEX items_tracked ON items (tracked, kind) WHERE removed_at IS NULL;

-- Tracks, as the Web API gives them. Everything the controller needs comes with the listings
-- (no batch lookups since February 2026), so it's stored when fetched.
CREATE TABLE tracks (
  id            TEXT PRIMARY KEY CHECK (length(id) = 22 AND id NOT GLOB '*[^0-9A-Za-z]*'),
  uri           TEXT NOT NULL,
  name          TEXT NOT NULL,
  artists       TEXT NOT NULL CHECK (json_valid(artists) AND json_type(artists) = 'array'),
  album_id      TEXT,
  album_name    TEXT,
  track_number  INTEGER,
  disc_number   INTEGER,
  duration_ms   INTEGER NOT NULL CHECK (duration_ms >= 0),
  -- Spytify's duplicate key: go_lower(go_trim(artists[0])) || char(31) || go_lower(go_trim(name)).
  -- Go's strings.ToLower/TrimSpace, not the database's or Python's: see vectors/track-keys.json.
  -- Computed by the controller, never by SQL lower()/trim().
  spytify_key   TEXT NOT NULL,
  fetched_at    TEXT NOT NULL
) STRICT;

CREATE INDEX tracks_spytify_key ON tracks (spytify_key);

-- An item's track list, in Web API order (also the .m3u order). Rebuilt when snapshot_id changes.
-- Entries that can't be recorded stay, so positions match Spotify's offset numbering, but are marked:
-- local files, episodes, entries with no `item`, and is_playable false under market=from_token.
CREATE TABLE item_tracks (
  item_id    TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
  position   INTEGER NOT NULL CHECK (position >= 0),  -- 0-based, as PUT /me/player/play's offset.position
  track_id   TEXT REFERENCES tracks (id),             -- NULL for local files and empty entries
  playable   INTEGER NOT NULL CHECK (playable IN (0, 1)),
  unplayable_reason TEXT CHECK (unplayable_reason IS NULL OR unplayable_reason IN ('local', 'episode', 'no_item', 'not_playable')),
  added_at   TEXT,                                    -- the entry's added_at (Liked Songs: when you liked it)
  PRIMARY KEY (item_id, position),
  CHECK ((playable = 1) = (unplayable_reason IS NULL)),
  CHECK (playable = 0 OR track_id IS NOT NULL)
) STRICT, WITHOUT ROWID;

CREATE INDEX item_tracks_track ON item_tracks (track_id);

-- D13: the tracks seen during the last clean full pass of a playlist without item access.
-- Built from that pass's track.started events (first artist and title, as MPRIS gives them),
-- with the Spotify id when D10's matching found one.
CREATE TABLE observed_tracks (
  item_id     TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
  ordinal     INTEGER NOT NULL CHECK (ordinal >= 1),  -- order of play in that pass
  spytify_key TEXT NOT NULL,
  artist      TEXT NOT NULL,
  title       TEXT NOT NULL,
  track_id    TEXT,
  length_ms   INTEGER,
  run_id      INTEGER NOT NULL REFERENCES runs (id),
  PRIMARY KEY (item_id, ordinal)
) STRICT, WITHOUT ROWID;

CREATE INDEX observed_tracks_key ON observed_tracks (spytify_key);

-- ------------------------------------------------------------------------------------------------
-- What's recorded
-- ------------------------------------------------------------------------------------------------

-- One row per file Spytify wrote for spotivault (from track.finished). Spytify's own index
-- (/music/.spytify/recorded.jsonl) stays the authority on duplicates; this table is History's record,
-- keyed by Spotify track id where the take was matched.
-- A take that doesn't count (low_volume, pause_fade, partial) is stored with counted = 0: the track
-- stays missing, and Spytify's naming gives the file a suffix so it never shadows a real recording.
CREATE TABLE files (
  id           INTEGER PRIMARY KEY,
  track_id     TEXT REFERENCES tracks (id),           -- NULL when the take wasn't matched
  spytify_key  TEXT NOT NULL,
  path         TEXT NOT NULL,                         -- relative to the music folder
  bytes        INTEGER NOT NULL CHECK (bytes >= 0),
  duration_ms  INTEGER NOT NULL CHECK (duration_ms >= 0),
  format       TEXT NOT NULL CHECK (format IN ('aac', 'mp3', 'flac', 'wav')),
  bitrate      INTEGER,
  counted      INTEGER NOT NULL CHECK (counted IN (0, 1)),
  run_id       INTEGER REFERENCES runs (id),
  take_id      TEXT NOT NULL,
  recorded_at  TEXT NOT NULL,
  missing_at   TEXT,                                  -- set when a check finds the file gone
  UNIQUE (run_id, take_id)
) STRICT;

CREATE INDEX files_track ON files (track_id) WHERE counted = 1 AND missing_at IS NULL;
CREATE INDEX files_key ON files (spytify_key) WHERE counted = 1 AND missing_at IS NULL;
CREATE INDEX files_path ON files (path);

-- ------------------------------------------------------------------------------------------------
-- History (kept forever)
-- ------------------------------------------------------------------------------------------------

-- Runs, plus rows for runs that didn't happen (kind 'missed', 'skipped', 'held'), which have no
-- counts. A run that is still going has ended_at NULL; start-up recovery turns such rows into
-- outcome 'failed' with failure_reason 'container_restarted'.
CREATE TABLE runs (
  id                 INTEGER PRIMARY KEY,
  kind               TEXT NOT NULL CHECK (kind IN ('run', 'missed', 'skipped', 'held')),
  trigger            TEXT NOT NULL CHECK (trigger IN ('scheduled', 'run_now', 'startup')),
  state              TEXT CHECK (state IS NULL OR state IN ('starting', 'running', 'paused', 'stopping', 'finishing', 'ended')),
  outcome            TEXT CHECK (outcome IS NULL OR outcome IN ('completed', 'completed_with_issues', 'window_ended', 'stopped', 'failed')),
  reason             TEXT,               -- failed / no-run rows: container_restarted, setting_drifted,
                                         -- client_logged_out, connection_expired, not_running,
                                         -- previous_paused, storage, device_missing, recorder
  paused_reason      TEXT CHECK (paused_reason IS NULL OR paused_reason IN ('device_moved', 'device_busy')),
  stop_mode          TEXT CHECK (stop_mode IS NULL OR stop_mode IN ('after_track', 'now')),
  started_at         TEXT NOT NULL,      -- no-run rows: the window's start
  ended_at           TEXT,
  window_start       TEXT,
  window_end         TEXT,
  -- Counters (NULL on no-run rows). Distinct tracks, not raw events: one run counted 10 skips for a
  -- 5-track album (FINDINGS § End-of-item handling).
  recorded           INTEGER CHECK (recorded >= 0),
  skipped_duplicate  INTEGER CHECK (skipped_duplicate >= 0),
  skipped_other      INTEGER CHECK (skipped_other >= 0),
  failed             INTEGER CHECK (failed >= 0),
  bytes_added        INTEGER CHECK (bytes_added >= 0),
  -- Web API counters for the run's summary line ("Web API: 112 requests · 2 retried · 0 rate-limited").
  api_requests       INTEGER CHECK (api_requests >= 0),
  api_retried        INTEGER CHECK (api_retried >= 0),
  api_rate_limited   INTEGER CHECK (api_rate_limited >= 0),
  CHECK (kind = 'run' OR (state IS NULL AND recorded IS NULL AND outcome IS NULL)),
  CHECK (kind <> 'run' OR state IS NOT NULL),
  CHECK ((state = 'ended') = (outcome IS NOT NULL)),
  CHECK (outcome IS NULL OR ended_at IS NOT NULL)
) STRICT;

CREATE INDEX runs_started ON runs (started_at DESC);
-- At most one run is going at a time.
CREATE UNIQUE INDEX runs_one_active ON runs (kind) WHERE kind = 'run' AND state <> 'ended';

-- An item in a run, in the order it ran. One row per item per run; an interruption bumps attempt
-- instead of adding a row (the second interruption ends it 'partial').
CREATE TABLE run_items (
  id                 INTEGER PRIMARY KEY,
  run_id             INTEGER NOT NULL REFERENCES runs (id),
  item_id            TEXT NOT NULL REFERENCES items (id),
  queue_pos          INTEGER NOT NULL,    -- current queue order; renumbered on re-queue
  ran_order          INTEGER,             -- order it started in, for the run page; NULL if it never ran
  state              TEXT NOT NULL CHECK (state IN ('up_next', 'planning', 'preflight', 'preparing', 'starting',
                                                    'playing', 'finishing', 'interrupted', 'done', 'up_to_date',
                                                    'partial', 'stopped', 'carried_over', 'failed',
                                                    'unavailable', 'removed')),
  attempt            INTEGER NOT NULL DEFAULT 1 CHECK (attempt IN (1, 2)),
  -- D1: 'missing_only' plays just the missing tracks with skip-forward off (albums, owned playlists,
  -- Liked Songs); 'whole' plays the context with skip-forward on and a loop guard (no item access).
  mode               TEXT CHECK (mode IS NULL OR mode IN ('missing_only', 'whole')),
  planned            INTEGER CHECK (planned >= 0),   -- NULL for 'whole'
  up_to_date_by      TEXT CHECK (up_to_date_by IS NULL OR up_to_date_by IN ('nothing_missing', 'd13_unchanged')),
  carried_over_in    INTEGER NOT NULL DEFAULT 0 CHECK (carried_over_in IN (0, 1)),
  carried_over_out   INTEGER NOT NULL DEFAULT 0 CHECK (carried_over_out IN (0, 1)),
  interrupted_count  INTEGER NOT NULL DEFAULT 0 CHECK (interrupted_count BETWEEN 0 AND 2),
  forced             INTEGER NOT NULL DEFAULT 0 CHECK (forced IN (0, 1)),  -- added by Back up now mid-run
  recorded           INTEGER NOT NULL DEFAULT 0 CHECK (recorded >= 0),
  skipped            INTEGER NOT NULL DEFAULT 0 CHECK (skipped >= 0),
  failed             INTEGER NOT NULL DEFAULT 0 CHECK (failed >= 0),
  bytes              INTEGER NOT NULL DEFAULT 0 CHECK (bytes >= 0),
  started_at         TEXT,
  ended_at           TEXT,
  reason             TEXT,
  recorder_exit_code INTEGER,
  log_file           TEXT,                -- /config/logs/spytify/<run>-<item>.log
  events_file        TEXT,                -- /config/logs/spytify/<run>-<item>.events.jsonl
  UNIQUE (run_id, item_id),
  CHECK (state <> 'up_to_date' OR up_to_date_by IS NOT NULL)
) STRICT;

CREATE INDEX run_items_run ON run_items (run_id, queue_pos);
CREATE INDEX run_items_item ON run_items (item_id, run_id);

-- One row per take. track.finished has no title, so it's joined to its track.started by take_id.
CREATE TABLE track_results (
  id           INTEGER PRIMARY KEY,
  run_item_id  INTEGER NOT NULL REFERENCES run_items (id),
  take_id      TEXT NOT NULL,
  track_id     TEXT REFERENCES tracks (id),  -- D10: mpris:trackid first, then GET /me/player
  position     INTEGER,                      -- in the item's track list, when matched
  artist       TEXT NOT NULL,                -- first artist, from track.started
  title        TEXT NOT NULL,
  length_ms    INTEGER,
  planned      INTEGER NOT NULL CHECK (planned IN (0, 1)),
  result       TEXT CHECK (result IS NULL OR result IN ('recorded', 'skipped', 'failed')),  -- NULL while recording
  reason       TEXT CHECK (reason IS NULL OR reason IN (
                 'duplicate', 'ad', 'too_short', 'incomplete', 'seeked', 'low_quality', 'silent',
                 'low_volume', 'recorder_error', 'unavailable', 'interrupted', 'discarded')),
  file_id      INTEGER REFERENCES files (id),
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  UNIQUE (run_item_id, take_id),
  CHECK (result <> 'recorded' OR file_id IS NOT NULL),
  CHECK (result IS NULL OR result = 'recorded' OR reason IS NOT NULL)
) STRICT;

CREATE INDEX track_results_track ON track_results (track_id);
CREATE INDEX track_results_failed ON track_results (run_item_id) WHERE result = 'failed';

-- ------------------------------------------------------------------------------------------------
-- Schedule, catalog refreshes, Web API usage, metrics
-- ------------------------------------------------------------------------------------------------

-- The weekly grid: one row per active hour, local wall-clock time in TZ. No rows = Manual only.
-- Contiguous hours form one window, across midnight and from Sunday (6) to Monday (0).
-- Window rules, DST included: vectors/schedule-windows.json.
CREATE TABLE schedule_hours (
  day  INTEGER NOT NULL CHECK (day BETWEEN 0 AND 6),   -- 0 = Monday … 6 = Sunday
  hour INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
  PRIMARY KEY (day, hour)
) STRICT, WITHOUT ROWID;

-- One row per catalog refresh. At most one every 15 minutes from page opens; never during a run
-- except the run's own refresh at its start.
CREATE TABLE catalog_refreshes (
  id               INTEGER PRIMARY KEY,
  trigger          TEXT NOT NULL CHECK (trigger IN ('run', 'page_open', 'setup', 'item_added')),
  run_id           INTEGER REFERENCES runs (id),
  started_at       TEXT NOT NULL,
  finished_at      TEXT,
  outcome          TEXT CHECK (outcome IS NULL OR outcome IN ('ok', 'partial', 'failed')),
  items_changed    INTEGER CHECK (items_changed >= 0),
  covers_saved     INTEGER CHECK (covers_saved >= 0),
  covers_fallback  INTEGER CHECK (covers_fallback >= 0),  -- "saved at the size returned"
  api_requests     INTEGER CHECK (api_requests >= 0),
  api_retried      INTEGER CHECK (api_retried >= 0),
  api_rate_limited INTEGER CHECK (api_rate_limited >= 0),
  error            TEXT
) STRICT;

CREATE INDEX catalog_refreshes_started ON catalog_refreshes (started_at DESC);

-- The endpoint templates the controller may call (design.md § Web API usage). api_requests can
-- only name these, so an id or a token can never end up in the usage log. A new endpoint is a
-- migration that inserts its template.
CREATE TABLE api_endpoints (
  id       INTEGER PRIMARY KEY,
  method   TEXT NOT NULL CHECK (method IN ('GET', 'PUT', 'POST', 'DELETE')),
  template TEXT NOT NULL CHECK (template GLOB '/*' AND template NOT GLOB '*[?#=&]*'),
  lane     TEXT NOT NULL CHECK (lane IN ('catalog', 'playback', 'auth')),
  UNIQUE (method, template)
) STRICT;

INSERT INTO api_endpoints (method, template, lane) VALUES
  ('POST', '/api/token', 'auth'),                    -- accounts.spotify.com: code exchange and refresh
  ('GET', '/me', 'catalog'),
  ('GET', '/me/playlists', 'catalog'),
  ('GET', '/playlists/{id}', 'catalog'),
  ('GET', '/playlists/{id}/items', 'catalog'),
  ('GET', '/me/tracks', 'catalog'),
  ('GET', '/me/albums', 'catalog'),
  ('GET', '/albums/{id}/tracks', 'catalog'),
  ('GET', '/me/player/devices', 'playback'),
  ('GET', '/me/player', 'playback'),                 -- D10's fallback for track identity
  ('PUT', '/me/player/play', 'playback'),
  ('PUT', '/me/player/pause', 'playback'),
  ('PUT', '/me/player/seek', 'playback'),            -- seek to 0 before the recorder starts
  ('PUT', '/me/player/shuffle', 'playback'),
  ('PUT', '/me/player/repeat', 'playback');

-- The Web API usage log: one row per HTTP attempt, retries included. Kept 90 days.
-- Never stores ids, URLs, query strings, tokens or bodies: only the endpoint template (by id).
-- The rolling 30 s counter and the warnings (429, burst > threshold, 5 x 4xx in a row from one
-- endpoint, a scope over twice its 7-day median) are computed from these rows.
CREATE TABLE api_requests (
  id             INTEGER PRIMARY KEY,
  at             TEXT NOT NULL,                       -- when the request was sent
  endpoint_id    INTEGER NOT NULL REFERENCES api_endpoints (id),
  status         INTEGER,                             -- NULL on a timeout or network error
  error          TEXT CHECK (error IS NULL OR error IN ('timeout', 'network', 'invalid_grant')),
  latency_ms     INTEGER NOT NULL CHECK (latency_ms >= 0),
  attempt        INTEGER NOT NULL CHECK (attempt >= 1),  -- 1, then 2.. for retries of the same call
  retry_after_s  INTEGER CHECK (retry_after_s >= 0),     -- from a 429's Retry-After
  scope_kind     TEXT NOT NULL CHECK (scope_kind IN ('refresh', 'run', 'setup', 'other')),
  scope_id       INTEGER,                                -- catalog_refreshes.id or runs.id
  -- A timeout or network error has no status; invalid_grant is a 400 from the token endpoint.
  CHECK ((status IS NULL) = (coalesce(error, '') IN ('timeout', 'network'))),
  CHECK (coalesce(error, '') <> 'invalid_grant' OR status = 400),
  CHECK (scope_kind IN ('setup', 'other') OR scope_id IS NOT NULL)
) STRICT;

CREATE INDEX api_requests_at ON api_requests (at);
CREATE INDEX api_requests_scope ON api_requests (scope_kind, scope_id);
CREATE INDEX api_requests_429 ON api_requests (at) WHERE status = 429;

-- Run metrics, sampled every 60 s during a run (S10's long-run analysis).
CREATE TABLE run_metrics (
  run_id                INTEGER NOT NULL REFERENCES runs (id),
  at                    TEXT NOT NULL,
  spotify_rss_bytes     INTEGER,   -- every Spotify process, summed
  spotify_cpu_pct       REAL,      -- over the last interval; 100 = one core
  spytifyd_rss_bytes    INTEGER,   -- NULL between items
  spytifyd_cpu_pct      REAL,
  controller_rss_bytes  INTEGER,
  controller_cpu_pct    REAL,
  client_cache_bytes    INTEGER,   -- /config/home/.cache/spotify
  music_free_bytes      INTEGER,
  config_free_bytes     INTEGER,
  webapi_requests_30s   INTEGER,   -- the rolling 30 s counter at sample time
  PRIMARY KEY (run_id, at)
) STRICT, WITHOUT ROWID;
