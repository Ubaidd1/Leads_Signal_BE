import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"
    message = "The request could not be processed."

    def __init__(self, message: str | None = None, *, code: str | None = None, details: Any = None):
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        super().__init__(self.message)


class NotAuthenticated(AppError):
    status_code = 401
    code = "NOT_AUTHENTICATED"
    message = "Authentication is required."


class PermissionDenied(AppError):
    status_code = 403
    code = "PERMISSION_DENIED"
    message = "You do not have permission to perform this action."


class NotFound(AppError):
    status_code = 404
    code = "RESOURCE_NOT_FOUND"
    message = "The requested resource was not found."


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"
    message = "The request conflicts with the current state of the resource."


class ValidationFailed(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "The request contains invalid data."


class RateLimited(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    message = "Too many attempts. Please wait and try again."

    def __init__(self, retry_after: int, **kwargs):
        self.retry_after = retry_after
        super().__init__(**kwargs)


_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "NOT_AUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "RESOURCE_NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


def error_body(code: str, message: str, details: Any = None) -> dict:
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError):
        headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimited) else None
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(part) for part in err["loc"] if part not in ("body", "query", "path")), "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(error_body("VALIDATION_ERROR", "The request contains invalid data.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_request: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "The request could not be processed."
        return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception):
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(error_body("INTERNAL_ERROR", "An unexpected error occurred."), status_code=500)
