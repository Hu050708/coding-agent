"""验证应用服务对持久化层、运行管理器和领域错误的协调。"""

from __future__ import annotations

import re
import threading
import time
from uuid import uuid4

import pytest

from coding_agent.services import ApplicationError, ApplicationServices
from coding_agent.agents.memory import MemorySummary
from coding_agent.database import create_database
from coding_agent.models import Base
from coding_agent.repository import PersistenceService
from coding_agent.agents.runtime.agent_runner import RunOutcome, RunSpec
from coding_agent.agents.runtime.run_manager import RunManager
from coding_agent.agents.security import WorkspacePolicy


class RecordingRunner:
    ready = True
    model = "test-model"

    def __init__(self) -> None:
        self.specs: list[RunSpec] = []
        self.lock = threading.Lock()

    def run(self, spec, *, cancel_event, confirm_command, trace):
        with self.lock:
            self.specs.append(spec)
        return RunOutcome(
            status="model_finished",
            reason="verified_completion",
            final_content="任务已完成",
            model_calls=1,
            tool_calls=0,
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "total_tokens": 14,
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 10,
            },
            duration_seconds=0.01,
            memory=MemorySummary(status="loaded" if spec.memory_snapshot else "empty"),
        )


@pytest.fixture
def application_stack(tmp_path):
    database = create_database(
        f"sqlite+pysqlite:///{(tmp_path / 'application.db').as_posix()}",
        require_postgresql=False,
    )
    Base.metadata.create_all(database.engine)
    persistence = PersistenceService(database.session_factory)
    allowed_root = tmp_path / "workspaces"
    allowed_root.mkdir()
    runner = RecordingRunner()
    manager = RunManager(
        runner=runner,
        workspace_policy=WorkspacePolicy(allowed_root),
        max_active_runs=4,
    )
    services = ApplicationServices.build(
        persistence=persistence,
        manager=manager,
        workspace_policy=WorkspacePolicy(allowed_root),
        benchmark_runs_dir=tmp_path / "benchmark-runs",
    )
    try:
        yield services, persistence, runner, allowed_root
    finally:
        manager.shutdown(wait=True)
        database.dispose()


def _workspace(services: ApplicationServices, root, name: str):
    path = root / name
    path.mkdir()
    return services.catalog.create_workspace(path=str(path), display_name=None)


def _conversation(services: ApplicationServices, workspace_id: str):
    return services.catalog.create_conversation(
        workspace_id=workspace_id,
        title=None,
        default_permission_mode="agent",
        use_memory=True,
    )


def _wait_terminal(services: ApplicationServices, run_id: str):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = services.runs.get(run_id)
        if result["status"] in {"completed", "failed", "cancelled", "budget_exhausted"}:
            return result
        time.sleep(0.02)
    raise AssertionError("run did not become terminal")


def test_catalog_registers_workspaces_and_updates_conversation(application_stack):
    services, _persistence, _runner, root = application_stack
    workspace = _workspace(services, root, "alpha")
    conversation = _conversation(services, str(workspace["id"]))

    assert re.fullmatch(r"新会话\d{8}-\d{6}", conversation["title"])

    updated = services.catalog.update_conversation(
        str(conversation["id"]),
        title="修复日期边界",
        default_permission_mode="workspace_full",
        use_memory=False,
    )

    assert workspace["path_hint"] == "alpha"
    assert updated["title"] == "修复日期边界"
    assert updated["default_permission_mode"] == "workspace_full"
    assert updated["use_memory"] is False
    assert services.catalog.list_messages(str(conversation["id"])) == []


def test_memory_ids_cannot_cross_workspace_boundary(application_stack):
    services, _persistence, _runner, root = application_stack
    first = _workspace(services, root, "first")
    second = _workspace(services, root, "second")
    memory = services.memories.create(
        str(second["id"]),
        kind="note",
        content="仅属于第二个工作区",
        pinned=False,
        source_run_id=None,
    )

    with pytest.raises(ApplicationError) as exc_info:
        services.memories.update(
            str(first["id"]),
            str(memory["id"]),
            kind=None,
            content="越权修改",
            pinned=None,
            enabled=None,
        )

    assert exc_info.value.code == "memory_not_found"


def test_run_is_idempotent_and_reuses_only_visible_history_and_frozen_memory(
    application_stack,
):
    services, _persistence, runner, root = application_stack
    workspace = _workspace(services, root, "project")
    workspace_id = str(workspace["id"])
    conversation = _conversation(services, workspace_id)
    conversation_id = str(conversation["id"])
    services.memories.create(
        workspace_id,
        kind="decision",
        content="所有日期边界使用闭区间",
        pinned=True,
        source_run_id=None,
    )
    request_id = str(uuid4())

    first = services.runs.create(
        conversation_id,
        content="修复日期边界",
        permission_mode="ask",
        use_memory=True,
        client_request_id=request_id,
    )
    first_terminal = _wait_terminal(services, str(first["id"]))
    replay = services.runs.create(
        conversation_id,
        content="这段不同文本必须被幂等键忽略",
        permission_mode="workspace_full",
        use_memory=False,
        client_request_id=request_id,
    )

    second = services.runs.create(
        conversation_id,
        content="补充回归测试",
        permission_mode="agent",
        use_memory=True,
        client_request_id=str(uuid4()),
    )
    _wait_terminal(services, str(second["id"]))

    assert first_terminal["final_content"] == "任务已完成"
    assert replay["id"] == first["id"]
    assert len(runner.specs) == 2
    assert runner.specs[0].permission_mode.value == "ask"
    assert [item.content for item in runner.specs[0].memory_snapshot or ()] == [
        "所有日期边界使用闭区间"
    ]
    assert [(item.role, item.content) for item in runner.specs[1].prior_messages] == [
        ("user", "修复日期边界"),
        ("assistant", "任务已完成"),
    ]
    assert [event["event"] for event in services.runs.list_events(str(second["id"]))][-1] == (
        "run.finished"
    )
