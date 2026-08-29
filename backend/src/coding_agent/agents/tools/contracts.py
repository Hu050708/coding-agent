"""提供工具参数共用的校验函数和结构化错误。"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

from coding_agent.agents.security import ToolApprovalRequest


class ToolError(Exception):
    """跨工具注册表边界返回的结构化失败。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        data: Mapping[str, Any] | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        """创建可跨工具注册表边界安全序列化的领域错误。

        :param code: 稳定且机器可读的工具错误码。
        :param message: 可提供给模型的安全错误说明。
        :param retryable: 调整参数或稍后执行是否可能成功。
        :param data: 即使失败也允许返回的结构化业务数据。
        :param meta: 截断、计数等不属于业务数据的元信息。
        """

        super().__init__(message)
        # 供注册表序列化的稳定错误码。
        self.code = code
        # 不应包含凭据或完整文件/命令内容的安全错误文本。
        self.message = message
        # 告知模型是否值得改变条件后重试。
        self.retryable = retryable
        # 可选失败业务数据的防御性副本。
        self.data = dict(data) if data is not None else None
        # 可选失败元数据的防御性副本。
        self.meta = dict(meta) if meta is not None else None


ToolConfirmation = Callable[[ToolApprovalRequest], bool]
CancellationCheck = Callable[[], bool]


def reject_unknown(arguments: Mapping[str, Any], allowed: set[str]) -> None:
    """拒绝工具 Schema 未声明的额外参数。

    :param arguments: 模型提供的已解析工具参数。
    :param allowed: 当前工具允许出现的参数名集合。
    :raises ToolError: 参数映射包含未知键。
    """

    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ToolError("unknown_argument", f"Unknown argument(s): {', '.join(unknown)}.")


def require_string(
    arguments: Mapping[str, Any],
    name: str,
    *,
    allow_empty: bool = False,
    max_length: int = 4096,
) -> str:
    """读取并校验一个必需字符串参数。

    :param arguments: 工具参数映射。
    :param name: 要读取的参数名称。
    :param allow_empty: 是否接受空字符串。
    :param max_length: 字符串允许包含的最大字符数。
    :return: 通过类型和长度检查的字符串。
    :raises ToolError: 参数缺失、类型错误、为空或过长。
    """

    value = arguments.get(name)
    if not isinstance(value, str):
        raise ToolError("invalid_argument", f"{name} must be a string.")
    if not allow_empty and not value:
        raise ToolError("invalid_argument", f"{name} may not be empty.")
    if len(value) > max_length:
        raise ToolError("argument_too_large", f"{name} is too long.")
    return value


def optional_string(
    arguments: Mapping[str, Any], name: str, *, default: str | None = None, max_length: int = 4096
) -> str | None:
    """读取并校验一个可选字符串参数。

    :param arguments: 工具参数映射。
    :param name: 要读取的参数名称。
    :param default: 参数缺失或显式为 ``None`` 时使用的值。
    :param max_length: 非空字符串允许包含的最大字符数。
    :return: 合法字符串或默认值。
    :raises ToolError: 已提供的参数不是非空字符串或长度超限。
    """

    if name not in arguments:
        return default
    value = arguments[name]
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ToolError("invalid_argument", f"{name} must be a non-empty string.")
    if len(value) > max_length:
        raise ToolError("argument_too_large", f"{name} is too long.")
    return value


def optional_boolean(
    arguments: Mapping[str, Any], name: str, *, default: bool
) -> bool:
    """读取一个可选布尔参数。

    :param arguments: 工具参数映射。
    :param name: 参数名称。
    :param default: 参数缺失时使用的布尔值。
    :return: 默认值或通过严格类型校验的布尔值。
    :raises ToolError: 已提供的值不是布尔类型。
    """

    if name not in arguments:
        return default
    value = arguments[name]
    if not isinstance(value, bool):
        raise ToolError("invalid_argument", f"{name} must be a boolean.")
    return value


def optional_integer(
    arguments: Mapping[str, Any],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """读取一个带闭区间限制的可选整数参数。

    :param arguments: 工具参数映射。
    :param name: 要读取的参数名称。
    :param default: 参数缺失时使用的整数。
    :param minimum: 允许的最小值，包含边界。
    :param maximum: 允许的最大值，包含边界。
    :return: 默认值或通过校验的整数。
    :raises ToolError: 值不是整数或落在区间之外。
    """

    if name not in arguments:
        return default
    value = arguments[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("invalid_argument", f"{name} must be an integer.")
    if value < minimum or value > maximum:
        raise ToolError("invalid_argument", f"{name} must be between {minimum} and {maximum}.")
    return value


def optional_number(
    arguments: Mapping[str, Any],
    name: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    """读取一个带闭区间限制的可选有限数值参数。

    :param arguments: 工具参数映射。
    :param name: 要读取的参数名称。
    :param default: 参数缺失时使用的数值。
    :param minimum: 允许的最小值，包含边界。
    :param maximum: 允许的最大值，包含边界。
    :return: 转换为浮点数后的合法值。
    :raises ToolError: 值不是有限数值或落在区间之外。
    """

    if name not in arguments:
        return default
    value = arguments[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ToolError("invalid_argument", f"{name} must be a finite number.")
    numeric = float(value)
    if numeric < minimum or numeric > maximum:
        raise ToolError("invalid_argument", f"{name} must be between {minimum} and {maximum}.")
    return numeric


def validate_json_value(value: Any) -> None:
    """递归确认工具参数只包含标准 JSON 可表达的值。

    :param value: 任意工具参数值或嵌套容器。
    :raises ToolError: 包含非字符串对象键、非有限浮点数或不支持的类型。
    """

    # 标量直接结束；容器递归检查，浮点数额外拒绝 JSON 不支持的非有限值。
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ToolError("invalid_json_value", "NaN and Infinity are not valid tool arguments.")
        return
    if isinstance(value, list):
        for item in value:
            validate_json_value(item)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ToolError("invalid_json_value", "JSON object keys must be strings.")
            validate_json_value(item)
        return
    raise ToolError("invalid_json_value", f"Unsupported JSON value type: {type(value).__name__}.")


__all__ = [
    "CancellationCheck",
    "ToolConfirmation",
    "ToolError",
    "optional_boolean",
    "optional_integer",
    "optional_number",
    "optional_string",
    "reject_unknown",
    "require_string",
    "validate_json_value",
]
