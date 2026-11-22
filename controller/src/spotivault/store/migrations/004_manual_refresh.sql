-- Migration 4 (the Library's Refresh button). Never edit it once released: add 005 instead.
--
-- Same conventions as 001_initial.sql (contracts/schema.sql): STRICT tables, RFC 3339 UTC times
-- with milliseconds.
--
-- `catalog_refreshes.trigger` gains 'manual': a refresh asked for with the Library's Refresh
-- button (POST /api/library/refresh). SQLite can't change a CHECK in place, so the table is
-- rebuilt with its rows and its index. `followed_playlists.refresh_id` refers to it, and the
-- migration runs with foreign keys on, so those rows are set aside and put back around the
-- rebuild. It all happens in the migration's one transaction.

CREATE TABLE catalog_refreshes_004 (
  id               INTEGER PRIMARY KEY,
  trigger          TEXT NOT NULL
                   CHECK (trigger IN ('run', 'page_open', 'setup', 'item_added', 'manual')),
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

INSERT INTO catalog_refreshes_004 (
  id, trigger, run_id, started_at, finished_at, outcome, items_changed, covers_saved,
  covers_fallback, api_requests, api_retried, api_rate_limited, error
)
SELECT
  id, trigger, run_id, started_at, finished_at, outcome, items_changed, covers_saved,
  covers_fallback, api_requests, api_retried, api_rate_limited, error
FROM catalog_refreshes;

CREATE TEMP TABLE followed_playlists_004 AS SELECT * FROM followed_playlists;
DELETE FROM followed_playlists;

DROP TABLE catalog_refreshes;
ALTER TABLE catalog_refreshes_004 RENAME TO catalog_refreshes;
CREATE INDEX catalog_refreshes_started ON catalog_refreshes (started_at DESC);

INSERT INTO followed_playlists SELECT * FROM followed_playlists_004;
DROP TABLE followed_playlists_004;
