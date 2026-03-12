"""
自定义异常和全局异常处理器
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from typing import Optional


class AppException(Exception):
    """应用基础异常"""
    def __init__(
        self,
        status_code: int = 400,
        message: str = "请求错误",
        detail: Optional[str] = None,
    ):
        self.status_code = status_code
        self.message = message
        self.detail = detail
        super().__init__(message)


class NotFoundException(AppException):
    def __init__(self, resource: str = "资源", resource_id: str = ""):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            message=f"{resource}不存在" + (f": {resource_id}" if resource_id else ""),
        )


class ForbiddenException(AppException):
    def __init__(self, message: str = "无权限访问"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, message=message)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "未认证，请先登录"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, message=message)


class ValidationException(AppException):
    def __init__(self, message: str = "数据验证失败", detail: Optional[str] = None):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, message=message, detail=detail)


class ConflictException(AppException):
    def __init__(self, message: str = "资源已存在"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, message=message)


class StorageException(AppException):
    def __init__(self, message: str = "文件存储失败"):
        super().__init__(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, message=message)


class LLMException(AppException):
    def __init__(self, message: str = "LLM调用失败", detail: Optional[str] = None):
        super().__init__(status_code=status.HTTP_502_BAD_GATEWAY, message=message, detail=detail)


class FileTooLargeException(AppException):
    def __init__(self, max_size_mb: int):
        super().__init__(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            message=f"文件超过最大上传限制 {max_size_mb}MB",
        )


class UnsupportedFileTypeException(AppException):
    def __init__(self, mime_type: str):
        super().__init__(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            message=f"不支持的文件类型: {mime_type}",
        )


def _error_response(status_code: int, message: str, detail: Optional[str] = None) -> JSONResponse:
    content = {"code": status_code, "message": message}
    if detail:
        content["detail"] = detail
    return JSONResponse(status_code=status_code, content=content)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return _error_response(exc.status_code, exc.message, exc.detail)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    messages = [f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}" for e in errors]
    return _error_response(422, "数据验证失败", "; ".join(messages))


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import logging
    logging.getLogger("app").exception("未处理的异常")
    return _error_response(500, "服务器内部错误")
