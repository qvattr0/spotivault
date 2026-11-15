"""Library endpoints (openapi.yaml tag `library`): playlists and Liked Songs.

Owner: S5. Not built yet: every endpoint answers 501.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from spotivault.api.models import (
    GetLibrarySuggestionsResponse,
    LibraryItem,
    LibrarySummary,
    ListLibraryResponse,
    PatchLibraryItemRequest,
    PlaylistPreview,
    TrackList,
    UrlBody,
)
from spotivault.api.params import IMAGE_RESPONSES, CoverSize, LibraryId
from spotivault.errors import not_built

router = APIRouter(tags=["library"])


@router.get("/api/library/summary", operation_id="getLibrarySummary", response_model=LibrarySummary)
async def get_library_summary() -> LibrarySummary:
    raise not_built("getLibrarySummary")


@router.get("/api/library", operation_id="listLibrary", response_model=ListLibraryResponse)
async def list_library(
    filter: Literal["all", "tracked", "not_tracked", "owned", "added"] = "all",
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Literal[
        "recently_backed_up", "name", "recently_added", "track_count"
    ] = "recently_backed_up",
) -> ListLibraryResponse:
    raise not_built("listLibrary")


@router.post(
    "/api/library", operation_id="addLibraryItem", response_model=LibraryItem, status_code=201
)
async def add_library_item(body: UrlBody) -> LibraryItem:
    raise not_built("addLibraryItem")


@router.get(
    "/api/library/suggestions",
    operation_id="getLibrarySuggestions",
    response_model=GetLibrarySuggestionsResponse,
)
async def get_library_suggestions(
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> GetLibrarySuggestionsResponse:
    raise not_built("getLibrarySuggestions")


@router.post(
    "/api/library/resolve", operation_id="resolveLibraryLink", response_model=PlaylistPreview
)
async def resolve_library_link(body: UrlBody) -> PlaylistPreview:
    raise not_built("resolveLibraryLink")


@router.patch("/api/library/{id}", operation_id="patchLibraryItem", response_model=LibraryItem)
async def patch_library_item(id: LibraryId, body: PatchLibraryItemRequest) -> LibraryItem:
    raise not_built("patchLibraryItem")


@router.delete(
    "/api/library/{id}", operation_id="removeLibraryItem", status_code=204, response_class=Response
)
async def remove_library_item(id: LibraryId) -> Response:
    raise not_built("removeLibraryItem")


@router.get(
    "/api/library/{id}/tracks", operation_id="getLibraryItemTracks", response_model=TrackList
)
async def get_library_item_tracks(id: LibraryId) -> TrackList:
    raise not_built("getLibraryItemTracks")


@router.get(
    "/api/library/{id}/cover",
    operation_id="getLibraryItemCover",
    response_class=Response,
    responses=IMAGE_RESPONSES,
)
async def get_library_item_cover(id: LibraryId, size: CoverSize = "thumb") -> Response:
    raise not_built("getLibraryItemCover")
