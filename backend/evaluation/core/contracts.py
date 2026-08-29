"""评测任务和结果使用的数据类型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CheckResult:
    """一项独立验收检查的结果。"""

    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        """:return: 可直接写入 JSON 的普通字典。"""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvaluationTask:
    """一个固定评测任务及其工作区模板和外部验收器。"""

    task_id: str
    title: str
    category: str
    template_dir: Path
    verifier_module: str
    timeout_seconds: float = 480.0


@dataclass(frozen=True, slots=True)
class TraceSummary:
    """从 Agent 安全 JSONL trace 中提取的运行统计。"""

    requested_model: str | None = None
    response_models: tuple[str, ...] = ()
    system_fingerprints: tuple[str, ...] = ()
    status: str | None = None
    reason: str | None = None
    verified: str = "unknown"
    model_calls: int = 0
    tool_calls: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0
    successful_tools: int = 0
    failed_tools: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)
    repeat_warnings: int = 0
    change_check: dict[str, object] = field(default_factory=dict)
    trace_file: str | None = None

    def as_dict(self) -> dict[str, object]:
        """:return: 可直接写入 JSON 的普通字典。"""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkspaceChanges:
    """一次 Agent 运行造成的工作区文件变化。"""

    added: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """:return: 可直接写入 JSON 的普通字典。"""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """工作区外 verifier 的执行和业务检查结果。"""

    passed: bool
    exit_code: int | None
    checks: tuple[CheckResult, ...] = ()
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        """:return: 可直接写入 JSON 的普通字典。"""

        return {
            "passed": self.passed,
            "exit_code": self.exit_code,
            "checks": [check.as_dict() for check in self.checks],
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class TrialResult:
    """一次任务试验的完整、可序列化结果。"""

    schema_version: int
    trial_id: str
    task_id: str
    task_title: str
    category: str
    repeat_index: int
    started_at: str
    model_requested: str
    agent_exit_code: int | None
    trace: TraceSummary
    workspace: WorkspaceChanges
    verification: VerificationResult
    classification: str
    template_digest: str
    source_commit: str | None = None
    source_dirty: bool | None = None
    infrastructure_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """:return: 保持字段层级稳定的 JSON 对象。"""

        return {
            "schema_version": self.schema_version,
            "trial_id": self.trial_id,
            "task_id": self.task_id,
            "task_title": self.task_title,
            "category": self.category,
            "repeat_index": self.repeat_index,
            "started_at": self.started_at,
            "model_requested": self.model_requested,
            "agent_exit_code": self.agent_exit_code,
            "agent": self.trace.as_dict(),
            "workspace": self.workspace.as_dict(),
            "verification": self.verification.as_dict(),
            "classification": self.classification,
            "template_digest": self.template_digest,
            "source_commit": self.source_commit,
            "source_dirty": self.source_dirty,
            "infrastructure_error": self.infrastructure_error,
        }
