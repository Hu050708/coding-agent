"""验证演示评测脚本的参数转发和结果输出。"""

from __future__ import annotations

import subprocess
import sys

from scripts import run_demo_trial


def test_demo_trial_invokes_the_importable_module_entrypoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-sent")
    calls: list[list[str]] = []

    def fake_run(arguments, **_kwargs):
        calls.append(list(arguments))
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(run_demo_trial.subprocess, "run", fake_run)
    output = tmp_path / "candidate"

    assert run_demo_trial.main(["--output", str(output)]) == 0
    assert calls[0][:3] == [sys.executable, "-m", "coding_agent"]
    assert calls[1][0] == sys.executable
    assert (tmp_path / "candidate-result.json").is_file()
