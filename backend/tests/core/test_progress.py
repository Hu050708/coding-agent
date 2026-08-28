"""验证完全重复工具交换检测只保存有界哈希摘要。"""

from __future__ import annotations

import json

import pytest

from coding_agent.agents.progress import RepeatedToolExchangeDetector
from coding_agent.agents.tool_protocol import add_progress_warning


def test_detector_canonicalizes_json_key_order_and_warns_on_third_exchange() -> None:
    detector = RepeatedToolExchangeDetector(warning_threshold=3)
    first = detector.observe(
        "read_file",
        {"path": "a.py", "start_line": 1},
        '{"ok":true,"data":{"text":"hello"},"meta":{}}',
    )
    second = detector.observe(
        "read_file",
        {"start_line": 1, "path": "a.py"},
        '{"meta":{},"data":{"text":"hello"},"ok":true}',
    )
    third = detector.observe(
        "read_file",
        {"path": "a.py", "start_line": 1},
        '{"ok":true,"data":{"text":"hello"},"meta":{}}',
    )

    assert (first.repeat_count, first.warning) == (1, False)
    assert (second.repeat_count, second.warning) == (2, False)
    assert (third.repeat_count, third.warning) == (3, True)


def test_detector_treats_different_arguments_or_results_as_different_exchanges() -> None:
    detector = RepeatedToolExchangeDetector(warning_threshold=2)
    assert detector.observe("read_file", {"path": "a.py"}, '{"ok":true}').repeat_count == 1
    assert detector.observe("read_file", {"path": "b.py"}, '{"ok":true}').repeat_count == 1
    assert detector.observe("read_file", {"path": "a.py"}, '{"ok":false}').repeat_count == 1


def test_detector_ignores_volatile_command_timing_fields() -> None:
    detector = RepeatedToolExchangeDetector(warning_threshold=2)
    first = detector.observe(
        "run_command",
        {"argv": ["python", "-m", "pytest"]},
        json.dumps(
            {
                "ok": False,
                "data": {"exit_code": 1, "duration_seconds": 1.25},
                "meta": {"duration_ms": 1250},
            }
        ),
    )
    second = detector.observe(
        "run_command",
        {"argv": ["python", "-m", "pytest"]},
        json.dumps(
            {
                "ok": False,
                "data": {"exit_code": 1, "duration_seconds": 2.5},
                "meta": {"duration_ms": 2500},
            }
        ),
    )

    assert first.warning is False
    assert (second.repeat_count, second.warning) == (2, True)


def test_detector_evicts_old_fingerprints_without_retaining_raw_content() -> None:
    detector = RepeatedToolExchangeDetector(max_fingerprints=2)
    marker = "RAW_SECRET_MARKER_7dd1"
    detector.observe("read_file", {"path": "a"}, json.dumps({"ok": True, "data": marker}))
    detector.observe("read_file", {"path": "b"}, '{"ok":true}')
    detector.observe("read_file", {"path": "c"}, '{"ok":true}')

    assert detector.retained_fingerprints == 2
    assert marker not in repr(detector.__dict__)


@pytest.mark.parametrize(
    "arguments",
    [
        {"warning_threshold": 1},
        {"warning_threshold": True},
        {"max_fingerprints": 0},
        {"max_fingerprints": False},
    ],
)
def test_detector_rejects_unbounded_or_invalid_configuration(arguments: dict) -> None:
    with pytest.raises(ValueError):
        RepeatedToolExchangeDetector(**arguments)


def test_progress_warning_preserves_original_status_and_error() -> None:
    original = json.dumps(
        {
            "ok": False,
            "error": {
                "code": "command_exit_nonzero",
                "message": "failed",
                "retryable": False,
            },
            "meta": {"stderr_truncated": False},
        },
        separators=(",", ":"),
    )

    payload = json.loads(add_progress_warning(original, repeat_count=3))

    assert payload["ok"] is False
    assert payload["error"]["code"] == "command_exit_nonzero"
    assert payload["meta"]["stderr_truncated"] is False
    assert payload["meta"]["progress_warning"] == {
        "code": "repeated_tool_exchange",
        "repeat_count": 3,
        "message": (
            "This exact tool call has produced the same result repeatedly. "
            "Inspect the result and change approach before retrying."
        ),
    }
