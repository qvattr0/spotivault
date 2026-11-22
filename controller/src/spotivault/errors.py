"""The API's error envelope, `{"error": {"code", "message", "details"}}` (openapi.yaml `Error`).

Every 4xx and 5xx body has this shape, and the UI words its message by `code`. Routers raise
ApiError (or let a port's error through), and the handlers below turn it into the envelope:

    raise ApiError(409, "run_active", "Not available while a backup is recording.")
    raise not_found()
    raise not_built("getBacklog")      # 501 for an endpoint a later step builds

`code` must be one of the contract's ErrorCode values: the body is built with the generated
`ErrorError` model, so a wrong code fails loudly in tests instead of reaching the UI.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from spotivault.api.models import Error, ErrorError
from spotivault.ports import (
    ConnectionExpired,
    NotConnected,
    NotFound,
    RateLimited,
    SpotifyUnavailable,
    TokenExchangeFailed,
    WebApiError,
)
from spotivault.store import StoreUnavailable

log = logging.getLogger(__name__)


class ApiError(Exception):
    """An error answer: its HTTP status, the contract's error code, an English message for the
    log, and optional facts (`field`, `reason`, `ids`, `retry_after_s`, …)."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """The envelope as JSON values. A code that isn't in the contract raises ValidationError."""
    envelope = Error(error=ErrorError(code=code, message=message, details=details))
    return envelope.model_dump(mode="json")


def error_response(error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        content=error_body(error.code, error.message, error.details),
        headers=error.headers,
    )


# --- Common errors --------------------------------------------------------------------------------


def not_found(message: str = "No such item.", details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(404, "not_found", message, details)


def run_active() -> ApiError:
    return ApiError(409, "run_active", "Not available while a backup is recording.")


def validation_failed(field: str, message: str) -> ApiError:
    return ApiError(422, "validation_failed", message, {"field": field})


def not_built(operation_id: str) -> ApiError:
    """501 for an endpoint in the contract that isn't built yet. The contract has no code for it,
    so it's `internal`, with `details.reason` "not_built" and the operation's id."""
    return ApiError(
        501,
        "internal",
        f"{operation_id} isn't built yet.",
        {"reason": "not_built", "operation": operation_id},
    )


# --- Handlers -------------------------------------------------------------------------------------


def install_error_handlers(app: FastAPI) -> None:
    """Makes every error answer an `Error` envelope."""
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(StoreUnavailable, _store_unavailable)
    app.add_exception_handler(WebApiError, _webapi_error)
    app.add_exception_handler(Exception, _unexpected)


async def _api_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return error_response(exc)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's request validation, as 422 `validation_failed` with `details.field`."""
    assert isinstance(exc, RequestValidationError)
    errors = exc.errors()
    first = errors[0] if errors else {}
    location = [str(part) for part in first.get("loc", ())]
    if location and location[0] in {"body", "query", "path", "header"}:
        location = location[1:]
    field = ".".join(location) or "body"
    message = f"{field}: {first.get('msg', 'invalid')}"
    return error_response(validation_failed(field, message))


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    """Starlette's own errors: an unknown path or method under /api."""
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code in (404, 405):
        return error_response(ApiError(exc.status_code, "not_found", "No such endpoint."))
    return error_response(ApiError(exc.status_code, "internal", str(exc.detail)))


async def _store_unavailable(request: Request, exc: Exception) -> JSONResponse:
    log.error("database unavailable: %s", exc)
    return error_response(ApiError(503, "internal", "The database can't be opened."))


async def _webapi_error(request: Request, exc: Exception) -> JSONResponse:
    """A Web API error a router didn't handle itself. NoAccess and NotFound are answers that
    routers usually handle (a 403 on /items is "no item access", not a failure)."""
    assert isinstance(exc, WebApiError)
    if isinstance(exc, NotConnected):
        error = ApiError(409, "not_connected", "Connect the Spotify Web API first.")
    elif isinstance(exc, ConnectionExpired):
        error = ApiError(409, "connection_expired", "The Spotify connection expired. Reconnect.")
    elif isinstance(exc, RateLimited):
        error = ApiError(
            503, "rate_limited", "Spotify asked us to wait.", {"retry_after_s": exc.retry_after_s}
        )
    elif isinstance(exc, TokenExchangeFailed):
        error = ApiError(422, "token_exchange_failed", "Spotify refused the authorization code.")
    elif isinstance(exc, NotFound):
        error = not_found("Spotify has no such item.")
    elif isinstance(exc, SpotifyUnavailable):
        error = ApiError(503, "spotify_unavailable", "Spotify didn't answer.")
    else:
        log.warning("unhandled Web API error: %s", exc)
        error = ApiError(503, "spotify_unavailable", str(exc))
    return error_response(error)


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return error_response(ApiError(500, "internal", "Something went wrong in the controller."))
