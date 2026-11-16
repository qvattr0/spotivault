-- Migration 3 (S6: the run engine, the scheduler and run metrics). Never edit it once released:
-- add 004 instead.
--
-- Same conventions as 001_initial.sql (contracts/schema.sql): STRICT tables, RFC 3339 UTC times
-- with milliseconds, booleans as INTEGER 0/1.
--
-- Not a schema change, noted here for the record: the scheduler keeps `scheduler_seen_at` in
-- `meta` (when it last ticked), to find the windows that passed while the container was off
-- ("Missed: spotivault was not running").

-- Where an item's time went (engine/types.py ItemTimings.to_json): seconds per phase, the
-- recorder's start and exit, the first track, the planned length. For S10's long-run analysis and
-- the backlog estimate's per-item allowance.
ALTER TABLE run_items ADD COLUMN timings TEXT CHECK (timings IS NULL OR json_valid(timings));

-- Why the last interruption happened: a stall (paused over 20 s by no other device), a takeover
-- (another device; the run paused), or the controller stopping (SIGTERM).
ALTER TABLE run_items ADD COLUMN interrupted_by TEXT
  CHECK (interrupted_by IS NULL OR interrupted_by IN ('stall', 'takeover', 'shutdown'));

-- The controller's own error code when it stepped in (contracts/events.md `error.code`, source
-- controller): recorder_exit, recorder_timeout, steering_guard, loop_guard, context_changed,
-- webapi, storage, client_restarted.
ALTER TABLE run_items ADD COLUMN error_code TEXT;

-- The skips that weren't duplicates (ads and Spytify's other reasons), so the run's counters
-- (runs.skipped_duplicate, runs.skipped_other) add up from its items. run_items.skipped stays the
-- total.
ALTER TABLE run_items ADD COLUMN skipped_other INTEGER NOT NULL DEFAULT 0
  CHECK (skipped_other >= 0);

-- The .m3u last written for a playlist (or Liked Songs), relative to the music folder
-- ('Playlists/Late Night Drive.m3u'), so a renamed playlist's old file can be removed and two
-- playlists with the same name don't overwrite each other's (design.md § Run flow step 7).
ALTER TABLE items ADD COLUMN m3u_path TEXT;

-- The event loop's worst lag since the previous sample, in ms (loopwatch.take_max; design.md
-- § asyncio: "the lag goes into the run metrics").
ALTER TABLE run_metrics ADD COLUMN loop_lag_max_ms INTEGER
  CHECK (loop_lag_max_ms IS NULL OR loop_lag_max_ms >= 0);

-- The scheduler looks a window's rows up by its start (a run, or a held, skipped or missed row).
CREATE INDEX runs_window ON runs (window_start) WHERE window_start IS NOT NULL;
