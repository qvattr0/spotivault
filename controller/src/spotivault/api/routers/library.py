"""Library endpoints (openapi.yaml tag `library`): playlists and Liked Songs.

The service behind them is
`services.library` (catalog/library.py), where the rules are. The cover endpoint is in covers.py
(albums-covers).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from spotivault.api.deps import ServicesDep
from spotivault.api.models import (
    GetLibrarySuggestionsResponse,
    LibraryItem,
    LibraryRefresh,
    LibrarySummary,
    ListLibraryResponse,
    PatchLibraryItemRequest,
    PlaylistPreview,
    TrackList,
    UrlBody,
)
from spotivault.api.params import LibraryId

router = APIRouter(tags=["library"])


@router.get("/api/library/summary", operation_id="getLibrarySummary", response_model=LibrarySummary)
async def get_library_summary(services: ServicesDep) -> LibrarySummary:
    return await services.library.summary()


@router.get("/api/library", operation_id="listLibrary", response_model=ListLibraryResponse)
async def list_library(
    services: ServicesDep,
    filter: Literal["all", "tracked", "not_tracked", "owned", "added"] = "all",
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Literal[
        "recently_backed_up", "name", "recently_added", "track_count"
    ] = "recently_backed_up",
) -> ListLibraryResponse:
    items = await services.library.list_items(filter=filter, q=q, sort=sort)
    return ListLibraryResponse(items=items)


@router.post(
    "/api/library",
    operation_id="addLibraryItem",
    response_model=LibraryItem,
    status_code=201,
    responses={
        409: {"description": "`already_added`, `not_connected` or `connection_expired`."},
        422: {"description": "The link can't be used."},
        503: {"description": "`rate_limited` or `spotify_unavailable`."},
    },
)
async def add_library_item(body: UrlBody, services: ServicesDep) -> LibraryItem:
    """A followed or linked playlist, by link. It comes in tracked."""
    return await services.library.add(body.url)


@router.get(
    "/api/library/suggestions",
    operation_id="getLibrarySuggestions",
    response_model=GetLibrarySuggestionsResponse,
)
async def get_library_suggestions(
    services: ServicesDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> GetLibrarySuggestionsResponse:
    return GetLibrarySuggestionsResponse(items=await services.library.suggestions(q))


@router.post(
    "/api/library/resolve",
    operation_id="resolveLibraryLink",
    response_model=PlaylistPreview,
    responses={
        409: {"description": "`not_connected` or `connection_expired`."},
        422: {"description": "The link can't be used."},
        503: {"description": "`rate_limited` or `spotify_unavailable`."},
    },
)
async def resolve_library_link(body: UrlBody, services: ServicesDep) -> PlaylistPreview:
    return await services.library.resolve(body.url)


@router.post(
    "/api/library/refresh",
    operation_id="refreshLibrary",
    response_model=LibraryRefresh,
    status_code=202,
    responses={
        409: {"description": "`run_active`, `not_connected` or `connection_expired`."},
    },
)
async def refresh_library(services: ServicesDep) -> LibraryRefresh:
    """The Refresh button: a catalog refresh now, unthrottled. Answers before it runs; a press
    while one runs joins it. Its `catalog.refresh` events say how it went."""
    return await services.catalog.request_manual()


@router.patch("/api/library/{id}", operation_id="patchLibraryItem", response_model=LibraryItem)
async def patch_library_item(
    id: LibraryId, body: PatchLibraryItemRequest, services: ServicesDep
) -> LibraryItem:
    return await services.library.set_tracked(id, body.tracked)


@router.delete(
    "/api/library/{id}", operation_id="removeLibraryItem", status_code=204, response_class=Response
)
async def remove_library_item(id: LibraryId, services: ServicesDep) -> Response:
    """Followed and linked items only. Files and History are kept."""
    await services.library.remove(id)
    return Response(status_code=204)


@router.get(
    "/api/library/{id}/tracks", operation_id="getLibraryItemTracks", response_model=TrackList
)
async def get_library_item_tracks(id: LibraryId, services: ServicesDep) -> TrackList:
    return await services.library.tracks(id)
