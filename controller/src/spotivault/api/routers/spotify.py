"""Web API connection endpoints (openapi.yaml tag `spotify`): wizard step 5, the banner, Settings.

The service behind it is
`services.connection` (connection.py).
"""

from fastapi import APIRouter

from spotivault.api.deps import ServicesDep
from spotivault.api.models import (
    AuthStart,
    Connection,
    Devices,
    FinishSpotifyAuthRequest,
    SetSpotifyAppRequest,
)

router = APIRouter(tags=["spotify"])


@router.post("/api/spotify/app", operation_id="setSpotifyApp", response_model=Connection)
async def set_spotify_app(body: SetSpotifyAppRequest, services: ServicesDep) -> Connection:
    """Stores the developer app's Client ID. A different one disconnects."""
    return await services.connection.set_client_id(body.client_id)


@router.post("/api/spotify/auth/start", operation_id="startSpotifyAuth", response_model=AuthStart)
async def start_spotify_auth(services: ServicesDep) -> AuthStart:
    """Returns Spotify's consent URL. The PKCE verifier stays on the server."""
    return await services.connection.start_auth()


@router.post(
    "/api/spotify/auth/finish", operation_id="finishSpotifyAuth", response_model=Connection
)
async def finish_spotify_auth(body: FinishSpotifyAuthRequest, services: ServicesDep) -> Connection:
    """Exchanges the code in the pasted callback address for tokens."""
    return await services.connection.finish_auth(body.redirect_url)


@router.get("/api/spotify/devices", operation_id="getSpotifyDevices", response_model=Devices)
async def get_spotify_devices(services: ServicesDep) -> Devices:
    """Connect devices, and whether the container's client is one of them."""
    return await services.connection.devices()


@router.get(
    "/api/spotify/connection", operation_id="getSpotifyConnection", response_model=Connection
)
async def get_spotify_connection(services: ServicesDep) -> Connection:
    return await services.connection.connection()


@router.delete(
    "/api/spotify/connection", operation_id="disconnectSpotify", response_model=Connection
)
async def disconnect_spotify(services: ServicesDep) -> Connection:
    return await services.connection.disconnect()
