"""验证诊断事件的脱敏、序列化和写入行为。"""

from __future__ import annotations

import io
import json

import pytest

from coding_agent.agents.diagnostics.trace import TraceWriter, summarize_argv, summarize_target


def test_trace_uses_allowlist_and_removes_sensitive_fields(tmp_path):
    path = tmp_path / "trace.jsonl"
    record = TraceWriter(path).emit(
        "model_completed",
        run_id="run-1",
        sequence=1,
        response_model="deepseek-v4-flash",
        finish_reason="stop",
        usage={"prompt_tokens": 7, "secret": "nope"},
        reasoning_content="must not be recorded",
        api_key="must not be recorded",
        arbitrary="must not be recorded",
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == record
    assert saved["usage"] == {"prompt_tokens": 7}
    assert saved["response_model"] == "deepseek-v4-flash"
    serialized = path.read_text(encoding="utf-8")
    assert "must not be recorded" not in serialized
    assert "arbitrary" not in serialized


def test_trace_can_write_to_stream_without_file():
    stream = io.StringIO()
    TraceWriter(stream=stream).emit("run_finished", status="failed", reason="protocol_error", content="hidden")
    saved = json.loads(stream.getvalue())
    assert saved["status"] == "failed"
    assert "content" not in saved


def test_trace_keeps_only_change_check_summary_fields():
    stream = io.StringIO()
    TraceWriter(stream=stream).emit(
        "run_finished",
        status="model_finished",
        change_check={
            "status": "passed",
            "change_version": 2,
            "checked_version": 2,
            "check_kind": "test",
            "tool_sequence": 7,
            "exit_code": 0,
            "content": "must not be recorded",
        },
    )

    saved = json.loads(stream.getvalue())
    assert saved["change_check"] == {
        "status": "passed",
        "change_version": 2,
        "checked_version": 2,
        "check_kind": "test",
        "tool_sequence": 7,
        "exit_code": 0,
    }
    assert "must not be recorded" not in stream.getvalue()


def test_unknown_event_is_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        TraceWriter().emit("debug", prompt="no")


def test_non_finite_numbers_are_rejected():
    with pytest.raises(ValueError):
        TraceWriter(stream=io.StringIO()).emit("run_finished", duration_ms=float("nan"))


def test_argv_summary_is_lossy():
    summary = summarize_argv(
        [r"D:\\Anaconda\\envs\\coding-agent\\python.exe", "--token=very-secret", r"private\\source.py"]
    )
    assert "very-secret" not in summary
    assert "private" not in summary
    assert "source.py" in summary
    assert summary.startswith("python.exe --token")


def test_target_summary_keeps_relative_paths_and_hides_credentials():
    assert summarize_target("src/hello.py") == "src/hello.py"
    assert summarize_target("../outside.py") is None
    assert summarize_target("config/.env") == "<protected>"
