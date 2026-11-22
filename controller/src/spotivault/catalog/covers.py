"""Cover thumbnails for playlists and albums, and the images the cover endpoints serve.

Owner: albums-covers. Built by services.py as `services.covers`. Specs: design.md § Playlist
covers (Thumbnails) and § Spotify's image CDN; web-ui.md § Library endpoints and § Album
endpoints; openapi.yaml getLibraryItemCover, getAlbumCover. Cover FILES next to the .m3u, custom
covers and the "Save Spotify's covers" setting are deferred (Q14, Q15): only the cache here.

Frozen for other modules: `CoverUpdate`, `update()` and `cover_url()` (written already).

**`update(item_id, images)`**, called by the catalog refresh (playlists) and by adding albums,
right after the listing that returned `images` (their URLs expire within a day: use them at once,
never store them):
1. **The image ID** (`image_id_of`), from the URL (design.md § Spotify's image CDN): for
   `…/image/<kind 8 hex>0000<size 4 hex><id 24 hex>` it's the 24-hex id; for
   `mosaic.scdn.co/<size>/<ids>` it's `<ids>`; for any other shape the URL's last path segment.
   It goes into file names and the cover URL's `v=`, so only letters and digits are accepted
   (IMAGE_ID): any other shape is `failed`, with nothing downloaded. Unchanged from
   `items.image_id` with both files still in the cache: nothing is downloaded (`unchanged`).
2. **The thumbnail (300 px):** the listed image whose width is 300 (albums list 640, 300 and 64);
   else the URL rewritten to its 300 px size (an uploaded cover's size code → `da84`, album art's
   → `1e02`, a mosaic's `/<size>/` → `/300/`), falling back to the URL as listed when that answers
   ImageNotFound; else the URL as listed. Saved as returned: no resizing (no image library).
3. **The full image:** the largest listed image (640 px for albums, "as the Web API gives it"),
   as listed.
4. **Downloads** go through `services.ports.cdn` only (ImageRefused, ImageNotFound,
   ImageFetchFailed are its errors; fake mode and tests never reach the network). The files go to
   `config.covers_cache_dir` (/config/cache/covers/) as `<item_id>-<image_id>-thumb.<jpg|png>` and
   `-full.<jpg|png>`, written with `asyncio.to_thread` (write a temporary file, then rename), and
   the old ones are deleted.
5. **The row:** `items.image_id`, `thumb_path`, `full_path` (file names, not paths), and
   `cover_source` 'spotify'. No images listed: `cover_source` 'none', paths NULL (`none`).
   A failed download keeps what was cached before and logs a warning (`failed`). A thumbnail
   that fell back to the size returned counts as `fallback` (the refresh's "1 at the size
   returned"). Liked Songs is never passed here.

**`image(item_id, size)`**, for GET /api/library/{id}/cover and GET /api/albums/{id}/cover
(api/routers/covers.py): the cached file's bytes and type, read with `asyncio.to_thread`; None
(the router answers 404) for Liked Songs, an unknown item, or nothing cached. `full` falls back
to the thumbnail when only that is cached. The router answers with Cache-Control
`private, max-age=86400`: the URL changes (`v=<image_id>`) when the cover does.
"""

import asyncio
import logging
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from spotivault.ports import (
    FetchedImage,
    Image,
    ImageError,
    ImageFetchFailed,
    ImageNotFound,
    spotify_image_url_allowed,
)

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

THUMB_EDGE = 300

type CoverOutcome = Literal["unchanged", "saved", "fallback", "none", "failed"]
type CoverSize = Literal["thumb", "full"]

# The two kinds of Spotify image that have size codes (design.md § Spotify's image CDN):
# an uploaded playlist cover (`ab67706c`) and album art (`ab67616d`).
UPLOADED_KIND = "ab67706c"
ALBUM_ART_KIND = "ab67616d"
_CODED_URL = re.compile(
    r"^(?P<head>https://[^/]+/image/)(?P<kind>[0-9a-f]{8})0000(?P<size>[0-9a-f]{4})"
    r"(?P<id>[0-9a-f]{24})$"
)
_MOSAIC_URL = re.compile(
    r"^(?P<head>https://mosaic\.scdn\.co/)(?P<size>\d+)/(?P<ids>[0-9A-Za-z]{1,200})$"
)
# What an image ID may be: it's part of a cache file name and of a URL.
IMAGE_ID = re.compile(r"[0-9A-Za-z]{1,200}")


@dataclass(frozen=True, slots=True)
class CoverUpdate:
    """What `update` did. The refresh counts `saved` and `fallback` for its summary line."""

    outcome: CoverOutcome
    image_id: str | None  # the cover's image ID now, or None without a cover


@dataclass(frozen=True, slots=True)
class CoverImage:
    """A cached cover, for the cover endpoints."""

    content_type: Literal["image/jpeg", "image/png"]
    data: bytes = field(repr=False)


def cover_url(
    path_kind: Literal["library", "albums"],
    item_id: str,
    thumb_path: str | None,
    image_id: str | None,
) -> str | None:
    """The thumbnail URL the API hands out (LibraryItem.cover, Album.cover, QueueItem.cover):
    `/api/library/<id>/cover?size=thumb&v=<image_id>`, or None while no thumbnail is cached.
    `v` changes with the cover, so a browser never shows an old one from its cache. Frozen."""
    if thumb_path is None:
        return None
    url = f"/api/{path_kind}/{item_id}/cover?size=thumb"
    if image_id:
        url += f"&v={image_id}"
    return url


def image_id_of(url: str) -> str | None:
    """The CDN image ID of a cover URL (see the module docstring, step 1). The same for every
    size of one image, so it's what a change of cover shows. None when it isn't plain letters
    and digits: it's never used as a file name then."""
    coded = _CODED_URL.match(url)
    if coded is not None:
        return coded.group("id")
    mosaic = _MOSAIC_URL.match(url)
    if mosaic is not None:
        return mosaic.group("ids")
    last = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    return last if IMAGE_ID.fullmatch(last) else None


def _sized(url: str, *, thumb: bool) -> str | None:
    """The URL at the thumbnail size (300 px) or the full size, or None when this kind of URL has
    no such size rule and is downloaded as listed. design.md § Spotify's image CDN, "Rewriting":
    uploaded covers go to `bebb` (640) for the full size and `da84` (300) for the thumbnail,
    mosaics to `/1280/` and `/300/`, album art to `1e02` (300) for the thumbnail only: its full
    size is the 640 px the Web API gives (web-ui.md § Album endpoints)."""
    coded = _CODED_URL.match(url)
    if coded is not None:
        kind = coded.group("kind")
        if kind == UPLOADED_KIND:
            code = "da84" if thumb else "bebb"
        elif kind == ALBUM_ART_KIND and thumb:
            code = "1e02"
        else:
            return None
        return f"{coded.group('head')}{kind}0000{code}{coded.group('id')}"
    mosaic = _MOSAIC_URL.match(url)
    if mosaic is not None:
        edge = THUMB_EDGE if thumb else 1280
        return f"{mosaic.group('head')}{edge}/{mosaic.group('ids')}"
    return None


def listed_thumbnail(images: Sequence[Image]) -> Image | None:
    """The listed image nearest 300 px wide (the one whose width is 300, when there is one). Its
    URL as listed: the listings' 300 px image, used without a rewrite (saved Albums' `cover`)."""
    if not images:
        return None
    return min(
        images,
        key=lambda image: abs(image.width - THUMB_EDGE) if image.width is not None else 10**9,
    )


def thumbnail_url(images: Sequence[Image]) -> tuple[str, str | None] | None:
    """(the URL to try first for the 300 px thumbnail, the URL as listed to fall back to, or
    None when there's nothing to fall back to), or None without images. See step 2."""
    if not images:
        return None
    for image in images:
        if image.width == THUMB_EDGE:
            return image.url, None
    listed = listed_thumbnail(images)
    assert listed is not None  # images isn't empty
    rewritten = _sized(listed.url, thumb=True)
    if rewritten is None or rewritten == listed.url:
        return listed.url, None
    return rewritten, listed.url


def full_url(images: Sequence[Image]) -> tuple[str, str | None] | None:
    """(the URL to try for the full image, the largest listed URL as the fallback, or None when
    there's nothing to fall back to), or None without images. Step 3: the largest listed image,
    rewritten to the largest size the CDN has for uploaded covers and mosaics (design.md)."""
    if not images:
        return None
    largest = max(images, key=lambda image: image.width or 0)
    rewritten = _sized(largest.url, thumb=False)
    if rewritten is None or rewritten == largest.url:
        return largest.url, None
    return rewritten, largest.url


class CoverService:
    """Cover thumbnails. See the module docstring."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        self.cache_dir = services.config.covers_cache_dir
        # Serializes the file writes and the row updates of two covers that land at once.
        self._lock = asyncio.Lock()

    async def update(self, item_id: str, images: Sequence[Image]) -> CoverUpdate:
        """Caches the item's cover if its image ID changed. Never raises for a CDN problem: it's
        `failed`, logged. The item's row must exist."""
        row = await self._row(item_id)
        if not images:
            # No cover: the files go, and the row says so.
            async with self._lock:
                await self._save_row(item_id, None, None, None, source="none")
                await self._remove_files([row.thumb_path, row.full_path], keep=())
            return CoverUpdate("none", None)

        full_pair = full_url(images)
        thumb_pair = thumbnail_url(images)
        assert full_pair is not None and thumb_pair is not None  # images isn't empty
        full_try, full_fallback = full_pair
        thumb_try, thumb_fallback = thumb_pair
        image_id = image_id_of(full_try)
        if image_id is None:
            log.warning("cover for %s: not a Spotify image URL shape, not downloaded", item_id)
            return CoverUpdate("failed", row.image_id)
        if row.image_id == image_id and await self._both_cached(row):
            return CoverUpdate("unchanged", image_id)

        thumb = await self._fetch(item_id, "thumbnail", thumb_try, thumb_fallback)
        if thumb is None:
            # Nothing new was saved: the cover that was cached stays.
            return CoverUpdate("failed", row.image_id)
        if full_try == thumb.url:
            full: _Fetched | None = thumb  # the same file serves both sizes: one download
        else:
            full = await self._fetch(item_id, "full", full_try, full_fallback)

        thumb_name = _file_name(item_id, image_id, "thumb", thumb.image)
        full_name = _file_name(item_id, image_id, "full", full.image) if full is not None else None
        async with self._lock:
            await asyncio.to_thread(self._write, thumb_name, thumb.image.data)
            if full is not None and full_name is not None:
                await asyncio.to_thread(self._write, full_name, full.image.data)
            await self._save_row(item_id, image_id, thumb_name, full_name, source="spotify")
            # The old files go after the row points at the new ones.
            await self._remove_files([row.thumb_path, row.full_path], keep=(thumb_name, full_name))
        return CoverUpdate("fallback" if thumb.fallback else "saved", image_id)

    async def image(self, item_id: str, size: CoverSize) -> CoverImage | None:
        """The cached file for the endpoints. None (404) for an unknown item, Liked Songs, or
        nothing cached. `full` falls back to the thumbnail when only that is cached."""
        row = await self.services.store.fetchone(
            "SELECT thumb_path, full_path FROM items WHERE id = ?", (item_id,)
        )
        if row is None:
            return None
        name = row["thumb_path"] if size == "thumb" else (row["full_path"] or row["thumb_path"])
        if name is None:
            return None
        data = await asyncio.to_thread(self._read, name)
        if data is None:
            return None
        content_type: Literal["image/jpeg", "image/png"] = (
            "image/png" if name.endswith(".png") else "image/jpeg"
        )
        return CoverImage(content_type=content_type, data=data)

    # --- Downloads -------------------------------------------------------------------------------

    async def _fetch(
        self, item_id: str, what: str, first: str, fallback: str | None
    ) -> "_Fetched | None":
        """Downloads `first` through the image port. A 404 or a failed download (not a JPEG, a
        timeout) tries `fallback`, the URL as listed, if there is one: that's a saved image at the
        size returned, logged. None when neither works (or the host isn't Spotify's)."""
        if not spotify_image_url_allowed(first):
            log.warning("cover %s for %s: not a Spotify image URL, not downloaded", what, item_id)
            return None
        cdn = self.services.ports.cdn
        try:
            return _Fetched(await cdn.fetch(first), first, fallback=False)
        except (ImageNotFound, ImageFetchFailed) as exc:
            if fallback is None:
                log.warning("cover %s for %s: not saved (%s)", what, item_id, exc)
                return None
            log.warning(
                "cover %s for %s: the larger size isn't there, saved as returned", what, item_id
            )
        except ImageError as exc:
            log.warning("cover %s for %s: not saved (%s)", what, item_id, exc)
            return None
        if not spotify_image_url_allowed(fallback):
            return None
        try:
            return _Fetched(await cdn.fetch(fallback), fallback, fallback=True)
        except ImageError as exc:
            log.warning("cover %s for %s: not saved (%s)", what, item_id, exc)
            return None

    # --- Files and rows --------------------------------------------------------------------------

    def _write(self, name: str, data: bytes) -> None:
        """Writes a cache file whole: a temporary file, then renamed over the name (blocking; call
        through asyncio.to_thread)."""
        if not _plain_name(name):
            raise ValueError(f"not a cover file name: {name!r}")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / name
        tmp = self.cache_dir / (name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def _read(self, name: str) -> bytes | None:
        if not _plain_name(name):
            return None
        try:
            return (self.cache_dir / name).read_bytes()
        except FileNotFoundError:
            return None

    def _all_exist(self, names: Iterable[str]) -> bool:
        return all(_plain_name(name) and (self.cache_dir / name).is_file() for name in names)

    async def _both_cached(self, row: "_Row") -> bool:
        """Both files of the cover are still in the cache (blocking check, in a thread)."""
        if row.thumb_path is None or row.full_path is None:
            return False
        return await asyncio.to_thread(self._all_exist, [row.thumb_path, row.full_path])

    async def _remove_files(
        self, names: Iterable[str | None], *, keep: Iterable[str | None]
    ) -> None:
        """Deletes cache files no row points at any more (blocking; in a thread)."""
        kept = {name for name in keep if name is not None}
        doomed = [name for name in names if name is not None and name not in kept]
        await asyncio.to_thread(self._unlink, doomed)

    def _unlink(self, names: list[str]) -> None:
        for name in names:
            if not _plain_name(name):
                continue  # never anything outside the cache
            try:
                (self.cache_dir / name).unlink()
            except FileNotFoundError:
                pass

    async def _row(self, item_id: str) -> "_Row":
        row = await self.services.store.fetchone(
            "SELECT image_id, thumb_path, full_path FROM items WHERE id = ?", (item_id,)
        )
        if row is None:
            raise LookupError(f"no item {item_id} to save a cover for")
        return _Row(row["image_id"], row["thumb_path"], row["full_path"])

    async def _save_row(
        self,
        item_id: str,
        image_id: str | None,
        thumb_path: str | None,
        full_path: str | None,
        *,
        source: Literal["spotify", "none"],
    ) -> None:
        await self.services.store.execute(
            "UPDATE items SET image_id = ?, thumb_path = ?, full_path = ?, cover_source = ? "
            "WHERE id = ?",
            (image_id, thumb_path, full_path, source, item_id),
        )


@dataclass(frozen=True, slots=True)
class _Row:
    """The cover columns of an items row."""

    image_id: str | None
    thumb_path: str | None
    full_path: str | None


@dataclass(frozen=True, slots=True)
class _Fetched:
    """A downloaded image, the URL it came from, and whether that was the fallback."""

    image: FetchedImage = field(repr=False)
    url: str
    fallback: bool


def _plain_name(name: str) -> bool:
    """A file name right inside the cache folder: no folder part, and not `.` or `..`."""
    return name not in ("", ".", "..") and PurePath(name).name == name and "\\" not in name


def _file_name(item_id: str, image_id: str, kind: str, image: FetchedImage) -> str:
    """`<item_id>-<image_id>-<thumb|full>.<jpg|png>`, under the covers cache."""
    ext = "jpg" if image.content_type == "image/jpeg" else "png"
    return f"{item_id}-{image_id}-{kind}.{ext}"
