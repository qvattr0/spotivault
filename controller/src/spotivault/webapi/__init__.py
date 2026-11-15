"""The real Spotify Web API port and what it's made of (design.md § Web API usage).

| Module | What |
|---|---|
| `endpoints.py` | The only endpoints spotivault may call, their lanes, URLs, scopes. |
| `auth_store.py` | The `spotify_auth` row: Client ID, tokens, account, expiry. |
| `client.py` | `SpotifyWebApi`, the real `ports.WebApi`. |
| `parse.py` | Web API JSON (2026 names) into the port's value types. |
| `tokens.py` | The access token: refresh before expiry, after a 401, invalid_grant. |
| `scheduler.py` | One request at a time, playback first, catalog 250 ms apart. |
| `usage.py` | The usage log, its warnings and summaries, GET /api/webapi/usage. |
| `pkce.py` | PKCE, the authorize URL, the pasted callback address. |
"""
