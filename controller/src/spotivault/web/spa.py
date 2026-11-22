"""The web UI: the built React app (S7) and the static pages, from the web root.

The web root is SPOTIVAULT_WEB_ROOT: `/usr/local/share/spotivault/web` in the image, where the
image build puts these files:

- `/`, `/index.html` and every app route (`/library`, `/settings/files`, …): `index.html`, the
  built UI (S7's `web/dist/`);
- `/assets/…`: Vite's content-hashed files;
- `/vnc.html`: the web root's `vnc.html` if there is one, else the controller's own copy,
  `web/static/vnc.html` (the S2 stub's page);
- `/novnc/core/…`, `/novnc/vendor/…`: noVNC's core, which /vnc.html imports: the `core/` and
  `vendor/` folders and the licence files of the `@novnc/novnc` npm package;
- any other file: `<web root>/<path>` (favicons and the rest of Vite's `public/`).

The rules:
- **Files first, then the app.** A path that isn't a file gets `index.html`, and the app routes
  itself. A path whose last part has an extension (`/assets/x.js`, `/favicon.ico`) is a missing
  file instead: 404, never index.html, so a browser never gets HTML for a script.
- **/api/…** is never the app: an unknown API path gets the `not_found` envelope.
- **Nothing outside the web root:** no `..`, no hidden files (`.git`, `.env`), no symlink that leads
  out of the root.
- **Caching:** `assets/` holds only Vite's content-hashed output, so it's cached for a year as
  `immutable`. Everything else (index.html, vnc.html, noVNC's core, favicons) is `no-cache`: the
  browser keeps it but asks each time, and an unchanged file costs a 304 (by ETag).
- **Media types** come from MEDIA_TYPES, not the system's `/etc/mime.types`, which the image may
  lack: module scripts need `text/javascript`, and the fonts `font/woff2`.
- **No UI built yet:** `/` and the app routes show a short placeholder with links to /vnc.html and
  /api/health.
- File lookups run in a worker thread (design.md § Stack).
"""

import asyncio
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from spotivault.config import Config
from spotivault.errors import not_found

STATIC_DIR = Path(__file__).parent / "static"  # pages the controller ships itself: vnc.html

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
# On every page and file: no type sniffing, and no framing by another site's page.
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN"}

MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".webmanifest": "application/manifest+json",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".wasm": "application/wasm",
}
DEFAULT_MEDIA_TYPE = "application/octet-stream"

PLACEHOLDER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>spotivault</title></head>
<body style="background:#121212;color:#b3b3b3;font:16px system-ui,sans-serif;padding:2rem">
<p>spotivault's controller is running. The web UI isn't built into this image yet.</p>
<p>The Spotify client's screen is at <a href="/vnc.html" style="color:#1ed760">/vnc.html</a>,
and the container's health at <a href="/api/health" style="color:#1ed760">/api/health</a>.</p>
</body></html>
"""


@dataclass(frozen=True, slots=True)
class StaticFile:
    """A file to send, with what the lookup learnt about it."""

    path: Path
    stat: os.stat_result
    cache_control: str


def mount(app: FastAPI, config: Config) -> None:
    """Adds the catch-all route. It must be added after every API router."""
    router = APIRouter(include_in_schema=False)
    root = config.web_root

    @router.get("/{path:path}")
    async def spa(path: str, request: Request) -> Response:
        if path == "api" or path.startswith("api/"):
            raise not_found("No such endpoint.")
        parts = safe_parts(path)
        if parts is None:
            return _missing()
        file = await asyncio.to_thread(lookup, root, parts)
        if file is not None:
            return file_response(request, file)
        if has_extension(parts):
            return _missing()
        return HTMLResponse(PLACEHOLDER, headers={"Cache-Control": REVALIDATE, **SECURITY_HEADERS})

    app.include_router(router)


def safe_parts(url_path: str) -> tuple[str, ...] | None:
    """`url_path` split at "/", or None when it may not be served: a part that starts with "."
    (`..`, `.git`) or holds a backslash or a NUL."""
    parts = tuple(part for part in url_path.split("/") if part)
    if any(part.startswith(".") or "\\" in part or "\x00" in part for part in parts):
        return None
    return parts


def has_extension(parts: tuple[str, ...]) -> bool:
    """True when the last part names a file (`app.js`), not an app route (`library`)."""
    return bool(parts) and "." in parts[-1]


def lookup(root: Path, parts: tuple[str, ...]) -> StaticFile | None:
    """What to send for a path: its file under the web root, else the controller's own copy, else
    (for an app route) the web root's index.html. None when there's none. Blocking: run it in a
    worker thread."""
    file = _file_under(root, parts) or _file_under(STATIC_DIR, parts)
    if file is None and not has_extension(parts):
        file = _file_under(root, ("index.html",))
    return file


def file_response(request: Request, file: StaticFile) -> Response:
    """The file, or 304 when the browser's copy (If-None-Match) is current."""
    headers = {"Cache-Control": file.cache_control, **SECURITY_HEADERS}
    media_type = MEDIA_TYPES.get(file.path.suffix.lower(), DEFAULT_MEDIA_TYPE)
    response = FileResponse(
        file.path, stat_result=file.stat, media_type=media_type, headers=headers
    )
    etag = response.headers["etag"]
    if etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag, **headers})
    return response


def etag_matches(if_none_match: str | None, etag: str) -> bool:
    """True when an If-None-Match header names `etag` (weakly compared, as RFC 9110 says)."""
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    wanted = etag.removeprefix("W/")
    return any(tag.strip().removeprefix("W/") == wanted for tag in if_none_match.split(","))


def _file_under(base: Path, parts: tuple[str, ...]) -> StaticFile | None:
    try:
        root = base.resolve()
        candidate = root.joinpath(*parts).resolve()
        if not candidate.is_relative_to(root):
            return None  # a symlink that leads out of the root
        info = candidate.stat()
    except (OSError, ValueError, RuntimeError):  # missing, unreadable, too long, a symlink loop
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    hashed = len(parts) > 1 and parts[0] == "assets"
    return StaticFile(candidate, info, IMMUTABLE if hashed else REVALIDATE)


def _missing() -> Response:
    return PlainTextResponse(
        "Not found\n", status_code=404, headers={"Cache-Control": REVALIDATE, **SECURITY_HEADERS}
    )
