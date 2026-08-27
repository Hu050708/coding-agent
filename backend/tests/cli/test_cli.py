from __future__ import annotations

import io
from types import SimpleNamespace

import coding_agent.cli as cli
from coding_agent.core import AgentStatus, TerminationReason
from coding_agent.security import CommandDecision, CommandRequest


def _options(tmp_path, *extra: str):
    return cli.build_parser().parse_args(["--workspace", str(tmp_path), *extra, "fix the bug"])


def test_missing_key_fails_without_constructing_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DeepSeekAdapter", lambda **kwargs: (_ for _ in ()).throw(AssertionError()))
    stderr = io.StringIO()
    code = cli.run_cli(_options(tmp_path), environ={}, stderr=stderr)
    assert code == cli.EXIT_CONFIGURATION
    assert "DEEPSEEK_API_KEY" in stderr.getvalue()


def test_cli_wires_run_and_prints_only_final_content(tmp_path, monkeypatch):
    captured = {}

    class FakeAdapter:
        def __init__(self, **kwargs):
            captured["adapter"] = kwargs

    class FakeRegistry:
        def __init__(self, workspace, **kwargs):
            captured["workspace"] = workspace
            captured["registry"] = kwargs

    class FakeAgent:
        def __init__(self, adapter, registry, **kwargs):
            captured["agent"] = kwargs

        def run(self, task):
            captured["task"] = task
            return SimpleNamespace(
                status=AgentStatus.MODEL_FINISHED,
                reason=TerminationReason.MODEL_FINAL,
                final_content="done",
                model_calls=2,
                tool_calls=1,
                verified="unknown",
            )

    monkeypatch.setattr(cli, "DeepSeekAdapter", FakeAdapter)
    monkeypatch.setattr(cli, "ToolRegistry", FakeRegistry)
    monkeypatch.setattr(cli, "Agent", FakeAgent)
    stdout, stderr = io.StringIO(), io.StringIO()
    code = cli.run_cli(
        _options(tmp_path, "--yes"),
        environ={"DEEPSEEK_API_KEY": "local-secret"},
        stdout=stdout,
        stderr=stderr,
    )
    assert code == cli.EXIT_SUCCESS
    assert stdout.getvalue() == "done\n"
    assert "local-secret" not in stdout.getvalue() + stderr.getvalue()
    assert captured["adapter"]["api_key"] == "local-secret"
    assert captured["registry"]["auto_approve"] is True
    assert captured["agent"]["trace"].stream is stderr
    assert captured["task"] == "fix the bug"


def test_startup_error_redacts_key(tmp_path, monkeypatch):
    secret = "a-very-distinct-secret"

    class BrokenAdapter:
        def __init__(self, **kwargs):
            raise ValueError(f"bad credential {secret}")

    monkeypatch.setattr(cli, "DeepSeekAdapter", BrokenAdapter)
    stderr = io.StringIO()
    code = cli.run_cli(
        _options(tmp_path),
        environ={"DEEPSEEK_API_KEY": secret},
        stderr=stderr,
    )
    assert code == cli.EXIT_CONFIGURATION
    assert secret not in stderr.getvalue()
    assert "***" in stderr.getvalue()


def test_confirmation_escapes_control_characters():
    stderr = io.StringIO()
    request = CommandRequest(
        argv=("python", "bad\n\x1b[31m"),
        resolved_argv=("C:/Python/python.exe", "bad\n\x1b[31m"),
        cwd=SimpleNamespace(),
        decision=CommandDecision.CONFIRM,
        reason="not allowlisted",
    )
    callback = cli._confirmation_callback(input_func=lambda prompt: "yes", stream=stderr)
    assert callback(request) is True
    rendered = stderr.getvalue()
    assert "\\n" in rendered and "\\u001b" in rendered
    assert "\x1b" not in rendered


def test_base_url_may_not_embed_credentials(tmp_path):
    stderr = io.StringIO()
    options = _options(tmp_path, "--base-url", "https://user:secret@example.test")
    code = cli.run_cli(options, environ={"DEEPSEEK_API_KEY": "secret"}, stderr=stderr)
    assert code == cli.EXIT_CONFIGURATION
    assert "without credentials" in stderr.getvalue()


def test_model_final_cannot_inject_terminal_escape_sequences(tmp_path, monkeypatch):
    class FakeAdapter:
        def __init__(self, **kwargs):
            pass

    class FakeRegistry:
        def __init__(self, workspace, **kwargs):
            pass

    class FakeAgent:
        def __init__(self, adapter, registry, **kwargs):
            pass

        def run(self, task):
            return SimpleNamespace(
                status=AgentStatus.MODEL_FINISHED,
                reason=TerminationReason.MODEL_FINAL,
                final_content="safe\x1b[31m-red",
                model_calls=1,
                tool_calls=0,
                verified="unknown",
            )

    monkeypatch.setattr(cli, "DeepSeekAdapter", FakeAdapter)
    monkeypatch.setattr(cli, "ToolRegistry", FakeRegistry)
    monkeypatch.setattr(cli, "Agent", FakeAgent)
    stdout = io.StringIO()
    code = cli.run_cli(
        _options(tmp_path, "--no-trace"),
        environ={"DEEPSEEK_API_KEY": "secret"},
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == cli.EXIT_SUCCESS
    assert "\x1b" not in stdout.getvalue()
    assert "\\u001b" in stdout.getvalue()
