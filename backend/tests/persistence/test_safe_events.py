"""验证运行事件白名单、脱敏和负载大小限制。"""

from __future__ import annotations

import math

import pytest

from coding_agent.repository import UnsafeEventError, safe_approval_data, sanitize_run_event


def test_safe_event_drops_path_command_and_provider_fields() -> None:
    result = sanitize_run_event(
        "run.accepted",
        {
            "run_id": "abc",
            "status": "starting",
            "workspace": "E:/private/project",
            "database_url": "postgresql://secret",
            "raw_response": {"secret": "value"},
        },
    )
    assert result == {"run_id": "abc", "status": "starting"}


def test_approval_event_does_not_persist_argv_or_cwd() -> None:
    result = sanitize_run_event(
        "approval.required",
        {
            "run_id": "run",
            "approval": {
                "approval_id": "approval",
                "argv": ["tool", "--password", "secret"],
                "cwd": "E:/private/project",
                "reason": "manual confirmation",
                "created_at": "2026-08-27T00:00:00Z",
                "expires_at": "2026-08-27T00:01:00Z",
            },
        },
    )
    assert result["approval"] == {
        "approval_id": "approval",
        "reason": "manual confirmation",
        "created_at": "2026-08-27T00:00:00Z",
        "expires_at": "2026-08-27T00:01:00Z",
    }


def test_unknown_events_and_non_finite_values_are_rejected() -> None:
    with pytest.raises(UnsafeEventError):
        sanitize_run_event("provider.raw", {})
    with pytest.raises(UnsafeEventError):
        sanitize_run_event("run.finished", {"duration_seconds": math.inf})


def test_approval_storage_shape_has_no_raw_execution_details() -> None:
    result = safe_approval_data(
        tool_name="run_command",
        action_summary="Run project tests",
        reason="Command requires confirmation",
    )
    assert set(result) == {"tool_name", "action_summary", "reason"}


def test_repeated_tool_event_keeps_only_safe_progress_fields() -> None:
    result = sanitize_run_event(
        "tool.completed",
        {
            "sequence": 3,
            "tool_name": "read_file",
            "ok": True,
            "repeat_count": 3,
            "progress_warning": True,
            "arguments": {"path": "private.py"},
            "raw_result": "secret file content",
        },
    )

    assert result == {
        "sequence": 3,
        "tool_name": "read_file",
        "ok": True,
        "repeat_count": 3,
        "progress_warning": True,
    }


def test_tool_events_keep_only_bounded_display_summaries() -> None:
    started = sanitize_run_event(
        "tool.started",
        {
            "sequence": 1,
            "tool_name": "run_command",
            "argv_summary": "python hello.py",
            "argv": ["python", "hello.py", "secret"],
        },
    )
    completed = sanitize_run_event(
        "tool.completed",
        {
            "sequence": 1,
            "tool_name": "write_file",
            "ok": True,
            "result_summary": "创建 hello.py · 428 B",
            "raw_result": "file contents",
        },
    )

    assert started == {
        "sequence": 1,
        "tool_name": "run_command",
        "argv_summary": "python hello.py",
    }
    assert completed == {
        "sequence": 1,
        "tool_name": "write_file",
        "ok": True,
        "result_summary": "创建 hello.py · 428 B",
    }


def test_change_check_survives_safe_event_storage_without_extra_fields() -> None:
    result = sanitize_run_event(
        "run.finished",
        {
            "run_id": "run",
            "status": "completed",
            "change_check": {
                "status": "passed",
                "change_version": 2,
                "checked_version": 2,
                "check_kind": "test",
                "tool_sequence": 8,
                "exit_code": 0,
                "raw_output": "secret",
            },
        },
    )

    assert result["change_check"] == {
        "status": "passed",
        "change_version": 2,
        "checked_version": 2,
        "check_kind": "test",
        "tool_sequence": 8,
        "exit_code": 0,
    }
