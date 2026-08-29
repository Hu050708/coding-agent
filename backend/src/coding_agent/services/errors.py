"""定义应用服务抛出的、与传输协议无关的错误。"""

from __future__ import annotations


class ApplicationError(RuntimeError):
    """可跨越应用层到 HTTP 层边界的稳定错误。"""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        """创建可由传输层稳定映射的业务错误。

        :param status_code: 建议的 HTTP 状态码。
        :param code: 供前端判断的稳定错误码。
        :param message: 可安全展示给用户的说明。
        """

        super().__init__(message)
        # 分别保留传输状态、机器码和展示文本，避免路由解析异常字符串。
        self.status_code = status_code
        self.code = code
        self.message = message


__all__ = ["ApplicationError"]
