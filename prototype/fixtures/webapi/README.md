# Web API fixtures

Real Spotify Web API responses captured in step S0 of the M1 plan (2026-11-15, a Development Mode app, the 2026 field names), for the controller's mocked-API tests.

They were sanitized with [`tests/sanitize_fixtures.py`](../../tests/sanitize_fixtures.py):
- **Kept:** every key, type and the nesting, paging fields, `is_playable`, `is_local`, `duration_ms`, `track_number`, `release_date`, image sizes and hosts.
- **Replaced:** Spotify IDs with stable fakes, so cross-references still match; user IDs and display names; the names of playlists, tracks, albums and artists; descriptions, copyrights and ISRC codes; image and snapshot IDs.

| File | Request | Shows |
| --- | --- | --- |
| `me-playlists-page.json` | `GET /me/playlists?limit=50` | Playlist objects with `items: {href, total}`, `snapshot_id` and `images`; a followed playlist with a total. |
| `playlist-items-page.json` | `GET /playlists/{id}/items?limit=2&market=from_token` | Entries with the track under `item`. |
| `me-tracks-page.json` | `GET /me/tracks?limit=5&market=from_token` | Saved tracks: entries still use `track`. |
| `me-albums-page.json` | `GET /me/albums?limit=2&market=from_token` | Saved albums: `album`, with `album.tracks.items` and `release_date`. |
| `album-tracks-page.json` | `GET /albums/{id}/tracks?limit=2&market=from_token` | Simplified tracks with `is_playable`. |
| `liked-results.json` | `probe liked` | Liked Songs context results (Q9). |
| `offsets-*.json` | `probe offsets` | Offset tests on a playlist with 20 unplayable entries. |
