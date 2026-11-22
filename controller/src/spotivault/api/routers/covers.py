"""The cover images (openapi.yaml getLibraryItemCover, getAlbumCover): a playlist's or an album's
cover, `thumb` (300 px, the default) or `full`.

The service behind them is
`services.covers` (catalog/covers.py): `image(item_id, size)`, None → 404 `not_found` (Liked
Songs always). The answer is the stored bytes with their type, and Cache-Control
`private, max-age=86400`. Both live here, one owner for both, though their paths are under
/api/library and /api/albums.
"""

from typing import TYPE_CHECKING

from fastapi import APIRouter, Response

from spotivault.api.deps import ServicesDep
from spotivault.api.params import IMAGE_RESPONSES, AlbumId, CoverSize, LibraryId
from spotivault.errors import not_found

if TYPE_CHECKING:
    from spotivault.services import Services

router = APIRouter()

CACHE_CONTROL = "private, max-age=86400"


@router.get(
    "/api/library/{id}/cover",
    operation_id="getLibraryItemCover",
    response_class=Response,
    responses=IMAGE_RESPONSES,
    tags=["library"],
)
async def get_library_item_cover(
    id: LibraryId, services: ServicesDep, size: CoverSize = "thumb"
) -> Response:
    return await _cover(services, id, size)


@router.get(
    "/api/albums/{id}/cover",
    operation_id="getAlbumCover",
    response_class=Response,
    responses=IMAGE_RESPONSES,
    tags=["albums"],
)
async def get_album_cover(
    id: AlbumId, services: ServicesDep, size: CoverSize = "thumb"
) -> Response:
    return await _cover(services, id, size)


async def _cover(services: "Services", item_id: str, size: CoverSize) -> Response:
    image = await services.covers.image(item_id, size)
    if image is None:
        raise not_found("No cover for this item.")
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={"Cache-Control": CACHE_CONTROL},
    )
