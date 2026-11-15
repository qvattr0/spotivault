"""Album endpoints (openapi.yaml tag `albums`): albums added for recording.

Owner: S5. Not built yet: every endpoint answers 501.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Body, Query, Response

from spotivault.api.models import (
    AddAlbumsRequestAddAlbumsRequest,
    AddAlbumsRequestAddAlbumsRequest1,
    AddAlbumsResponse,
    GetSavedAlbumsResponse,
    ListAlbumsResponse,
    TrackList,
)
from spotivault.api.params import IMAGE_RESPONSES, AlbumId, CoverSize
from spotivault.errors import not_built

router = APIRouter(tags=["albums"])

# `{ids: [...]}` or `{all: true}` (the generated AddAlbumsRequest alias, spelled out for FastAPI).
AddAlbumsBody = Annotated[
    AddAlbumsRequestAddAlbumsRequest | AddAlbumsRequestAddAlbumsRequest1, Body()
]


@router.get("/api/albums", operation_id="listAlbums", response_model=ListAlbumsResponse)
async def list_albums(
    filter: Literal["all", "recorded", "queued", "partial"] = "all",
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Literal["recently_added", "album", "artist", "year"] = "recently_added",
) -> ListAlbumsResponse:
    raise not_built("listAlbums")


@router.post("/api/albums", operation_id="addAlbums", response_model=AddAlbumsResponse)
async def add_albums(body: AddAlbumsBody) -> AddAlbumsResponse:
    raise not_built("addAlbums")


@router.get(
    "/api/albums/saved", operation_id="getSavedAlbums", response_model=GetSavedAlbumsResponse
)
async def get_saved_albums() -> GetSavedAlbumsResponse:
    raise not_built("getSavedAlbums")


@router.delete(
    "/api/albums/{id}", operation_id="removeAlbum", status_code=204, response_class=Response
)
async def remove_album(id: AlbumId) -> Response:
    raise not_built("removeAlbum")


@router.get("/api/albums/{id}/tracks", operation_id="getAlbumTracks", response_model=TrackList)
async def get_album_tracks(id: AlbumId) -> TrackList:
    raise not_built("getAlbumTracks")


@router.get(
    "/api/albums/{id}/cover",
    operation_id="getAlbumCover",
    response_class=Response,
    responses=IMAGE_RESPONSES,
)
async def get_album_cover(id: AlbumId, size: CoverSize = "thumb") -> Response:
    raise not_built("getAlbumCover")
