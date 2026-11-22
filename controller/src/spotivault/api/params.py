"""Path and query parameters shared by several routers, as openapi.yaml `components.parameters`."""

from typing import Annotated, Literal

from fastapi import Path, Query

LIBRARY_ID_PATTERN = r"^(liked|[0-9A-Za-z]{22})$"
SPOTIFY_ID_PATTERN = r"^[0-9A-Za-z]{22}$"

# A Spotify playlist id, or `liked` for Liked Songs.
LibraryId = Annotated[str, Path(pattern=LIBRARY_ID_PATTERN)]
# A Spotify album id.
AlbumId = Annotated[str, Path(pattern=SPOTIFY_ID_PATTERN)]
# A Library item id or an album id, as in a run's queue.
ItemId = Annotated[str, Path(pattern=LIBRARY_ID_PATTERN)]
# A run id from History.
RunId = Annotated[int, Path(ge=1)]
# `thumb` (300 px, the default) or `full`.
CoverSize = Annotated[Literal["thumb", "full"], Query()]

# Cover endpoints answer with the image itself.
IMAGE_RESPONSES: dict[int | str, dict] = {
    200: {"content": {"image/jpeg": {}, "image/png": {}}, "description": "The image, as stored."}
}
