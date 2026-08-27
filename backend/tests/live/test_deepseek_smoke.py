"""Opt-in real DeepSeek vertical smoke test.

Normal test runs skip this module. To spend API credits explicitly, set both
DEEPSEEK_API_KEY and CLEARLOOP_RUN_LIVE=1, then run this file directly.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from clearloop.core import Agent, AgentConfig, AgentStatus
from clearloop.providers import DeepSeekAdapter
from clearloop.security import Workspace
from clearloop.tools import ToolRegistry


_LIVE_ENABLED = os.environ.get("CLEARLOOP_RUN_LIVE") == "1" and bool(
    os.environ.get("DEEPSEEK_API_KEY")
)
pytestmark = pytest.mark.skipif(
    not _LIVE_ENABLED,
    reason="requires explicit CLEARLOOP_RUN_LIVE=1 and DEEPSEEK_API_KEY",
)


@pytest.mark.parametrize("trial", range(3))
def test_real_read_file_tool_round_trip(tmp_path, trial):
    token = f"clearloop-live-{trial}-{uuid4().hex}"
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
