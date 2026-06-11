from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def api_error(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> ApiError:
    return ApiError(status_code, code, message, details)


def error_body(error: ApiError) -> dict[str, Any]:
    return {"code": error.code, "message": error.message, "details": error.details}


def _json_safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    errors = []
    for error in exc.errors():
        safe_error = dict(error)
        if "ctx" in safe_error:
            safe_error["ctx"] = {key: str(value) for key, value in safe_error["ctx"].items()}
        errors.append(safe_error)
    return errors


async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_body(exc))


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed.",
            "details": {"errors": _json_safe_validation_errors(exc)},
        },
    )
