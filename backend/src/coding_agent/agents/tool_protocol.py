"""严格解析本地工具协议并规范化工具结果。
note:
    把 Coding Agent 和本地工具之间的“通信协议”管严一点，保证工具参数安全、工具返回格式统一、
    日志只提取允许的字段，并且防止 Agent 死循环重复调用同一个工具。

    strict_json_object → 检查“模型传给工具的参数”

    tool_error → 构造“标准工具错误”

    normalize_tool_result → 检查“工具返回给模型的结果”

    tool_result_metadata → 从工具结果里提取“日志信息”

    add_progress_warning → 防止 Agent 一直重复调用同一个工具

"""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from typing import Any


class _DuplicateJSONKey(ValueError):
    """严格 JSON 解析发现任意层级重复键时抛出。"""

    pass


def strict_json_object(raw: str) -> dict[str, Any]:
    """解析有限 JSON 对象，并拒绝任意层级的重复键。

    :param raw: 模型提供的原始工具参数 JSON 字符串。
    :return: 不含重复键和非有限数值的普通字典。
    :raises ValueError: JSON 非法、顶层不是对象或包含重复键/非有限数字。
    """

    # 第一步：通过解析钩子拒绝非有限常量和任意层级的重复键。
    def reject_constant(value: str) -> Any:
        """拒绝 JSON 标准以外的非有限数字常量。

        :param value: 解析器发现的 ``NaN`` 或无穷大常量文本。
        :raises ValueError: 始终抛出，阻止该常量进入参数对象。
        """

        raise ValueError(f"non-finite JSON number: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        """把键值对列表转换为字典并拒绝重复键。

        :param pairs: JSON 解析器按原顺序提供的对象键值对。
        :return: 键唯一的普通字典。
        :raises _DuplicateJSONKey: 同一对象层级出现重复键。
        """

        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJSONKey(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    value = json.loads(
        raw,
        parse_constant=reject_constant,
        object_pairs_hook=unique_object,
    )
    if not isinstance(value, dict):
        raise ValueError("tool arguments must be a JSON object")

    # 第二步：递归复核解析结果，防止嵌套结构携带非有限浮点数。
    def reject_nonfinite(item: Any) -> None:
        """递归复核嵌套参数中的浮点数均为有限值。

        :param item: 任意已解析 JSON 值。
        :raises ValueError: 任意层级包含非有限浮点数。
        """

        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("tool arguments contain a non-finite number")
        if isinstance(item, Mapping):
            for nested in item.values():
                reject_nonfinite(nested)
        elif isinstance(item, list):
            for nested in item:
                reject_nonfinite(nested)

    reject_nonfinite(value)
    return value


def tool_error(code: str, message: str, *, retryable: bool = False) -> str:
    """序列化统一格式的本地工具失败结果。

    :param code: 供状态机和模型识别的稳定错误码。
    :param message: 不含敏感数据的可读错误摘要。
    :param retryable: 模型改变参数或稍后重试是否可能成功。
    :return: 符合工具结果协议的紧凑 JSON 字符串。
    """

    return json.dumps(
        {
            "ok": False,
            "error": {"code": code, "message": message, "retryable": retryable},
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def tool_result_metadata(
    result: str,
) -> tuple[bool, str | None, int | None, bool | None]:
    """仅从注册表结果中提取白名单诊断字段。

    :param result: 注册表返回的工具结果 JSON 字符串。
    :return: 成功标志、错误码、退出码和截断标志组成的元组。
    """

    # 第一步：把非 JSON、非对象和错误字段缺失都视为无效工具结果。
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return False, "invalid_tool_result", None, None
    if not isinstance(payload, Mapping):
        return False, "invalid_tool_result", None, None
    ok = payload.get("ok") is True
    error_code: str | None = None
    error = payload.get("error")
    if isinstance(error, Mapping) and isinstance(error.get("code"), str):
        error_code = error["code"]
    data = payload.get("data")
    meta = payload.get("meta")
    exit_code: int | None = None
    truncated: bool | None = None
    # 第二步：只提取退出码和截断标志，不允许工具结果任意字段进入诊断事件。
    if isinstance(data, Mapping):
        value = data.get("exit_code")
        if isinstance(value, int) and not isinstance(value, bool):
            exit_code = value
    if isinstance(meta, Mapping):
        value = meta.get("truncated")
        if isinstance(value, bool):
            truncated = value
        else:
            stdout_truncated = meta.get("stdout_truncated")
            stderr_truncated = meta.get("stderr_truncated")
            if isinstance(stdout_truncated, bool) and isinstance(stderr_truncated, bool):
                truncated = stdout_truncated or stderr_truncated
    return ok, error_code, exit_code, truncated


def normalize_tool_result(result: Any) -> str:
    """写入历史前，确保注册表返回统一的 JSON 对象结果。

    :param result: 工具执行器返回的候选结果。
    :return: 原合法结果，或描述边界违规的标准工具错误 JSON。
    """

    # 第一步：工具边界必须返回字符串形式的严格 JSON 对象。
    if not isinstance(result, str):
        return tool_error(
            "invalid_tool_result",
            "tool registry returned a non-string result",
        )
    try:
        payload = strict_json_object(result)
    except (TypeError, ValueError, RecursionError):
        return tool_error(
            "invalid_tool_result",
            "tool registry returned invalid JSON",
        )
    # 第二步：统一协议至少包含布尔型 ok；失败时改写成模型可理解的工具错误。
    if not isinstance(payload.get("ok"), bool):
        return tool_error(
            "invalid_tool_result",
            "tool registry result must contain a boolean ok field",
        )
    return result


def add_progress_warning(result: str, *, repeat_count: int) -> str:
    """附加重复调用警告，同时保留原工具结果的成功或失败状态。

    :param result: 已通过协议规范化的工具结果 JSON 字符串。
    :param repeat_count: 同一工具交换在本次运行中的累计次数。
    :return: 在 ``meta`` 中加入进度警告后的工具结果 JSON。
    :raises ValueError: 输入结果不是严格 JSON 对象。
    """

    # 第一步：复制已有 meta，避免覆盖工具本身提供的截断、耗时等信息。
    payload = strict_json_object(result)
    raw_meta = payload.get("meta")
    meta = dict(raw_meta) if isinstance(raw_meta, Mapping) else {}
    meta["progress_warning"] = {
        "code": "repeated_tool_exchange",
        "repeat_count": repeat_count,
        "message": (
            "This exact tool call has produced the same result repeatedly. "
            "Inspect the result and change approach before retrying."
        ),
    }
    # 第二步：只替换 meta 后重新序列化，ok、data 和 error 保持原样。
    payload["meta"] = meta
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


__all__ = [
    "add_progress_warning",
    "normalize_tool_result",
    "strict_json_object",
    "tool_error",
    "tool_result_metadata",
]
