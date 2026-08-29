"""需要显式启用的真实 DeepSeek 纵向冒烟测试。

普通测试会跳过本模块。若明确允许消耗 API 额度，请同时设置 DEEPSEEK_API_KEY 和
CODING_AGENT_RUN_LIVE=1，再直接运行本文件。
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from coding_agent.agents import Agent, AgentConfig, AgentStatus
from coding_agent.agents.providers.deepseek import DeepSeekAdapter
from coding_agent.agents.security import Workspace
from coding_agent.agents.tools import ToolRegistry


_LIVE_ENABLED = os.environ.get("CODING_AGENT_RUN_LIVE") == "1" and bool(
    os.environ.get("DEEPSEEK_API_KEY")
)
pytestmark = pytest.mark.skipif(
    not _LIVE_ENABLED,
    reason="requires explicit CODING_AGENT_RUN_LIVE=1 and DEEPSEEK_API_KEY",
)


@pytest.mark.parametrize("trial", range(3))
def test_real_read_file_tool_round_trip(tmp_path, trial):
    token = f"coding-agent-live-{trial}-{uuid4().hex}"
    (tmp_path / "note.txt").write_text(token + "\n", encoding="utf-8", newline="\n")

    adapter = DeepSeekAdapter(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        max_tokens=4096,
        timeout_seconds=60,
    )
    agent = Agent(
        adapter,
        ToolRegistry(Workspace(tmp_path)),
        config=AgentConfig(
            max_model_calls=5,
            max_tool_calls=5,
            max_total_tokens=50_000,
            wall_time_seconds=120,
            api_timeout_seconds=60,
            max_transient_retries=3,
        ),
    )

    result = agent.run(
        "Use read_file to read note.txt. Do not run commands or modify any file. "
        "Then reply with the exact token from that file."
    )

    assert result.status is AgentStatus.MODEL_FINISHED
    assert result.tool_calls >= 1
    assert result.final_content is not None and token in result.final_content
