from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from clearloop.security import CommandDecision, CommandRequest, Workspace
from clearloop.tools import ToolRegistry


def decode(payload: str) -> dict:
    value = json.loads(payload)
    assert isinstance(value, dict)
    return value


def test_allowlisted_python_module_runs_without_confirmation(tmp_path: Path) -> None:
    registry = ToolRegistry(Workspace(tmp_path))
    response = decode(
        registry.execute("run_command", {"argv": [sys.executable, "-m", "compileall", "-q", "."]})
    )
    assert response["ok"] is True
    assert response["data"]["exit_code"] == 0
    assert response["meta"]["policy"] == "allow"
    assert response["meta"]["exit_code"] == 0
    assert isinstance(response["meta"]["duration_ms"], int)
    assert response["meta"]["truncated"] is False


def test_arbitrary_python_requires_confirmation(tmp_path: Path) -> None:
    registry = ToolRegistry(Workspace(tmp_path))
    response = decode(
        registry.execute("run_command", {"argv": [sys.executable, "-c", "print('blocked')"]})
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "command_confirmation_required"


def test_confirmation_callback_receives_real_request(tmp_path: Path) -> None:
    observed: list[CommandRequest] = []

    def confirm(request: CommandRequest) -> bool:
        observed.append(request)
        return True

    registry = ToolRegistry(Workspace(tmp_path), confirm_command=confirm)
    response = decode(
        registry.execute("run_command", {"argv": [sys.executable, "-c", "print('approved')"]})
    )
    assert response["ok"] is True
    assert response["data"]["stdout"] == "approved\r\n" if os.name == "nt" else "approved\n"
    assert len(observed) == 1
    assert observed[0].argv[2] == "print('approved')"
    assert observed[0].decision is CommandDecision.CONFIRM


def test_confirmation_callback_can_reject(tmp_path: Path) -> None:
    registry = ToolRegistry(Workspace(tmp_path), confirm_command=lambda request: False)
    response = decode(
        registry.execute("run_command", {"argv": [sys.executable, "-c", "print('no')"]})
    )
    assert response["error"]["code"] == "command_rejected"


@pytest.mark.skipif(os.name != "nt", reason="Windows shell policy case")
def test_shell_host_is_denied_before_execution(tmp_path: Path) -> None:
    cmd = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    response = decode(
        ToolRegistry(Workspace(tmp_path), auto_approve=True).execute(
            "run_command", {"argv": [os.fspath(cmd), "/c", "echo", "must-not-run"]}
        )
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "command_denied"


def test_nonzero_exit_is_structured_and_preserves_output(tmp_path: Path) -> None:
    response = decode(
        ToolRegistry(Workspace(tmp_path), auto_approve=True).execute(
            "run_command",
            {"argv": [sys.executable, "-c", "import sys; print('before'); sys.exit(7)"]},
        )
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "command_exit_nonzero"
    assert response["data"]["exit_code"] == 7
    assert "before" in response["data"]["stdout"]


def test_stdout_and_stderr_are_drained_concurrently_and_bounded(tmp_path: Path) -> None:
    code = (
        "import sys; "
        "sys.stdout.write('A'*200000); sys.stdout.flush(); "
        "sys.stderr.write('B'*200000); sys.stderr.flush()"
    )
    response = decode(
        ToolRegistry(
            Workspace(tmp_path), auto_approve=True, max_command_output_bytes=512
        ).execute("run_command", {"argv": [sys.executable, "-c", code], "timeout_seconds": 10})
    )
    assert response["ok"] is True
    assert response["meta"]["stdout_total_bytes"] == 200_000
    assert response["meta"]["stderr_total_bytes"] == 200_000
    assert response["meta"]["stdout_truncated"] is True
    assert response["meta"]["stderr_truncated"] is True
    assert response["meta"]["truncated"] is True
    assert "bytes omitted" in response["data"]["stdout"]
    assert "bytes omitted" in response["data"]["stderr"]
    assert len(response["data"]["stdout"]) < 600
    assert len(response["data"]["stderr"]) < 600


def test_timeout_kills_process_and_returns_bounded_result(tmp_path: Path) -> None:
    started = time.monotonic()
    response = decode(
        ToolRegistry(Workspace(tmp_path), auto_approve=True).execute(
            "run_command",
            {
                "argv": [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(5)"],
                "timeout_seconds": 0.2,
            },
        )
    )
    elapsed = time.monotonic() - started
    assert response["ok"] is False
    assert response["error"]["code"] == "command_timed_out"
    assert response["data"]["timed_out"] is True
    assert "started" in response["data"]["stdout"]
    assert elapsed < 4


def test_running_command_can_be_cancelled(tmp_path: Path) -> None:
    ready = tmp_path / "command-ready.txt"
    registry = ToolRegistry(
        Workspace(tmp_path),
        auto_approve=True,
        cancel_check=ready.exists,
    )
    code = (
        "import pathlib,time; "
        "pathlib.Path('command-ready.txt').write_text('ready'); "
        "print('started', flush=True); time.sleep(10)"
    )

    started = time.monotonic()
    response = decode(
        registry.execute(
            "run_command",
            {"argv": [sys.executable, "-c", code], "timeout_seconds": 10},
        )
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "command_cancelled"
    assert response["data"]["cancelled"] is True
    assert response["data"]["timed_out"] is False
    assert response["meta"]["cancelled"] is True
    assert ready.exists()
    assert time.monotonic() - started < 4


def test_cancellation_terminates_spawned_child_process(tmp_path: Path) -> None:
    ready = tmp_path / "tree-ready.txt"
    child_survived = tmp_path / "child-survived.txt"
    child_code = (
        "import pathlib,time; time.sleep(1.0); "
        "pathlib.Path('child-survived.txt').write_text('alive')"
    )
    parent_code = (
        "import pathlib,subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "pathlib.Path('tree-ready.txt').write_text('ready'); "
        "time.sleep(10)"
    )
    registry = ToolRegistry(
        Workspace(tmp_path),
        auto_approve=True,
        cancel_check=ready.exists,
    )

    response = decode(
        registry.execute(
            "run_command",
            {"argv": [sys.executable, "-c", parent_code], "timeout_seconds": 10},
        )
    )

    assert response["error"]["code"] == "command_cancelled"
    assert ready.exists()
    time.sleep(1.3)
    assert not child_survived.exists(), response


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal escalation case")
def test_cancellation_force_kills_child_that_ignores_sigterm(tmp_path: Path) -> None:
    ready = tmp_path / "tree-ready.txt"
    child_survived = tmp_path / "child-survived.txt"
    child_code = (
        "import pathlib,signal,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path('child-ready.txt').write_text('ready'); "
        "time.sleep(1.0); pathlib.Path('child-survived.txt').write_text('alive')"
    )
    parent_code = (
        "import pathlib,subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        "child_ready=pathlib.Path('child-ready.txt')\n"
        "for _ in range(200):\n"
        "    if child_ready.exists(): break\n"
        "    time.sleep(0.01)\n"
        "pathlib.Path('tree-ready.txt').write_text('ready'); time.sleep(10)"
    )
    registry = ToolRegistry(
        Workspace(tmp_path),
        auto_approve=True,
        cancel_check=ready.exists,
    )

    response = decode(
        registry.execute(
            "run_command",
            {"argv": [sys.executable, "-c", parent_code], "timeout_seconds": 10},
        )
    )

    assert response["error"]["code"] == "command_cancelled"
    time.sleep(1.3)
    assert not child_survived.exists(), response


def test_false_cancellation_callback_preserves_success_behavior(tmp_path: Path) -> None:
    checks = 0

    def not_cancelled() -> bool:
        nonlocal checks
        checks += 1
        return False

    response = decode(
        ToolRegistry(
            Workspace(tmp_path),
            auto_approve=True,
            cancel_check=not_cancelled,
        ).execute(
            "run_command",
            {"argv": [sys.executable, "-c", "print('completed')"]},
        )
    )

    assert response["ok"] is True
    assert response["data"]["stdout"].strip() == "completed"
    assert response["data"]["cancelled"] is False
    assert checks >= 1


def test_cancellation_callback_exception_is_treated_as_not_cancelled(tmp_path: Path) -> None:
    checks = 0

    def broken_cancel_check() -> bool:
        nonlocal checks
        checks += 1
        raise RuntimeError("observer failed")

    response = decode(
        ToolRegistry(
            Workspace(tmp_path),
            auto_approve=True,
            cancel_check=broken_cancel_check,
        ).execute(
            "run_command",
            {"argv": [sys.executable, "-c", "print('completed')"]},
        )
    )

    assert response["ok"] is True
    assert response["data"]["stdout"].strip() == "completed"
    assert response["data"]["cancelled"] is False
    assert checks >= 1


def test_controller_timeout_cap_can_be_below_schema_minimum(tmp_path: Path) -> None:
    started = time.monotonic()
    response = decode(
        ToolRegistry(Workspace(tmp_path), auto_approve=True).execute(
            "run_command",
            {
                "argv": [sys.executable, "-c", "import time; time.sleep(5)"],
                "timeout_seconds": 10,
            },
            timeout_seconds=0.05,
        )
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "wall_time_exceeded"
    assert response["meta"]["deadline_limited"] is True
    assert response["meta"]["effective_timeout_seconds"] == pytest.approx(0.05)
    assert time.monotonic() - started < 4


def test_child_does_not_receive_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DeepSeek_Api_Key", "top-secret")
    code = "import os; print(os.environ.get('DeepSeek_Api_Key', 'missing'))"
    response = decode(
        ToolRegistry(Workspace(tmp_path), auto_approve=True).execute(
            "run_command", {"argv": [sys.executable, "-c", code]}
        )
    )
    assert response["ok"] is True
    assert response["data"]["stdout"].strip() == "missing"


def test_command_cwd_cannot_escape_workspace(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    response = decode(
        ToolRegistry(Workspace(root), auto_approve=True).execute(
            "run_command",
            {"argv": [sys.executable, "-c", "print('no')"], "cwd": "../"},
        )
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "path_traversal"
