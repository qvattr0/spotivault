"""Web API connection endpoints (openapi.yaml tag `spotify`): wizard step 5, the banner, Settings.

Owner: S5. Not built yet: every endpoint answers 501.
"""

from fastapi import APIRouter

from spotivault.api.models import (
    AuthStart,
    Connection,
    Devices,
    FinishSpotifyAuthRequest,
    SetSpotifyAppRequest,
)
from spotivault.errors import not_built

router = APIRouter(tags=["spotify"])


@router.post("/api/spotify/app", operation_id="setSpotifyApp", response_model=Connection)
async def set_spotify_app(body: SetSpotifyAppRequest) -> Connection:
    raise not_built("setSpotifyApp")


@router.post("/api/spotify/auth/start", operation_id="startSpotifyAuth", response_model=AuthStart)
async def start_spotify_auth() -> AuthStart:
    raise not_built("startSpotifyAuth")


@router.post(
    "/api/spotify/auth/finish", operation_id="finishSpotifyAuth", response_model=Connection
)
async def finish_spotify_auth(body: FinishSpotifyAuthRequest) -> Connection:
    raise not_built("finishSpotifyAuth")


@router.get("/api/spotify/devices", operation_id="getSpotifyDevices", response_model=Devices)
async def get_spotify_devices() -> Devices:
    raise not_built("getSpotifyDevices")


@router.get(
    "/api/spotify/connection", operation_id="getSpotifyConnection", response_model=Connection
)
async def get_spotify_connection() -> Connection:
    raise not_built("getSpotifyConnection")


@router.delete(
    "/api/spotify/connection", operation_id="disconnectSpotify", response_model=Connection
)
async def disconnect_spotify() -> Connection:
    raise not_built("disconnectSpotify")
