"""Pasted playlist links and URIs (the Library's + modal; prototype/probe.py `parse_uri`).

Owner: catalog-library.

Accepted, with surrounding spaces ignored:
- `https://open.spotify.com/playlist/<id>`, with an optional `intl-xx/` before `playlist`, and
  any query (`?si=…`) or fragment;
- `spotify:playlist:<id>`.
The id is 22 base-62 characters. Anything else is `invalid_url`. An id starting with
SPOTIFY_MADE_PREFIX is a playlist made by Spotify (S0 row 28: the API answers 404 for them):
refused as `spotify_owned` without asking the Web API.
"""

import re
from urllib.parse import urlsplit

SPOTIFY_MADE_PREFIX = "37i9dQZF1"

_ID = r"[0-9A-Za-z]{22}"
_URI = re.compile(rf"spotify:playlist:({_ID})")
# The path of an open.spotify.com link: an optional language part (`/intl-de`, `/intl-pt-BR`),
# then `/playlist/<id>`, with or without a slash at the end.
_LINK_PATH = re.compile(rf"(?:/intl-[A-Za-z]{{2}}(?:-[A-Za-z]{{2}})?)?/playlist/({_ID})/?")


class LinkError(ValueError):
    """A link that can't be used. `code` is the API's error code: invalid_url, spotify_owned."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def parse_playlist_link(text: str) -> str:
    """The playlist id in a pasted link or URI. Raises LinkError (see the module docstring)."""
    text = text.strip()
    playlist_id = _uri_id(text) or _link_id(text)
    if playlist_id is None:
        raise LinkError("invalid_url", "That isn't a Spotify playlist link.")
    if is_spotify_made(playlist_id):
        raise LinkError(
            "spotify_owned", "Playlists made by Spotify aren't available through the API."
        )
    return playlist_id


def is_spotify_made(playlist_id: str) -> bool:
    return playlist_id.startswith(SPOTIFY_MADE_PREFIX)


def _uri_id(text: str) -> str | None:
    match = _URI.fullmatch(text)
    return match.group(1) if match else None


def _link_id(text: str) -> str | None:
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:  # a malformed address, such as a port that isn't a number
        return None
    if parts.scheme.lower() != "https" or (parts.hostname or "").lower() != "open.spotify.com":
        return None
    if parts.username is not None or parts.password is not None or port not in (None, 443):
        return None
    match = _LINK_PATH.fullmatch(parts.path)
    return match.group(1) if match else None
