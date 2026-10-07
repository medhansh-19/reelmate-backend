from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


def _payload(
    request: Request,
    *,
    code: str,
    message: str,
    retryable: bool,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": getattr(request.state, "request_id", None),
        }
    }


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
        context: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.context = context or {}
        self.headers = headers


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content=_payload(
            request,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
        ),
    )


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    codes = {
        401: "AUTH_REQUIRED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        429: "RATE_LIMITED",
        503: "SERVICE_UNAVAILABLE",
    }
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content=_payload(
            request,
            code=codes.get(exc.status_code, "HTTP_ERROR"),
            message=message,
            retryable=exc.status_code in {429, 502, 503, 504},
        ),
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    del exc  # Validation details can contain filenames or other creator input.
    return JSONResponse(
        status_code=422,
        content=_payload(
            request,
            code="VALIDATION_ERROR",
            message="The request did not match the API contract.",
            retryable=False,
        ),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled API error request_id=%s",
        getattr(request.state, "request_id", None),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content=_payload(
            request,
            code="INTERNAL_ERROR",
            message="The server could not complete the request.",
            retryable=True,
        ),
    )
