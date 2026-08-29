"""检测完全重复的工具交换，并以有界摘要提供恢复提示。
note:
    使用hash256来对这次工具调用算出来哈希值，然后跟之前持久化的记录做对比
    如果相同，就说明出现了一次重复工具调用

"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import Any


_VOLATILE_RESULT_KEYS = frozenset(
    {"duration_ms", "duration_seconds", "elapsed_ms", "timestamp", "occurred_at"}
)


@dataclass(frozen=True, slots=True)
class RepeatObservation:
    """一次工具交换在当前运行中的精确重复情况。"""

    # 当前规范化工具交换在本次运行中累计出现的次数。
    repeat_count: int
    # 重复次数是否已达到需要提醒模型改变策略的阈值。
    warning: bool


class RepeatedToolExchangeDetector:
    """在不保留原始内容的情况下跟踪规范化工具交换的哈希。"""

    def __init__(self, *, warning_threshold: int = 3, max_fingerprints: int = 128) -> None:
        """创建一个有容量上限的重复工具交换检测器。

        :param warning_threshold: 同一交换累计多少次后标记为需要警告，最小为 2。
        :param max_fingerprints: 内存中最多保留的不同交换指纹数量。
        :raises ValueError: 任一参数类型或取值范围不合法。
        """

        if (
            isinstance(warning_threshold, bool)
            or not isinstance(warning_threshold, int)
            or warning_threshold < 2
        ):
            raise ValueError("warning_threshold must be an integer greater than one")
        if (
            isinstance(max_fingerprints, bool)
            or not isinstance(max_fingerprints, int)
            or max_fingerprints <= 0
        ):
            raise ValueError("max_fingerprints must be a positive integer")
        self.warning_threshold = warning_threshold
        self.max_fingerprints = max_fingerprints
        self._counts: OrderedDict[str, int] = OrderedDict()

    def observe(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        result: str,
    ) -> RepeatObservation:
        """统计一次工具名、参数和结果在语义上完全相同的交换。

        :param tool_name: 本次执行的规范工具名称。
        :param arguments: 发送给工具的已解析参数映射。
        :param result: 工具返回的 JSON 字符串或普通文本。
        :return: 当前累计重复次数及是否达到警告阈值。
        """

        fingerprint = _exchange_fingerprint(tool_name, arguments, result)
        count = self._counts.pop(fingerprint, 0) + 1
        self._counts[fingerprint] = count
        while len(self._counts) > self.max_fingerprints:
            self._counts.popitem(last=False)
        return RepeatObservation(
            repeat_count=count,
            warning=count >= self.warning_threshold,
        )

    @property
    def retained_fingerprints(self) -> int:
        """返回当前保留的不同工具交换指纹数量。

        :return: 受 ``max_fingerprints`` 限制的缓存项数量。
        """

        return len(self._counts)


def _exchange_fingerprint(
    tool_name: str,
    arguments: Mapping[str, Any],
    result: str,
) -> str:
    """对工具名、参数和去波动后的结果生成稳定指纹。

    :param tool_name: 工具名称。
    :param arguments: 工具参数映射。
    :param result: 工具结果文本；合法 JSON 会先移除易变字段。
    :return: 三部分规范化内容的 SHA-256 十六进制摘要。
    """

    # 第一步：以稳定键顺序序列化参数，消除字典插入顺序差异。
    canonical_arguments = json.dumps(
        dict(arguments),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    # 第二步：结果若为 JSON，则移除耗时和时间戳等每次都会变化的字段。
    try:
        parsed_result: Any = json.loads(result)
    except (TypeError, ValueError):
        parsed_result = result
    else:
        parsed_result = _without_volatile_fields(parsed_result)
    canonical_result = json.dumps(
        parsed_result,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    # 第三步：用空字节分隔三部分，避免字符串拼接产生边界歧义。
    digest = hashlib.sha256()
    for value in (tool_name, canonical_arguments, canonical_result):
        digest.update(value.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _without_volatile_fields(value: Any) -> Any:
    """递归移除计时和时间戳等不影响语义的结果字段。

    :param value: 任意已解析 JSON 值。
    :return: 保持原有容器结构但去除易变键的新值。
    """

    if isinstance(value, Mapping):
        return {
            key: _without_volatile_fields(item)
            for key, item in value.items()
            if key not in _VOLATILE_RESULT_KEYS
        }
    if isinstance(value, list):
        return [_without_volatile_fields(item) for item in value]
    return value


__all__ = ["RepeatObservation", "RepeatedToolExchangeDetector"]
