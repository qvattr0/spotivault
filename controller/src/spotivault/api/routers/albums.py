"""Album endpoints (openapi.yaml tag `albums`): albums added for recording.

The service behind them is
`services.albums` (catalog/albums.py). The cover endpoint is in covers.py.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Body, Query, Response

from spotivault.api.deps import ServicesDep
from spotivault.api.models import (
    AddAlbumsRequestAddAlbumsRequest,
    AddAlbumsRequestAddAlbumsRequest1,
    AddAlbumsResponse,
    GetSavedAlbumsResponse,
    ListAlbumsResponse,
    TrackList,
)
from spotivault.api.params import AlbumId

router = APIRouter(tags=["albums"])

# `{ids: [...]}` or `{all: true}` (the generated AddAlbumsRequest alias, spelled out for FastAPI).
AddAlbumsBody = Annotated[
    AddAlbumsRequestAddAlbumsRequest | AddAlbumsRequestAddAlbumsRequest1, Body()
]


@router.get("/api/albums", operation_id="listAlbums", response_model=ListAlbumsResponse)
async def list_albums(
    services: ServicesDep,
    filter: Literal["all", "recorded", "queued", "partial"] = "all",
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Literal["recently_added", "album", "artist", "year"] = "recently_added",
) -> ListAlbumsResponse:
    return await services.albums.list_albums(filter=filter, q=q, sort=sort)


@router.post("/api/albums", operation_id="addAlbums", response_model=AddAlbumsResponse)
async def add_albums(body: AddAlbumsBody, services: ServicesDep) -> AddAlbumsResponse:
    if isinstance(body, AddAlbumsRequestAddAlbumsRequest1):
        return await services.albums.add(all_saved=True)
    return await services.albums.add(ids=body.ids)


@router.get(
    "/api/albums/saved", operation_id="getSavedAlbums", response_model=GetSavedAlbumsResponse
)
async def get_saved_albums(services: ServicesDep) -> GetSavedAlbumsResponse:
    return await services.albums.saved()


@router.delete(
    "/api/albums/{id}", operation_id="removeAlbum", status_code=204, response_class=Response
)
async def remove_album(id: AlbumId, services: ServicesDep) -> Response:
    await services.albums.remove(id)
    return Response(status_code=204)


@router.get("/api/albums/{id}/tracks", operation_id="getAlbumTracks", response_model=TrackList)
async def get_album_tracks(id: AlbumId, services: ServicesDep) -> TrackList:
    return await services.albums.tracks(id)
