"""PKCE for wizard step 5 (web-ui.md § 5; prototype/probe.py `cmd_auth`; RFC 7636).

Owner: spotify-connect. Only connection.py uses it; the signatures below are a suggestion.

- **Verifier:** 64 random bytes, base64url without padding (86 characters; RFC 7636 allows 43–128),
  from `secrets`. **Challenge:** base64url(sha256(verifier)) without padding, method S256.
  **State:** `secrets.token_urlsafe(16)`.
- **The authorize URL:** endpoints.AUTHORIZE_URL with client_id, response_type=code,
  redirect_uri=endpoints.REDIRECT_URI, code_challenge_method=S256, code_challenge,
  scope (endpoints.SCOPES joined by spaces) and state, URL-encoded.
- **The pasted address** must be the redirect URI itself: http, host 127.0.0.1, port 8888, path
  /callback (anything else: `invalid_redirect`). Its query has `code` and `state`, or
  `error=access_denied` when you declined. Surrounding spaces are ignored.
- **Secrets:** the verifier and the code are never logged, put in an event or returned by the API.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlsplit

from spotivault.webapi.endpoints import AUTHORIZE_URL, REDIRECT_URI, SCOPES

# The callback address, split once: every pasted address is compared with these parts.
_CALLBACK = urlsplit(REDIRECT_URI)


@dataclass(frozen=True, slots=True)
class Pkce:
    verifier: str = field(repr=False)
    challenge: str


@dataclass(frozen=True, slots=True)
class Redirect:
    """What the pasted callback address says. Exactly one of `code` and `error` is set."""

    code: str | None = field(repr=False)
    state: str | None
    error: str | None  # Spotify's `error`, such as access_denied


class InvalidRedirect(ValueError):
    """The pasted text isn't the callback address."""


def _base64url(data: bytes) -> str:
    """base64url without the trailing '=' padding (RFC 7636 Appendix A)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def new_pkce() -> Pkce:
    """A fresh verifier (86 random characters) and its S256 challenge."""
    verifier = _base64url(secrets.token_bytes(64))
    return Pkce(verifier=verifier, challenge=challenge_for(verifier))


def challenge_for(verifier: str) -> str:
    """S256: base64url(sha256(verifier)), no padding."""
    return _base64url(hashlib.sha256(verifier.encode("ascii")).digest())


def new_state() -> str:
    """The `state` parameter: checked when the address comes back, so an old one is refused."""
    return secrets.token_urlsafe(16)


def authorize_url(*, client_id: str, challenge: str, state: str) -> str:
    """Spotify's consent page for these scopes, with the PKCE challenge and the state."""
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "scope": " ".join(SCOPES),
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def parse_redirect(text: str) -> Redirect:
    """Reads the pasted address. Raises InvalidRedirect when it isn't the callback address, or
    has neither a code nor an error."""
    try:
        parts = urlsplit(text.strip())
        port = parts.port
    except ValueError as exc:  # a malformed address, such as a broken port
        raise InvalidRedirect("not a URL") from exc
    # Only the exact callback: no other scheme, host, port, path or user part.
    if (
        parts.scheme != _CALLBACK.scheme
        or parts.hostname != _CALLBACK.hostname
        or port != _CALLBACK.port
        or parts.path != _CALLBACK.path
        or parts.username is not None
        or parts.password is not None
    ):
        raise InvalidRedirect("not the callback address")

    query = parse_qs(parts.query)
    state = _first(query, "state")
    error = _first(query, "error")
    if error is not None:
        return Redirect(code=None, state=state, error=error)
    code = _first(query, "code")
    if code is None:
        raise InvalidRedirect("the address has neither a code nor an error")
    return Redirect(code=code, state=state, error=None)


def _first(query: dict[str, list[str]], key: str) -> str | None:
    """The first non-empty value of a query parameter, or None."""
    values = query.get(key)
    if not values or not values[0]:
        return None
    return values[0]
