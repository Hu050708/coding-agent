"""验证不同权限模式对文件和命令操作的决策。"""

from __future__ import annotations

import pytest

from coding_agent.agents.security import CommandDecision, PermissionMode, PermissionPolicy


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ask", PermissionMode.ASK),
        ("AGENT", PermissionMode.AGENT),
        (PermissionMode.WORKSPACE_FULL, PermissionMode.WORKSPACE_FULL),
    ],
)
def test_permission_modes_parse_to_closed_enum(raw, expected) -> None:
    assert PermissionMode.parse(raw) is expected


@pytest.mark.parametrize("raw", ["", "review", "workspace", "auto", None, 1])
def test_permission_modes_reject_unknown_values(raw) -> None:
    with pytest.raises(ValueError):
        PermissionMode.parse(raw)


def test_ask_confirms_writes_but_keeps_all_workspace_tools_visible() -> None:
    policy = PermissionPolicy(PermissionMode.ASK)
    assert policy.tool_names == {
        "list_files",
        "read_file",
        "search_text",
        "make_directory",
        "write_file",
        "replace_text",
        "delete_file",
        "run_command",
    }
    assert policy.tool_decision("read_file") is CommandDecision.ALLOW
    assert policy.tool_decision("make_directory") is CommandDecision.CONFIRM
    assert policy.tool_decision("write_file") is CommandDecision.CONFIRM
    assert policy.tool_decision("replace_text") is CommandDecision.CONFIRM
    assert policy.tool_decision("delete_file") is CommandDecision.CONFIRM


def test_agent_mode_only_requires_confirmation_for_destructive_file_deletion() -> None:
    agent = PermissionPolicy(PermissionMode.AGENT)
    full = PermissionPolicy(PermissionMode.WORKSPACE_FULL)

    assert agent.tool_decision("make_directory") is CommandDecision.ALLOW
    assert agent.tool_decision("write_file") is CommandDecision.ALLOW
    assert agent.tool_decision("replace_text") is CommandDecision.ALLOW
    assert agent.tool_decision("delete_file") is CommandDecision.CONFIRM
    assert full.tool_decision("delete_file") is CommandDecision.ALLOW


def test_command_decision_matrix_preserves_hard_denials() -> None:
    ask = PermissionPolicy(PermissionMode.ASK)
    agent = PermissionPolicy(PermissionMode.AGENT)
    full = PermissionPolicy(PermissionMode.WORKSPACE_FULL)

    assert ask.command_decision(CommandDecision.ALLOW) is CommandDecision.CONFIRM
    assert agent.command_decision(CommandDecision.ALLOW) is CommandDecision.ALLOW
    assert agent.command_decision(CommandDecision.CONFIRM) is CommandDecision.CONFIRM
    assert full.command_decision(CommandDecision.CONFIRM) is CommandDecision.ALLOW
    for policy in (ask, agent, full):
        assert policy.command_decision(CommandDecision.DENY) is CommandDecision.DENY
