-- Migration 2 (S5: the Web API and the catalog). Never edit it once released: add 003 instead.
--
-- Same conventions as 001_initial.sql (contracts/schema.sql): STRICT tables, RFC 3339 UTC times
-- with milliseconds, booleans as INTEGER 0/1, Spotify ids as base-62 TEXT.
--
-- Q9 and Q10 were settled by S0 (web-ui.md § Open questions): Liked Songs plays as a context, so
-- items.playback_note always stays NULL; a linked playlist's name, owner and cover come from
-- GET /playlists/{id}, so items.name always holds the real name.

-- The followed playlists of the last GET /me/playlists (playlists you follow but didn't create),
-- whether or not they're in the Library. The + modal's suggestions are the ones that aren't, so
-- listing them costs no Web API request (openapi.yaml getLibrarySuggestions). Each catalog refresh
-- replaces the whole table. No image URL is kept: playlist image URLs expire in under a day.
CREATE TABLE followed_playlists (
  id            TEXT PRIMARY KEY CHECK (length(id) = 22 AND id NOT GLOB '*[^0-9A-Za-z]*'),
  uri           TEXT NOT NULL,
  name          TEXT NOT NULL,
  owner_id      TEXT,
  owner_name    TEXT,
  collaborative INTEGER NOT NULL CHECK (collaborative IN (0, 1)),
  total         INTEGER CHECK (total IS NULL OR total >= 0),  -- items.total, which S0 found present
  snapshot_id   TEXT,
  listed_order  INTEGER NOT NULL CHECK (listed_order >= 0),   -- position in /me/playlists
  refresh_id    INTEGER REFERENCES catalog_refreshes (id),
  seen_at       TEXT NOT NULL
) STRICT;

-- The usage-log warnings (design.md § Requests, plan § Web API request scheduler and usage log),
-- as also written to the controller log: every 429, more than `webapi_burst_threshold` requests
-- in 30 s, five or more 4xx in a row from one endpoint, and a refresh or run over twice its 7-day
-- median. GET /api/webapi/usage lists them. Kept 90 days, like api_requests. `message` names
-- endpoint templates only, never ids, URLs or tokens.
CREATE TABLE api_warnings (
  id          INTEGER PRIMARY KEY,
  at          TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('rate_limited', 'burst', 'repeated_4xx', 'above_median')),
  message     TEXT NOT NULL,
  endpoint_id INTEGER REFERENCES api_endpoints (id),           -- NULL for burst and above_median
  scope_kind  TEXT CHECK (scope_kind IS NULL OR scope_kind IN ('refresh', 'run', 'setup', 'other')),
  scope_id    INTEGER
) STRICT;

CREATE INDEX api_warnings_at ON api_warnings (at);

-- The full-size cover cached next to the thumbnail (items.thumb_path), both file names under
-- /config/cache/covers/. GET /api/library/{id}/cover?size=full and the albums' one serve it: the
-- image as the Web API lists it (640 px), since cover files next to the .m3u are deferred (Q14, Q15).
ALTER TABLE items ADD COLUMN full_path TEXT;
