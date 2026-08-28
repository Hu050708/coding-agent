"""使用离线适配器验证端到端智能体循环。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import sys

from coding_agent.agents import (
    Agent,
    AgentConfig,
    AgentStatus,
    AssistantMessage,
    ModelCompletion,
    ToolCall,
)
from coding_agent.agents.security import Workspace
from coding_agent.agents.tools import ToolRegistry


class ScriptedAdapter:
    model = "fake-deepseek"

    def __init__(self, completions):
        self.completions = list(completions)
        self.requests = []

    def complete(self, messages, tools, *, timeout_seconds=None):
        self.requests.append(
            {
                "messages": deepcopy(list(messages)),
                "tools": deepcopy(list(tools)),
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.completions.pop(0)


def _tool(call_id: str, name: str, arguments: dict) -> ModelCompletion:
    return ModelCompletion(
        finish_reason="tool_calls",
        assistant=AssistantMessage(
            reasoning_content=f"private-{call_id}",
            tool_calls=(
                ToolCall(
                    id=call_id,
                    name=name,
                    arguments=json.dumps(arguments, separators=(",", ":")),
                ),
            ),
        ),
    )


def test_fake_model_drives_real_search_read_edit_test_loop(tmp_path):
    source = "def add(left, right):\n    return left - right\n"
    (tmp_path / "mathutil.py").write_text(source, encoding="utf-8", newline="\n")
    (tmp_path / "test_mathutil.py").write_text(
        "from mathutil import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
        newline="\n",
    )
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()

    adapter = ScriptedAdapter(
        [
            _tool(
                "call-search",
                "search_text",
                {"query": "def add", "path": ".", "glob": "*.py"},
            ),
            _tool("call-read", "read_file", {"path": "mathutil.py"}),
            _tool(
                "call-edit",
                "replace_text",
                {
                    "path": "mathutil.py",
                    "old_text": "return left - right",
                    "new_text": "return left + right",
                    "expected_sha256": digest,
                },
            ),
            _tool(
                "call-test",
                "run_command",
                {"argv": [sys.executable, "-m", "pytest", "-q"], "cwd": ".", "timeout_seconds": 30},
            ),
            ModelCompletion(
                finish_reason="stop",
                assistant=AssistantMessage(content="Fixed add() and verified the test.", reasoning_content="private-final"),
            ),
        ]
    )
    registry = ToolRegistry(Workspace(tmp_path))
    agent = Agent(
        adapter,
        registry,
        config=AgentConfig(retry_base_seconds=0, retry_jitter_seconds=0),
    )

    result = agent.run("Fix add() and run its test")

    assert result.status is AgentStatus.MODEL_FINISHED
    assert result.model_calls == 5
    assert result.tool_calls == 4
    assert "left + right" in (tmp_path / "mathutil.py").read_text(encoding="utf-8")
    tool_payloads = [
        json.loads(message["content"])
        for message in result.messages
        if message["role"] == "tool"
    ]
    assert all(payload["ok"] is True for payload in tool_payloads)
    assert tool_payloads[0]["data"]["matches"][0]["path"] == "mathutil.py"
    assert tool_payloads[-1]["data"]["exit_code"] == 0
    assert "private-call-read" == adapter.requests[2]["messages"][-2]["reasoning_content"]
    assert len(adapter.requests[0]["tools"]) == 6
