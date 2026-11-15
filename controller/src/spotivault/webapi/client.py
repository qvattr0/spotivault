"""`SpotifyWebApi`: the real `ports.WebApi`, on httpx.AsyncClient (design.md § Web API usage).

Owner: webapi-core. Frozen: the constructor's signature (services.py and tests/spotify_mock.py
build it) and every `ports.WebApi` method's signature (tests/test_ports.py checks them).

**What each call does**, in order:
1. **The endpoint** comes from `endpoints.py`, never a hand-written URL: it can't reach anything
   design.md doesn't allow. Ids go through `Endpoint.url(id=...)`.
2. **The token:** `self.tokens.access_token()` gives a valid one, refreshing it first when it
   expires within 60 s. No Client ID or token: NotConnected, before any request. A stored
   `invalid_grant_at`: ConnectionExpired, before any request.
3. **The scheduler** (`self.scheduler`): the call waits its turn in its endpoint's lane. One
   request is in flight at a time; playback (and auth) calls go before waiting catalog calls;
   catalog calls start at least 250 ms apart. Only the HTTP attempt holds the turn: waiting for a
   retry happens outside it, so a catalog retry never delays a playback call.
4. **The request:** `Authorization: Bearer <token>`. Track listings add `market=from_token`, so
   `is_playable` is in the answer. The two playlist endpoints add `fields` (design.md § Load),
   naming only what the controller stores: see PLAYLIST_FIELDS and PLAYLIST_ITEMS_FIELDS below.
   Listings take `offset` and `limit` (1–50).
5. **Each attempt is a usage-log row** (`self.usage.record`): send time, endpoint, status or
   error, latency, attempt number, Retry-After, scope. Endpoint templates only, never ids.
6. **Retries** (design.md § Requests): a 429 waits Retry-After; a 5xx or a timeout waits 5 s, then
   10 s, then 20 s (3 retries; with a Retry-After on a 5xx, the longer wait wins); a 401 refreshes
   the token once and retries. The 3 retries are one budget per call, shared by 429s, 5xx,
   timeouts and network errors, and the resend after a 401 goes on with what's left of it.
   After the last retry: SpotifyUnavailable (5xx, timeouts, network errors) or RateLimited (429).
   A Retry-After longer than RATE_LIMIT_MAX_WAIT_S isn't waited out: RateLimited at once, with
   `retry_after_s`. A 429 holds back every lane until it passes: Spotify's limits are per app,
   not per endpoint. While such a long hold lasts, a call is refused with RateLimited before any
   request, instead of waiting minutes for its turn: a new call at once, and a call already
   waiting for its turn as soon as the hold starts (the scheduler's `max_hold_s`).
7. **Answers that aren't retried:** 403 → NoAccess, 404 → NotFound (Spotify-made playlists answer
   404 too), any other 4xx → WebApiError with its status. A 2xx is parsed by `parse.py`.

**Secrets:** the access token, refresh token, PKCE verifier and auth code never reach a log line,
an exception message, an event, an API answer or the usage log. Messages name the endpoint by its
template and quote only Spotify's short error text, through `logs.redact`.

**Responses use the 2026 field names** (design.md § Web API usage): a playlist's contents under
`items` (with `total`), a playlist entry's track under `item`; `/me/tracks` entries keep `track`,
`/me/albums` entries keep `album`, with the album's first page of tracks under `album.tracks`.
"""

import asyncio
import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from spotivault.config import Config
from spotivault.logs import redact
from spotivault.ports import (
    OTHER,
    SETUP,
    ApiScope,
    Clock,
    Device,
    NoAccess,
    NotFound,
    Page,
    PlayerState,
    Playlist,
    PlaylistEntry,
    RateLimited,
    RepeatState,
    SavedAlbum,
    SavedTrack,
    SpotifyUnavailable,
    SpotifyUser,
    TokenExchangeFailed,
    TokenGrant,
    Track,
    WebApiError,
)
from spotivault.store import Store
from spotivault.webapi.auth_store import AuthStore
from spotivault.webapi.endpoints import (
    ALBUM_TRACKS,
    DEVICES,
    ME,
    MY_PLAYLISTS,
    PAUSE,
    PLAY,
    PLAYER,
    PLAYLIST,
    PLAYLIST_ITEMS,
    REPEAT,
    SAVED_ALBUMS,
    SAVED_TRACKS,
    SEEK,
    SHUFFLE,
    TOKEN,
    Endpoint,
)
from spotivault.webapi.parse import (
    parse_device,
    parse_page,
    parse_player_state,
    parse_playlist,
    parse_playlist_entry,
    parse_saved_album,
    parse_saved_track,
    parse_token_grant,
    parse_track,
    parse_user,
)
from spotivault.webapi.scheduler import LongHold, RequestScheduler
from spotivault.webapi.tokens import TokenManager, oauth_error
from spotivault.webapi.usage import Attempt, AttemptError, UsageRecorder

log = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 20.0  # one HTTP attempt, connect to last byte
RATE_LIMIT_MAX_WAIT_S = 120  # a longer Retry-After raises RateLimited instead of waiting
SERVER_ERROR_DELAYS_S = (5.0, 10.0, 20.0)  # design.md § Requests: 5 s, doubling, 3 retries
PAGE_LIMIT = 50
MARKET = "from_token"  # track listings: `is_playable` for the account's own country

# `fields` for the playlist endpoints (design.md § Load): only what's stored. Spotify documents
# `fields` on these two; the other listings answer their whole objects. tests/spotify_mock.py
# applies them like Spotify does. `episode` is asked for because, without `additional_types`,
# Spotify sends an episode as a track object with `episode: true`.
PLAYLIST_FIELDS = (
    "id,uri,name,owner(id,display_name),collaborative,public,snapshot_id,"
    "images(url,width,height),items(total)"
)
PLAYLIST_ITEMS_FIELDS = (
    "total,limit,offset,next,items(added_at,is_local,item(type,episode,id,uri,name,duration_ms,"
    "is_local,is_playable,track_number,disc_number,artists(name),"
    "album(id,name,images(url,width,height))))"
)


class SpotifyWebApi:
    """`ports.WebApi` against api.spotify.com and accounts.spotify.com. See the module docstring.

    Building it touches nothing: the HTTP client is made on first use. `transport` is for tests
    (tests/spotify_mock.py's `SpotifyMock.transport()`).
    """

    def __init__(
        self,
        config: Config,
        clock: Clock,
        store: Store,
        auth: AuthStore,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.clock = clock
        self.auth = auth
        self.usage = UsageRecorder(store, clock)
        self.scheduler = RequestScheduler(clock)
        self.tokens = TokenManager(auth, clock, post=self._post_token)
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    # --- ports.WebApi --------------------------------------------------------------------------

    async def exchange_code(
        self,
        *,
        client_id: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        scope: ApiScope = SETUP,
    ) -> TokenGrant:
        """POST accounts.spotify.com/api/token, form-encoded: grant_type=authorization_code,
        code, redirect_uri, client_id, code_verifier (PKCE: no client secret). Lane `auth`, one
        usage row. A 400 (`invalid_grant`, a wrong verifier, an old code) is TokenExchangeFailed;
        5xx and timeouts are retried like any call. `scope` in the answer is space-separated.
        Stores nothing: the caller saves the grant (AuthStore.save_grant)."""
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        }
        response = await self._post_token(form, scope)
        status = response.status_code
        if not 200 <= status < 300:
            error = oauth_error(response) or "no error code"
            raise TokenExchangeFailed(
                f"Spotify refused the authorization code ({status}, {error})", status=status
            )
        try:
            return parse_token_grant(response.json())
        except (ValueError, KeyError, TypeError) as exc:
            raise TokenExchangeFailed(
                f"the code exchange answered something unexpected ({type(exc).__name__})",
                status=status,
            ) from None

    async def me(self, *, scope: ApiScope = OTHER) -> SpotifyUser:
        """GET /me."""
        body = await self._get_json(ME, scope=scope)
        return _parsed(ME, lambda: parse_user(body))

    async def my_playlists(
        self, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[Playlist]:
        """GET /me/playlists. `items.total` is read even for followed playlists (S0 row 20)."""
        params = _page_params(offset, limit)
        body = await self._get_json(MY_PLAYLISTS, scope=scope, params=params)
        return _parsed(
            MY_PLAYLISTS,
            lambda: parse_page(body, [parse_playlist(p) for p in _entries(body)]),
        )

    async def playlist(self, playlist_id: str, *, scope: ApiScope = OTHER) -> Playlist:
        """GET /playlists/{id} with PLAYLIST_FIELDS. A linked playlist has no `items`, so its
        total is None (S0 row 29). 404 → NotFound (Spotify-made playlists too, row 28)."""
        params = {"fields": PLAYLIST_FIELDS}
        body = await self._get_json(PLAYLIST, scope=scope, id=playlist_id, params=params)
        return _parsed(PLAYLIST, lambda: parse_playlist(body))

    async def playlist_items(
        self, playlist_id: str, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[PlaylistEntry]:
        """GET /playlists/{id}/items with PLAYLIST_ITEMS_FIELDS and market=from_token. The track
        is under `item` (None for an empty entry). 403 → NoAccess."""
        params = _page_params(offset, limit) | {"market": MARKET, "fields": PLAYLIST_ITEMS_FIELDS}
        body = await self._get_json(PLAYLIST_ITEMS, scope=scope, id=playlist_id, params=params)
        return _parsed(
            PLAYLIST_ITEMS,
            lambda: parse_page(body, [parse_playlist_entry(e) for e in _entries(body)]),
        )

    async def saved_tracks(
        self, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[SavedTrack]:
        """GET /me/tracks with market=from_token: Liked Songs, newest first, under `track`."""
        params = _page_params(offset, limit) | {"market": MARKET}
        body = await self._get_json(SAVED_TRACKS, scope=scope, params=params)
        return _parsed(
            SAVED_TRACKS,
            lambda: parse_page(
                body,
                [parse_saved_track(e) for e in _entries(body) if isinstance(e.get("track"), dict)],
            ),
        )

    async def saved_albums(
        self, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[SavedAlbum]:
        """GET /me/albums with market=from_token, each under `album`, with its first page of
        tracks under `album.tracks` (they carry no `album` of their own: parse.py passes it in)."""
        params = _page_params(offset, limit) | {"market": MARKET}
        body = await self._get_json(SAVED_ALBUMS, scope=scope, params=params)
        return _parsed(
            SAVED_ALBUMS,
            lambda: parse_page(
                body,
                [parse_saved_album(e) for e in _entries(body) if isinstance(e.get("album"), dict)],
            ),
        )

    async def album_tracks(
        self, album_id: str, *, offset: int = 0, limit: int = 50, scope: ApiScope = OTHER
    ) -> Page[Track]:
        """GET /albums/{id}/tracks with market=from_token. Tracks have no `album` here, so each
        gets this album's id (its name stays None)."""
        params = _page_params(offset, limit) | {"market": MARKET}
        body = await self._get_json(ALBUM_TRACKS, scope=scope, id=album_id, params=params)
        album = {"id": album_id}
        return _parsed(
            ALBUM_TRACKS,
            lambda: parse_page(body, [parse_track(t, album=album) for t in _entries(body)]),
        )

    async def devices(self, *, scope: ApiScope = OTHER) -> list[Device]:
        """GET /me/player/devices. Lane `playback`."""
        body = await self._get_json(DEVICES, scope=scope)
        return _parsed(
            DEVICES,
            lambda: [parse_device(d) for d in body.get("devices") or () if isinstance(d, dict)],
        )

    async def player_state(self, *, scope: ApiScope = OTHER) -> PlayerState | None:
        """GET /me/player; None on 204 (nothing playing anywhere). Lane `playback`."""
        response = await self._api(PLAYER, scope=scope)
        if response.status_code == 204 or not response.content.strip():
            return None
        body = _json_object(PLAYER, response)
        return _parsed(PLAYER, lambda: parse_player_state(body))

    async def play(
        self,
        *,
        device_id: str,
        context_uri: str,
        offset_uri: str | None = None,
        position_ms: int = 0,
        scope: ApiScope = OTHER,
    ) -> None:
        """PUT /me/player/play?device_id=…, body {context_uri, offset: {uri}, position_ms}.
        Never `offset.position` (it counts only playable entries). Lane `playback`."""
        body: dict[str, Any] = {"context_uri": context_uri, "position_ms": position_ms}
        if offset_uri is not None:
            body["offset"] = {"uri": offset_uri}
        await self._api(PLAY, scope=scope, params={"device_id": device_id}, json_body=body)

    async def pause(self, *, device_id: str, scope: ApiScope = OTHER) -> None:
        """PUT /me/player/pause?device_id=…"""
        await self._api(PAUSE, scope=scope, params={"device_id": device_id})

    async def seek(self, position_ms: int, *, device_id: str, scope: ApiScope = OTHER) -> None:
        """PUT /me/player/seek?position_ms=…&device_id=…"""
        params = {"position_ms": str(position_ms), "device_id": device_id}
        await self._api(SEEK, scope=scope, params=params)

    async def set_shuffle(self, state: bool, *, device_id: str, scope: ApiScope = OTHER) -> None:
        """PUT /me/player/shuffle?state=true|false&device_id=…"""
        params = {"state": "true" if state else "false", "device_id": device_id}
        await self._api(SHUFFLE, scope=scope, params=params)

    async def set_repeat(
        self, state: RepeatState, *, device_id: str, scope: ApiScope = OTHER
    ) -> None:
        """PUT /me/player/repeat?state=off|track|context&device_id=…"""
        await self._api(REPEAT, scope=scope, params={"state": state, "device_id": device_id})

    async def aclose(self) -> None:
        """Closes the HTTP client, if one was made. Must work when nothing was ever sent."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # --- One call: token, 401, answer ----------------------------------------------------------

    async def _get_json(
        self,
        endpoint: Endpoint,
        *,
        scope: ApiScope,
        id: str | None = None,
        params: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self._api(endpoint, scope=scope, id=id, params=params)
        return _json_object(endpoint, response)

    async def _api(
        self,
        endpoint: Endpoint,
        *,
        scope: ApiScope,
        id: str | None = None,
        params: Mapping[str, str] | None = None,
        json_body: Any = None,
    ) -> httpx.Response:
        """One api.spotify.com call with the stored token: a 401 refreshes the token once and
        sends again. Returns a 2xx answer, or raises the error its status means."""
        url = endpoint.url(id=id)  # checks the id before anything else happens
        token = await self.tokens.access_token(scope=scope)
        response, attempt, retries = await self._send(
            endpoint, url, scope=scope, token=token, params=params, json_body=json_body
        )
        if response.status_code == 401:
            # The token was refused before its time (revoked, or the clock is off): refresh once.
            # The resend goes on with the same retry budget (design.md § Requests: 3 per call).
            token = await self.tokens.refresh(scope=scope, stale_token=token)
            response, attempt, retries = await self._send(
                endpoint,
                url,
                scope=scope,
                token=token,
                params=params,
                json_body=json_body,
                first_attempt=attempt + 1,
                retries_used=retries,
            )
        _raise_for_answer(endpoint, response)
        return response

    async def _post_token(self, form: Mapping[str, str], scope: ApiScope) -> httpx.Response:
        """One form to accounts.spotify.com/api/token (TokenManager uses it for refreshes).
        Returns Spotify's answer, 2xx or 4xx: the caller reads it."""
        response, _, _ = await self._send(TOKEN, TOKEN.url(), scope=scope, form=form)
        return response

    # --- One call: the attempts, the scheduler, the retries -------------------------------------

    async def _send(
        self,
        endpoint: Endpoint,
        url: str,
        *,
        scope: ApiScope,
        token: str | None = None,
        params: Mapping[str, str] | None = None,
        json_body: Any = None,
        form: Mapping[str, str] | None = None,
        first_attempt: int = 1,
        retries_used: int = 0,
    ) -> tuple[httpx.Response, int, int]:
        """Sends one call, retrying 429s, 5xx, timeouts and network errors (module docstring,
        step 6). `retries_used` is what an earlier send of the same call already spent (the
        send before a 401). Returns the answer that ended it (any status but 429 and 5xx), the
        number of its attempt and the retries spent so far. Raises RateLimited or
        SpotifyUnavailable when it gives up."""
        http = self._client()
        attempt = first_attempt
        retries = retries_used
        while True:
            self._refuse_during_long_hold(endpoint)
            request = _build_request(
                http, endpoint, url, token=token, params=params, json_body=json_body, form=form
            )
            try:
                sent = await self._attempt(endpoint, http, request, retries)
            except LongHold as hold:
                # A 429 from another call started a long hold while this one waited for its
                # turn: refused like a new call would be, with nothing sent.
                raise _long_hold_error(endpoint, hold.held_s) from None
            response = sent.response
            retry_after = sent.retry_after_s
            error = sent.error
            status = response.status_code if response is not None else None
            if response is not None and _is_invalid_grant(endpoint, response):
                error = "invalid_grant"
            await self.usage.record(
                Attempt(
                    at=sent.at,
                    endpoint=endpoint,
                    status=status,
                    error=error,
                    latency_ms=sent.latency_ms,
                    attempt=attempt,
                    retry_after_s=retry_after,
                    scope=scope,
                )
            )

            if response is not None and status is not None and status != 429 and status < 500:
                return response, attempt, retries
            wait = self._retry_wait(endpoint, status, error, retry_after, retries)
            log.info(
                "Web API: %s %s; retry %d of %d in %g s",
                endpoint.name,
                f"answered {status}" if status is not None else f"failed ({error})",
                retries + 1,
                len(SERVER_ERROR_DELAYS_S),
                wait,
            )
            await self.clock.sleep(wait)  # outside the turn: other calls go meanwhile
            retries += 1
            attempt += 1

    async def _attempt(
        self, endpoint: Endpoint, http: httpx.AsyncClient, request: httpx.Request, retries: int
    ) -> "_Sent":
        """One HTTP attempt, inside the scheduler's turn. Raises LongHold, with nothing sent,
        when a 429's hold has more than RATE_LIMIT_MAX_WAIT_S left while it waits for the turn."""
        response: httpx.Response | None = None
        error: AttemptError | None = None
        async with self.scheduler.turn(endpoint.lane, max_hold_s=RATE_LIMIT_MAX_WAIT_S):
            at = self.clock.now()
            started = self.clock.monotonic()
            try:
                # httpx's timeout is per phase (connect, each read); this one bounds the whole
                # attempt. It's real time, like the network it waits for.
                async with asyncio.timeout(REQUEST_TIMEOUT_S):
                    response = await http.send(request)
            except (httpx.TimeoutException, TimeoutError):
                error = "timeout"
            except httpx.RequestError:
                error = "network"
            latency_ms = max(0, round((self.clock.monotonic() - started) * 1000))
            retry_after = _retry_after_s(response)
            if response is not None and response.status_code == 429:
                # Spotify's limits are per app: hold every lane, before the turn is freed, so
                # no other request slips in. Callers waiting for a turn are woken by it.
                hold_s = retry_after if retry_after is not None else _delay(retries)
                self.scheduler.hold_until(self.clock.monotonic() + hold_s)
        return _Sent(
            at=at,
            response=response,
            error=error,
            latency_ms=latency_ms,
            retry_after_s=retry_after,
        )

    def _retry_wait(
        self,
        endpoint: Endpoint,
        status: int | None,
        error: AttemptError | None,
        retry_after: int | None,
        retries: int,
    ) -> float:
        """How long to wait before the next attempt, or the error that ends the call."""
        what = f"{status}" if status is not None else (error or "error")
        too_long = retry_after is not None and retry_after > RATE_LIMIT_MAX_WAIT_S
        if status == 429:
            if too_long:
                raise RateLimited(
                    f"{endpoint.name}: rate-limited; Retry-After {retry_after} s is too long to "
                    "wait",
                    retry_after_s=retry_after,
                )
            if retries >= len(SERVER_ERROR_DELAYS_S):
                raise RateLimited(
                    f"{endpoint.name}: still rate-limited after {retries} retries",
                    retry_after_s=retry_after,
                )
            return float(retry_after) if retry_after is not None else _delay(retries)
        if too_long or retries >= len(SERVER_ERROR_DELAYS_S):
            raise SpotifyUnavailable(
                f"{endpoint.name}: Spotify is unavailable ({what}, after {retries} retries)",
                status=status,
            )
        if retry_after is not None:
            return max(_delay(retries), float(retry_after))  # the longer wait wins
        return _delay(retries)

    def _refuse_during_long_hold(self, endpoint: Endpoint) -> None:
        """A 429's Retry-After over RATE_LIMIT_MAX_WAIT_S holds every lane: refuse at once
        instead of waiting minutes for a turn."""
        held = self.scheduler.held_for()
        if held > RATE_LIMIT_MAX_WAIT_S:
            raise _long_hold_error(endpoint, held)

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(REQUEST_TIMEOUT_S),
                follow_redirects=False,
            )
        return self._http


# --- Helpers ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Sent:
    """What one HTTP attempt gave: an answer, or the error that stopped it."""

    at: datetime  # when it was sent (clock.now())
    response: httpx.Response | None
    error: AttemptError | None  # "timeout" or "network" when there's no answer
    latency_ms: int
    retry_after_s: int | None


def _long_hold_error(endpoint: Endpoint, held_s: float) -> RateLimited:
    """The refusal while a 429's hold has more than RATE_LIMIT_MAX_WAIT_S left."""
    seconds = math.ceil(held_s)
    return RateLimited(
        f"{endpoint.name}: rate-limited for {seconds} s more; not sent", retry_after_s=seconds
    )


def _build_request(
    http: httpx.AsyncClient,
    endpoint: Endpoint,
    url: str,
    *,
    token: str | None,
    params: Mapping[str, str] | None,
    json_body: Any,
    form: Mapping[str, str] | None,
) -> httpx.Request:
    """A new request for each attempt. The token only ever goes into the Authorization
    header."""
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    query = dict(params) if params else None
    if form is not None:
        return http.build_request(
            endpoint.method, url, params=query, data=dict(form), headers=headers
        )
    if json_body is not None:
        return http.build_request(
            endpoint.method, url, params=query, json=json_body, headers=headers
        )
    if endpoint.method in ("PUT", "POST"):
        # Spotify wants a Content-Length on a PUT, even an empty one.
        return http.build_request(endpoint.method, url, params=query, content=b"", headers=headers)
    return http.build_request(endpoint.method, url, params=query, headers=headers)


def _delay(retries: int) -> float:
    """The 5 / 10 / 20 s backoff for the retry after `retries` earlier ones."""
    return SERVER_ERROR_DELAYS_S[min(retries, len(SERVER_ERROR_DELAYS_S) - 1)]


def _retry_after_s(response: httpx.Response | None) -> int | None:
    """Retry-After in whole seconds, rounded up, or None when there's none (or it's a date)."""
    if response is None:
        return None
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return math.ceil(seconds)


def _is_invalid_grant(endpoint: Endpoint, response: httpx.Response) -> bool:
    return (
        endpoint is TOKEN
        and response.status_code == 400
        and oauth_error(response) == "invalid_grant"
    )


def _page_params(offset: int, limit: int) -> dict[str, str]:
    if not 1 <= limit <= PAGE_LIMIT:
        raise ValueError(f"limit must be 1 to {PAGE_LIMIT}, not {limit}")
    if offset < 0:
        raise ValueError(f"offset must be 0 or more, not {offset}")
    return {"offset": str(offset), "limit": str(limit)}


def _raise_for_answer(endpoint: Endpoint, response: httpx.Response) -> None:
    """Nothing for a 2xx; otherwise the error the status means (not retried: an answer)."""
    status = response.status_code
    if 200 <= status < 300:
        return
    message = _spotify_message(response)
    if status == 401:
        raise WebApiError(
            f"{endpoint.name}: Spotify refused the token again after a refresh ({message})",
            status=401,
        )
    if status == 403:
        raise NoAccess(f"{endpoint.name}: no access ({message})", status=403)
    if status == 404:
        raise NotFound(f"{endpoint.name}: not found ({message})", status=404)
    raise WebApiError(f"{endpoint.name} answered {status} ({message})", status=status)


def _spotify_message(response: httpx.Response) -> str:
    """Spotify's own short error text (`error.message`), redacted and cut short."""
    try:
        body = response.json()
    except ValueError:
        return "no message"
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if not isinstance(message, str) or not message:
        return "no message"
    return redact(message)[:200]


def _json_object(endpoint: Endpoint, response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise WebApiError(
            f"{endpoint.name}: the answer isn't a JSON object", status=response.status_code
        )
    return body


def _entries(body: dict[str, Any]) -> list[dict[str, Any]]:
    """A page's `items`, leaving out nulls (a deleted playlist can be one)."""
    items = body.get("items")
    if not isinstance(items, list):
        raise ValueError("no items list")
    return [item for item in items if isinstance(item, dict)]


def _parsed[T](endpoint: Endpoint, parse: Callable[[], T]) -> T:
    """Runs a parse.py function on an answer; one it can't read is a WebApiError."""
    try:
        return parse()
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise WebApiError(
            f"{endpoint.name}: an answer spotivault can't read ({type(exc).__name__})", status=200
        ) from None
