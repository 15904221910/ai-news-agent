"""统一业务异常 → HTTP 错误码映射。"""
from __future__ import annotations


class AppError(Exception):
    code = "INTERNAL"
    http_status = 500

    def __init__(
        self,
        message: str,
        code: str | None = None,
        http_status: int | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status
        self.details = details or {}

    def to_dict(self, request_id: str | None = None) -> dict:
        err: dict = {"code": self.code, "message": self.message}
        if self.details:
            err["details"] = self.details
        if request_id:
            err["request_id"] = request_id
        return {"error": err}


class ValidationAppError(AppError):
    code = "VALIDATION_ERROR"
    http_status = 400


class NotFoundAppError(AppError):
    code = "NOT_FOUND"
    http_status = 404


class ConflictAppError(AppError):
    code = "CONFLICT"
    http_status = 409


class LLMFailedAppError(AppError):
    code = "LLM_FAILED"
    http_status = 502
