"""检测完全重复的工具交换，并以有界摘要提供恢复提示。"""

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

    repeat_count: int
    warning: bool


class RepeatedToolExchangeDetector:
    """Track hashes of canonical tool exchanges without retaining raw content."""

    def __init__(self, *, warning_threshold: int = 3, max_fingerprints: int = 128) -> None:
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
        """Count one semantically identical name/arguments/result exchange."""

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
        return len(self._counts)


def _exchange_fingerprint(
    tool_name: str,
    arguments: Mapping[str, Any],
    result: str,
) -> str:
    canonical_arguments = json.dumps(
        dict(arguments),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
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
    digest = hashlib.sha256()
    for value in (tool_name, canonical_arguments, canonical_result):
        digest.update(value.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _without_volatile_fields(value: Any) -> Any:
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
