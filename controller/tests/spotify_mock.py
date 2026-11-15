"""A mock Spotify for tests: the Web API and the accounts service on httpx.MockTransport.

It answers the allowed endpoints (webapi/endpoints.py) as Spotify does under the 2026 Development
Mode rules, from the fake catalog (fake/catalog.py: the sanitized S0 captures, filled out to
their real totals), and nothing else: any other host, path or method raises UnexpectedRequest.
No network, no real token.

    mock = SpotifyMock(clock=fake_clock)                 # the fixtures library
    api = use_mock(services, mock)                       # the real port, on the mock
    await connect(services, mock)                        # a stored token, as step 5 leaves it
    mock.fail("GET /me/tracks", status=429, retry_after_s=3)
    mock.fail("GET /me/playlists", status=503, times=2)
    mock.timeout("GET /me/player/devices")
    mock.expire_access_tokens()                          # next call: 401, then a refresh works
    mock.revoke_refresh_tokens()                         # next refresh: 400 invalid_grant
    ...
    assert mock.count("GET /me/playlists") == 1
    assert mock.requests[-1].params["market"] == "from_token"
    assert mock.unexpected == []

**The real port waits on the FakeClock:** catalog calls in a row are spaced 250 ms apart, and
retries wait 5 s and more. A test that never moves the clock hangs, so run such calls with
`run(fake_clock, call)` (or `drive(fake_clock, *calls)` for several at once), which move the
clock to each sleeper's deadline. A test that doesn't check the spacing can also set
`api.scheduler.catalog_spacing_s = 0.0` on the port `use_mock` returns.

**What it does like Spotify** (design.md § Web API usage, prototype/FINDINGS.md S0 rows):
- **Tokens:** every api.spotify.com call needs `Authorization: Bearer <a valid access token>`,
  else 401. POST accounts.spotify.com/api/token (form-encoded only) exchanges a code from
  `authorize()` (PKCE: the verifier must hash to the challenge; codes are single use) and
  refreshes. A refresh hands out a new refresh token and retires the old one
  (`rotate_refresh_tokens`), so a client that doesn't store it fails its next refresh. Tokens look
  like Spotify's (`BQ…` access, `AQ…` refresh and codes), so `logs.redact` patterns apply.
- **Paging:** `offset` and `limit` (1–50, else 400; 20 when absent), `total`, `next`.
- **`market`:** `is_playable` is in track objects only when the request has a `market`.
- **`fields`:** applied on GET /playlists/{id} and /items, as Spotify does (nested `a(b,c)` and
  `a.b`), so a client that leaves a field out of its list doesn't get it.
- **2026 names:** a playlist's contents under `items`, a playlist entry's track under `item`;
  /me/tracks entries keep `track`, /me/albums entries keep `album` with `album.tracks`.
- **Access:** owned and collaborative playlists list their items; followed and linked ones answer
  403 on /items, and GET /playlists/{id} gives them no `items` (rows 20, 29); a Spotify-made or
  unknown playlist is 404 on both (row 28); /me/playlists gives a followed one's `items.total`.
- **Episodes** come as track objects with `episode: true` (no `additional_types`), local files
  with `is_local: true` and no id, an empty entry with `item: null`.
- **Devices:** ours (named `device_name`) while `our_device_listed`, and the catalog's others.
  PUT /me/player/play with a device_id that isn't listed is 404.

**Scripted failures** (`fail`, `timeout`, `network_error`) are taken first-in, first-out by the
first matching request, before anything else, the token endpoint included. A 429 carries
`Retry-After`; a 5xx can too.

**The request log:** `requests` has every request, in order (`MockRequest`: endpoint name, path,
query, form, JSON body, Authorization header, status, clock time); `unexpected` the refused ones.

"""

import asyncio
import base64
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode

import httpx

from spotivault.fake.catalog import (
    SPOTIFY_MADE_PREFIX,
    Catalog,
    CatalogAlbum,
    CatalogPlaylist,
    Entry,
    device_id,
)
from spotivault.fake.clock import FakeClock
from spotivault.ports import Clock, Image, TokenGrant, Track
from spotivault.services import Services
from spotivault.webapi.client import SpotifyWebApi
from spotivault.webapi.endpoints import (
    ALBUM_TRACKS,
    API_BASE,
    BY_NAME,
    DEVICES,
    ME,
    MY_PLAYLISTS,
    PAUSE,
    PLAY,
    PLAYER,
    PLAYLIST,
    PLAYLIST_ITEMS,
    REDIRECT_URI,
    REPEAT,
    SAVED_ALBUMS,
    SAVED_TRACKS,
    SCOPES,
    SEEK,
    SHUFFLE,
    TOKEN,
    Endpoint,
    endpoint_for,
)

MOCK_CLIENT_ID = "5f0e1d2c3b4a59687766554433221100"
DEFAULT_LIMIT = 20  # Spotify's, when a listing is asked without `limit`
MAX_LIMIT = 50
ITEMS_IN_PLAYLIST_OBJECT = 100  # GET /playlists/{id} without `fields` embeds this many entries


class UnexpectedRequest(AssertionError):
    """A request to anything but the allowed endpoints. It's raised out of the HTTP call, so a
    test can't miss it, and also kept in `SpotifyMock.unexpected`."""


@dataclass(slots=True)
class MockRequest:
    """One request the mock saw. `form` and `authorization` hold secrets: tests only."""

    method: str
    endpoint: str | None  # "GET /playlists/{id}/items"; None when it wasn't an allowed endpoint
    url: str
    path: str
    params: dict[str, str]
    form: dict[str, str]
    json: Any
    authorization: str | None
    at: float | None  # clock.monotonic() when it arrived, if the mock has a clock
    status: int | None = None  # None: a scripted timeout or network error, or refused


@dataclass(slots=True)
class Failure:
    """A scripted failure for the next request(s) to `endpoint` (None: any endpoint)."""

    endpoint: str | None
    status: int | None = None  # the answer's status; None with `error`
    retry_after_s: int | None = None
    error: type[httpx.TransportError] | None = None  # httpx.ReadTimeout, httpx.ConnectError
    body: Any = None
    times: int = 1


@dataclass(slots=True)
class _Code:
    client_id: str
    challenge: str
    redirect_uri: str
    scopes: tuple[str, ...]


class SpotifyMock:
    """See the module docstring."""

    def __init__(
        self,
        *,
        catalog: Catalog | None = None,
        library: Literal["fixtures", "empty"] = "fixtures",
        device_name: str = "spotivault-test",
        client_id: str = MOCK_CLIENT_ID,
        clock: Clock | None = None,
    ) -> None:
        self.catalog = (
            catalog if catalog is not None else Catalog(device_name=device_name, library=library)
        )
        self.device_name = device_name
        self.client_id = client_id
        self.clock = clock
        self.our_device_listed = True
        self.active_device_id: str | None = None
        self.player_state: dict[str, Any] | None = None  # GET /me/player's JSON; None: 204
        self.access_token_ttl_s = 3600
        self.rotate_refresh_tokens = True
        self.requests: list[MockRequest] = []
        self.unexpected: list[MockRequest] = []
        self.failures: list[Failure] = []
        self.access_tokens: set[str] = set()
        self.refresh_tokens: set[str] = set()
        self.codes: dict[str, _Code] = {}
        self._serial = 0

    # --- Wiring ------------------------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        """The transport to build the real port (or any httpx.AsyncClient) on."""
        return httpx.MockTransport(self._handle)

    # --- Tokens ------------------------------------------------------------------------------

    def authorize(
        self,
        *,
        code_challenge: str,
        client_id: str | None = None,
        redirect_uri: str = REDIRECT_URI,
        scopes: tuple[str, ...] = SCOPES,
    ) -> str:
        """You approving on Spotify's consent page: returns the code the browser's callback
        address carries. It works once, for this client id, redirect URI and PKCE challenge."""
        code = self._token("AQ", "code")
        self.codes[code] = _Code(client_id or self.client_id, code_challenge, redirect_uri, scopes)
        return code

    def issue_tokens(self) -> tuple[str, str]:
        """A working (access token, refresh token) pair, as a finished authorization gives."""
        access = self._token("BQ", "access")
        refresh = self._token("AQ", "refresh")
        self.access_tokens.add(access)
        self.refresh_tokens.add(refresh)
        return access, refresh

    def expire_access_tokens(self) -> None:
        """Every access token handed out so far answers 401 from now on; refreshing works."""
        self.access_tokens.clear()

    def revoke_refresh_tokens(self) -> None:
        """The 6-month authorization is over: every refresh answers 400 invalid_grant."""
        self.refresh_tokens.clear()

    # --- Scripted failures ---------------------------------------------------------------------

    def fail(
        self,
        endpoint: str | None,
        *,
        status: int,
        retry_after_s: int | None = None,
        times: int = 1,
        body: Any = None,
    ) -> None:
        """The next `times` requests to `endpoint` ("GET /me/playlists", "POST /api/token"; None
        for any) answer `status`, with Retry-After when given, and Spotify's error body."""
        self._check_name(endpoint)
        self.failures.append(Failure(endpoint, status, retry_after_s, None, body, times))

    def timeout(self, endpoint: str | None, *, times: int = 1) -> None:
        """The next `times` requests to `endpoint` time out (httpx.ReadTimeout)."""
        self._check_name(endpoint)
        self.failures.append(Failure(endpoint, error=httpx.ReadTimeout, times=times))

    def network_error(self, endpoint: str | None, *, times: int = 1) -> None:
        """The next `times` requests to `endpoint` can't connect (httpx.ConnectError)."""
        self._check_name(endpoint)
        self.failures.append(Failure(endpoint, error=httpx.ConnectError, times=times))

    # --- The log -------------------------------------------------------------------------------

    def count(self, endpoint: str | None = None) -> int:
        """Requests to `endpoint` ("GET /me/tracks"), or every request when None."""
        return sum(1 for r in self.requests if endpoint is None or r.endpoint == endpoint)

    def endpoints(self) -> list[str | None]:
        """The endpoint of every request, in order."""
        return [r.endpoint for r in self.requests]

    def clear_log(self) -> None:
        self.requests.clear()
        self.unexpected.clear()

    # --- Handling one request -----------------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        endpoint = endpoint_for(request.method, str(request.url))
        record = self._record(request, endpoint)
        if endpoint is None:
            self.unexpected.append(record)
            raise UnexpectedRequest(
                f"{request.method} {request.url.host}{request.url.path} is not an allowed "
                "endpoint (webapi/endpoints.py)"
            )
        failure = self._take_failure(endpoint.name)
        if failure is not None:
            if failure.error is not None:
                raise failure.error(f"mock {failure.error.__name__}", request=request)
            assert failure.status is not None
            response = _error(failure.status, failure.body, failure.retry_after_s, endpoint)
        elif endpoint is TOKEN:
            response = self._token_endpoint(request, record)
        elif not self._authorized(request):
            response = _api_error(401, "The access token expired")
        else:
            response = self._route(endpoint, request, record)
        record.status = response.status_code
        return response

    def _record(self, request: httpx.Request, endpoint: Endpoint | None) -> MockRequest:
        form: dict[str, str] = {}
        body: Any = None
        content = request.content
        content_type = request.headers.get("content-type", "")
        if content and content_type.startswith("application/x-www-form-urlencoded"):
            form = {k: v[-1] for k, v in parse_qs(content.decode(), keep_blank_values=True).items()}
        elif content:
            try:
                body = json.loads(content)
            except ValueError:
                body = content.decode(errors="replace")
        record = MockRequest(
            method=request.method,
            endpoint=endpoint.name if endpoint else None,
            url=str(request.url),
            path=request.url.path,
            params=dict(request.url.params),
            form=form,
            json=body,
            authorization=request.headers.get("authorization"),
            at=self.clock.monotonic() if self.clock is not None else None,
        )
        self.requests.append(record)
        return record

    def _take_failure(self, name: str) -> Failure | None:
        for failure in self.failures:
            if failure.endpoint is None or failure.endpoint == name:
                failure.times -= 1
                if failure.times <= 0:
                    self.failures.remove(failure)
                return failure
        return None

    def _authorized(self, request: httpx.Request) -> bool:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        return scheme == "Bearer" and token in self.access_tokens

    # --- accounts.spotify.com/api/token ---------------------------------------------------------

    def _token_endpoint(self, request: httpx.Request, record: MockRequest) -> httpx.Response:
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("application/x-www-form-urlencoded"):
            return _oauth_error(400, "invalid_request", "Only form-encoded bodies are accepted")
        form = record.form
        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            return self._exchange(form)
        if grant_type == "refresh_token":
            return self._refresh(form)
        return _oauth_error(400, "unsupported_grant_type", "grant_type must be supported")

    def _exchange(self, form: dict[str, str]) -> httpx.Response:
        code = self.codes.pop(form.get("code", ""), None)
        if code is None:
            return _oauth_error(400, "invalid_grant", "Invalid authorization code")
        if form.get("client_id") != code.client_id:
            return _oauth_error(400, "invalid_client", "Invalid client")
        if form.get("redirect_uri") != code.redirect_uri:
            return _oauth_error(400, "invalid_grant", "Invalid redirect URI")
        if _challenge(form.get("code_verifier", "")) != code.challenge:
            return _oauth_error(400, "invalid_grant", "code_verifier was incorrect")
        access, refresh = self.issue_tokens()
        return httpx.Response(
            200,
            json={
                "access_token": access,
                "token_type": "Bearer",
                "scope": " ".join(code.scopes),
                "expires_in": self.access_token_ttl_s,
                "refresh_token": refresh,
            },
        )

    def _refresh(self, form: dict[str, str]) -> httpx.Response:
        token = form.get("refresh_token", "")
        if form.get("client_id") != self.client_id:
            return _oauth_error(400, "invalid_client", "Invalid client")
        if token not in self.refresh_tokens:
            return _oauth_error(400, "invalid_grant", "Refresh token revoked")
        access = self._token("BQ", "access")
        self.access_tokens.add(access)
        body: dict[str, Any] = {
            "access_token": access,
            "token_type": "Bearer",
            "scope": " ".join(SCOPES),
            "expires_in": self.access_token_ttl_s,
        }
        if self.rotate_refresh_tokens:
            self.refresh_tokens.discard(token)
            new_refresh = self._token("AQ", "refresh")
            self.refresh_tokens.add(new_refresh)
            body["refresh_token"] = new_refresh
        return httpx.Response(200, json=body)

    # --- api.spotify.com ---------------------------------------------------------------------

    def _route(
        self, endpoint: Endpoint, request: httpx.Request, record: MockRequest
    ) -> httpx.Response:
        params = record.params
        ident = _path_id(record.path)
        handlers: dict[Endpoint, Callable[[], httpx.Response]] = {
            ME: lambda: httpx.Response(200, json=user_json(self.catalog)),
            MY_PLAYLISTS: lambda: self._my_playlists(params),
            PLAYLIST: lambda: self._playlist(ident, params),
            PLAYLIST_ITEMS: lambda: self._playlist_items(ident, params),
            SAVED_TRACKS: lambda: self._saved_tracks(params),
            SAVED_ALBUMS: lambda: self._saved_albums(params),
            ALBUM_TRACKS: lambda: self._album_tracks(ident, params),
            DEVICES: lambda: httpx.Response(200, json={"devices": self._devices()}),
            PLAYER: self._player,
            PLAY: lambda: self._player_call(params, record.json, play=True),
            PAUSE: lambda: self._player_call(params, record.json),
            SEEK: lambda: self._player_call(params, record.json),
            SHUFFLE: lambda: self._player_call(params, record.json),
            REPEAT: lambda: self._player_call(params, record.json),
        }
        return handlers[endpoint]()

    def _my_playlists(self, params: dict[str, str]) -> httpx.Response:
        listed = self.catalog.library_playlists()
        return self._paged(
            "/me/playlists",
            params,
            listed,
            lambda item: playlist_json(item, listing=True, market=False),
        )

    def _playlist(self, ident: str, params: dict[str, str]) -> httpx.Response:
        item = self._visible_playlist(ident)
        if item is None:
            return _api_error(404, "Resource not found")
        body = playlist_json(item, listing=False, market="market" in params)
        return httpx.Response(200, json=_with_fields(body, params))

    def _playlist_items(self, ident: str, params: dict[str, str]) -> httpx.Response:
        item = self._visible_playlist(ident)
        if item is None:
            return _api_error(404, "Resource not found")
        if item.access not in ("owned", "collaborative"):
            return _api_error(403, "Forbidden")
        market = "market" in params
        response = self._paged(
            f"/playlists/{ident}/items",
            params,
            item.entries,
            lambda entry: playlist_entry_json(entry, market=market),
        )
        if response.status_code != 200 or "fields" not in params:
            return response
        return httpx.Response(200, json=_with_fields(response.json(), params))

    def _saved_tracks(self, params: dict[str, str]) -> httpx.Response:
        market = "market" in params
        liked = [entry for entry in self.catalog.liked if entry.track is not None]
        return self._paged(
            "/me/tracks",
            params,
            liked,
            lambda entry: {
                "added_at": entry.added_at,
                "track": track_json(entry.track, entry=entry, market=market),
            },
        )

    def _saved_albums(self, params: dict[str, str]) -> httpx.Response:
        market = "market" in params
        return self._paged(
            "/me/albums",
            params,
            self.catalog.saved_albums(),
            lambda album: {"added_at": album.added_at, "album": album_json(album, market=market)},
        )

    def _album_tracks(self, ident: str, params: dict[str, str]) -> httpx.Response:
        album = self.catalog.albums.get(ident)
        if album is None:
            return _api_error(404, "Resource not found")
        market = "market" in params
        tracks = [entry.track for entry in album.entries if entry.track is not None]
        return self._paged(
            f"/albums/{ident}/tracks",
            params,
            tracks,
            lambda track: track_json(track, market=market, with_album=False),
        )

    def _devices(self) -> list[dict[str, Any]]:
        specs = list(self.catalog.other_devices)
        if self.our_device_listed:
            specs.insert(0, self.catalog.our_device)
        return [
            {
                "id": spec.id,
                "is_active": spec.id == self.active_device_id,
                "is_private_session": False,
                "is_restricted": False,
                "name": spec.name,
                "supports_volume": True,
                "type": spec.type,
                "volume_percent": spec.volume_percent,
            }
            for spec in specs
        ]

    def _player(self) -> httpx.Response:
        if self.player_state is None:
            return httpx.Response(204)
        return httpx.Response(200, json=self.player_state)

    def _player_call(
        self, params: dict[str, str], body: Any, *, play: bool = False
    ) -> httpx.Response:
        device = params.get("device_id")
        listed = {d["id"] for d in self._devices()}
        if device is not None and device not in listed:
            return _api_error(404, "Device not found")
        if play and device is not None:
            self.active_device_id = device
        return httpx.Response(204)

    # --- Helpers -------------------------------------------------------------------------------

    def _visible_playlist(self, ident: str) -> CatalogPlaylist | None:
        item = self.catalog.playlists.get(ident)
        if item is None or item.access == "spotify" or ident.startswith(SPOTIFY_MADE_PREFIX):
            return None
        return item

    def _paged[T](
        self,
        path: str,
        params: dict[str, str],
        items: list[T],
        to_json: Callable[[T], Any],
    ) -> httpx.Response:
        try:
            limit = int(params.get("limit", DEFAULT_LIMIT))
            offset = int(params.get("offset", 0))
        except ValueError:
            return _api_error(400, "Invalid limit or offset")
        if not 1 <= limit <= MAX_LIMIT:
            return _api_error(400, "Invalid limit")
        if offset < 0:
            return _api_error(400, "Invalid offset")
        return httpx.Response(200, json=page_json(path, params, items, offset, limit, to_json))

    def _token(self, prefix: str, kind: str) -> str:
        self._serial += 1
        digest = hashlib.sha256(f"mock-{kind}-{self._serial}".encode()).digest()
        return prefix + base64.urlsafe_b64encode(digest).decode().rstrip("=")

    @staticmethod
    def _check_name(endpoint: str | None) -> None:
        if endpoint is not None and endpoint not in BY_NAME:
            raise ValueError(f"not an allowed endpoint: {endpoint!r}")


# --- JSON, as the 2026 Web API spells it ---------------------------------------------------------


def page_json[T](
    path: str,
    params: dict[str, str],
    items: list[T],
    offset: int,
    limit: int,
    to_json: Callable[[T], Any],
) -> dict[str, Any]:
    """A paging object. `next` and `previous` keep the request's other parameters."""
    chunk = items[offset : offset + limit]
    total = len(items)

    def link(at: int) -> str:
        query = {k: v for k, v in params.items() if k not in ("offset", "limit")}
        query.update({"offset": str(at), "limit": str(limit)})
        return f"{API_BASE}{path}?{urlencode(query)}"

    end = offset + len(chunk)
    return {
        "href": link(offset),
        "items": [to_json(item) for item in chunk],
        "limit": limit,
        "next": link(end) if end < total else None,
        "offset": offset,
        "previous": link(max(0, offset - limit)) if offset > 0 else None,
        "total": total,
    }


def user_json(catalog: Catalog) -> dict[str, Any]:
    user = catalog.user
    return {
        "display_name": user.display_name,
        "external_urls": {"spotify": f"https://open.spotify.com/user/{user.id}"},
        "href": f"{API_BASE}/users/{user.id}",
        "id": user.id,
        "type": "user",
        "uri": f"spotify:user:{user.id}",
    }


def images_json(images: tuple[Image, ...]) -> list[dict[str, Any]]:
    return [{"height": i.height, "url": i.url, "width": i.width} for i in images]


def playlist_json(item: CatalogPlaylist, *, listing: bool, market: bool) -> dict[str, Any]:
    """A playlist object. In /me/playlists (`listing`), `items` is `{href, total}`, followed
    playlists included (row 20). From GET /playlists/{id}, yours embed their first entries; a
    followed or linked one has no `items` at all (rows 20, 29)."""
    playlist = item.playlist
    owner_id = playlist.owner_id or "unknown"
    body: dict[str, Any] = {
        "collaborative": playlist.collaborative,
        "description": "",
        "external_urls": {"spotify": f"https://open.spotify.com/playlist/{playlist.id}"},
        "href": f"{API_BASE}/playlists/{playlist.id}",
        "id": playlist.id,
        "images": images_json(playlist.images),
        "name": playlist.name,
        "owner": {
            "display_name": playlist.owner_name,
            "external_urls": {"spotify": f"https://open.spotify.com/user/{owner_id}"},
            "href": f"{API_BASE}/users/{owner_id}",
            "id": owner_id,
            "type": "user",
            "uri": f"spotify:user:{owner_id}",
        },
        "primary_color": None,
        "public": playlist.public,
        "snapshot_id": playlist.snapshot_id,
        "type": "playlist",
        "uri": playlist.uri,
    }
    has_access = item.access in ("owned", "collaborative")
    items_href = f"{API_BASE}/playlists/{playlist.id}/items"
    if listing:
        if item.access != "linked":
            body["items"] = {"href": items_href, "total": len(item.entries)}
    elif has_access:
        body["items"] = page_json(
            f"/playlists/{playlist.id}/items",
            {},
            item.entries,
            0,
            ITEMS_IN_PLAYLIST_OBJECT,
            lambda entry: playlist_entry_json(entry, market=market),
        )
    else:
        body["followers"] = {"href": None, "total": 12}
    return body


def playlist_entry_json(entry: Entry, *, market: bool) -> dict[str, Any]:
    """A playlist entry: its track under `item` (2026), null for an empty entry."""
    track = entry.track
    return {
        "added_at": entry.added_at,
        "added_by": {
            "external_urls": {"spotify": "https://open.spotify.com/user/user2"},
            "href": f"{API_BASE}/users/user2",
            "id": "user2",
            "type": "user",
            "uri": "spotify:user:user2",
        },
        "is_local": bool(track is not None and track.is_local),
        "primary_color": None,
        "item": None if track is None else track_json(track, entry=entry, market=market),
    }


def track_json(
    track: Track | None,
    *,
    entry: Entry | None = None,
    market: bool,
    with_album: bool = True,
) -> dict[str, Any] | None:
    """A track object (an episode is one with `episode: true`, as without `additional_types`).
    `is_playable` only with a market. An album's own track list has no `album` (`with_album`)."""
    if track is None:
        return None
    body: dict[str, Any] = {
        "artists": [
            {
                "external_urls": {"spotify": "https://open.spotify.com/artist/" + _artist_id(n)},
                "href": f"{API_BASE}/artists/{_artist_id(n)}",
                "id": None if track.is_local else _artist_id(n),
                "name": n,
                "type": "artist",
                "uri": None if track.is_local else f"spotify:artist:{_artist_id(n)}",
            }
            for n in track.artists
        ],
        "disc_number": track.disc_number or 0,
        "duration_ms": track.duration_ms,
        "episode": track.is_episode,
        "explicit": False,
        "external_urls": {} if track.is_local else {"spotify": _open_url(track.uri)},
        "href": None if track.id is None else f"{API_BASE}/tracks/{track.id}",
        "id": track.id,
        "is_local": track.is_local,
        "name": track.name,
        "track": not track.is_episode,
        "track_number": track.track_number or 0,
        "type": "track",
        "uri": track.uri,
    }
    if market and not track.is_local:
        body["is_playable"] = track.is_playable is not False
    if with_album:
        art = entry.art_url if entry is not None else None
        album_artist = entry.album_artist if entry is not None else None
        body["album"] = {
            "album_type": "album",
            "artists": [{"name": album_artist or (track.artists[0] if track.artists else "")}],
            "id": track.album_id,
            "images": [{"height": 640, "url": art, "width": 640}] if art else [],
            "name": track.album_name or "",
            "release_date": "2024-01-01",
            "release_date_precision": "day",
            "type": "album",
            "uri": f"spotify:album:{track.album_id}" if track.album_id else None,
        }
    return body


def album_json(item: CatalogAlbum, *, market: bool) -> dict[str, Any]:
    """An album from /me/albums, with its first page of tracks under `tracks`."""
    album = item.album
    tracks = [entry.track for entry in item.entries if entry.track is not None]
    body: dict[str, Any] = {
        "album_type": "album",
        "artists": [
            {
                "id": _artist_id(n),
                "name": n,
                "type": "artist",
                "uri": f"spotify:artist:{_artist_id(n)}",
            }
            for n in album.artists
        ],
        "external_urls": {"spotify": f"https://open.spotify.com/album/{album.id}"},
        "href": f"{API_BASE}/albums/{album.id}",
        "id": album.id,
        "images": images_json(album.images),
        "name": album.name,
        "release_date": album.release_date,
        "release_date_precision": "day",
        "total_tracks": len(tracks),
        "tracks": page_json(
            f"/albums/{album.id}/tracks",
            {"market": "from_token"} if market else {},
            tracks,
            0,
            MAX_LIMIT,
            lambda track: track_json(track, market=market, with_album=False),
        ),
        "type": "album",
        "uri": album.uri,
    }
    if market:
        body["is_playable"] = True
    return body


# --- `fields`, as Spotify applies it -------------------------------------------------------------


def apply_fields(value: Any, fields: str) -> Any:
    """Keeps only what `fields` names: `a,b(c,d),e.f`. In a list, each element is filtered."""
    return _filter(value, _parse_fields(fields))


def _with_fields(body: Any, params: dict[str, str]) -> Any:
    fields = params.get("fields")
    return body if not fields else apply_fields(body, fields)


# A parsed `fields`: name → what to keep of it (None: all of it).
type _Spec = dict[str, "_Spec | None"]


def _parse_fields(text: str) -> _Spec:
    text = text.replace(" ", "")
    spec, at = _parse_list(text, 0)
    if at != len(text):
        raise ValueError(f"bad fields: {text!r}")
    return spec


def _parse_list(text: str, at: int) -> tuple[_Spec, int]:
    """`a,b(c),d.e` up to the end or a closing parenthesis."""
    spec: _Spec = {}
    while True:
        name, sub, at = _parse_item(text, at)
        spec[name] = _merge(spec[name], sub) if name in spec else sub
        if at < len(text) and text[at] == ",":
            at += 1
            continue
        return spec, at


def _parse_item(text: str, at: int) -> tuple[str, _Spec | None, int]:
    """One `name`, `name(list)` or `name.item`."""
    end = at
    while end < len(text) and text[end] not in ",().":
        end += 1
    name = text[at:end]
    if not name:
        raise ValueError(f"bad fields: {text!r}")
    at = end
    if at < len(text) and text[at] == "(":
        sub, at = _parse_list(text, at + 1)
        if at >= len(text) or text[at] != ")":
            raise ValueError(f"bad fields: {text!r}")
        return name, sub, at + 1
    if at < len(text) and text[at] == ".":
        child, child_sub, at = _parse_item(text, at + 1)
        return name, {child: child_sub}, at
    return name, None, at


def _merge(old: _Spec | None, new: _Spec | None) -> _Spec | None:
    """Two specs for one name: asking for all of it wins."""
    if old is None or new is None:
        return None
    merged = dict(old)
    for key, value in new.items():
        merged[key] = _merge(merged[key], value) if key in merged else value
    return merged


def _filter(value: Any, spec: _Spec | None) -> Any:
    if spec is None:
        return value
    if isinstance(value, list):
        return [_filter(v, spec) for v in value]
    if isinstance(value, dict):
        return {k: _filter(value[k], sub) for k, sub in spec.items() if k in value}
    return value


# --- Errors --------------------------------------------------------------------------------------


def _api_error(status: int, message: str, retry_after_s: int | None = None) -> httpx.Response:
    headers = {"Retry-After": str(retry_after_s)} if retry_after_s is not None else None
    return httpx.Response(
        status, json={"error": {"status": status, "message": message}}, headers=headers
    )


def _oauth_error(status: int, error: str, description: str) -> httpx.Response:
    return httpx.Response(status, json={"error": error, "error_description": description})


def _error(status: int, body: Any, retry_after_s: int | None, endpoint: Endpoint) -> httpx.Response:
    if body is not None:
        headers = {"Retry-After": str(retry_after_s)} if retry_after_s is not None else None
        return httpx.Response(status, json=body, headers=headers)
    if endpoint is TOKEN and status == 400:
        return _oauth_error(400, "invalid_grant", "Refresh token revoked")
    messages = {
        429: "API rate limit exceeded",
        500: "Server error",
        502: "Bad gateway",
        503: "Service unavailable",
    }
    return _api_error(status, messages.get(status, "Error"), retry_after_s)


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _path_id(path: str) -> str:
    """The {id} segment of /v1/playlists/<id>/items and the like, or ''."""
    parts = path.split("/")
    return parts[3] if len(parts) > 3 and parts[2] in ("playlists", "albums") else ""


def _artist_id(name: str) -> str:
    return base64.b32encode(hashlib.sha1(name.encode()).digest()).decode()[:22]


def _open_url(uri: str) -> str:
    _, kind, ident = (uri.split(":") + ["", ""])[:3]
    return f"https://open.spotify.com/{kind}/{ident}"


# --- Services on the mock ------------------------------------------------------------------------


def use_mock(services: Services, mock: SpotifyMock) -> SpotifyWebApi:
    """Puts the real Web API port, on `mock`, in place of the fake one, and returns it. The
    other ports stay fake. Modules reach the port at call time, so this works before or after
    the lifespan starts."""
    api = SpotifyWebApi(
        services.config, services.clock, services.store, services.auth, transport=mock.transport()
    )
    services.ports.webapi = api
    return api


async def connect(services: Services, mock: SpotifyMock) -> tuple[str, str]:
    """Stores a working connection, as a finished wizard step 5 leaves it: the mock's Client ID,
    a fresh token pair the mock accepts, and its user. Needs the store open (a running app).
    Returns the (access, refresh) tokens, for tests that look for them where they mustn't be."""
    access, refresh = mock.issue_tokens()
    await services.auth.set_client_id(mock.client_id)
    grant = TokenGrant(
        access_token=access,
        refresh_token=refresh,
        expires_in_s=mock.access_token_ttl_s,
        scopes=SCOPES,
    )
    await services.auth.save_grant(mock.client_id, grant)
    await services.auth.set_account(mock.catalog.user)
    return access, refresh


def our_device_id(mock: SpotifyMock) -> str:
    """The id the mock gives the container's device."""
    return device_id(mock.device_name)


# --- Running calls on the FakeClock --------------------------------------------------------------


async def drive[T](clock: FakeClock, *calls: Awaitable[T], within: float = 3600.0) -> list[T]:
    """Runs the calls together to the end. Whenever something sleeps on the fake clock, the
    clock jumps to the next deadline; real time passes too, for the database thread. Raises the
    first call's error, if any failed, and TimeoutError after `within` seconds of fake time."""
    tasks = [asyncio.ensure_future(call) for call in calls]
    limit = clock.monotonic() + within
    try:
        while not all(task.done() for task in tasks):
            # Real time, so the database thread and the mock's answers get their turn.
            await asyncio.sleep(0.002)
            due = clock.next_deadline()
            if due is not None:
                if due > limit:
                    raise TimeoutError(f"still running after {within} s of fake time")
                await clock.advance(max(0.0, due - clock.monotonic()))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
    errors = [task.exception() for task in tasks]
    for error in errors:
        if error is not None:
            raise error
    return [task.result() for task in tasks]


async def run[T](clock: FakeClock, call: Awaitable[T], *, within: float = 3600.0) -> T:
    """`drive` for one call: catalog calls in a row wait out the 250 ms spacing on the clock."""
    [result] = await drive(clock, call, within=within)
    return result


__all__ = [
    "MOCK_CLIENT_ID",
    "Failure",
    "MockRequest",
    "SpotifyMock",
    "UnexpectedRequest",
    "apply_fields",
    "connect",
    "drive",
    "our_device_id",
    "run",
    "use_mock",
]
