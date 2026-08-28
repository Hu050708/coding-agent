"""定义应用服务抛出的、与传输协议无关的错误。"""

from __future__ import annotations


class ApplicationError(RuntimeError):
    """可跨越应用层到 HTTP 层边界的稳定错误。"""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


__all__ = ["ApplicationError"]
