"""定义 benchmark 结果页面使用的只读响应模型。"""

from __future__ import annotations

from .base import ApiModel


class EvaluationMetricStats(ApiModel):
    mean: float
    median: float
    maximum: float


class EvaluationTaskSummary(ApiModel):
    title: str
    runs: int
    successes: int
    success_rate: float


class EvaluationCheck(ApiModel):
    name: str
    passed: bool
    detail: str


class EvaluationVerification(ApiModel):
    passed: bool
    exit_code: int | None
    checks: list[EvaluationCheck]
    error: str | None


class EvaluationAgentSummary(ApiModel):
    requested_model: str | None
    response_models: list[str]
    system_fingerprints: list[str]
    status: str | None
    reason: str | None
    verified: str
    model_calls: int
    tool_calls: int
    usage: dict[str, int]
    duration_ms: int
    successful_tools: int
    failed_tools: int
    tool_counts: dict[str, int]
    error_counts: dict[str, int]
    repeat_warnings: int
    trace_file: str | None


class EvaluationWorkspaceChanges(ApiModel):
    added: list[str]
    modified: list[str]
    deleted: list[str]


class EvaluationTrial(ApiModel):
    schema_version: int
    trial_id: str
    task_id: str
    task_title: str
    category: str
    repeat_index: int
    started_at: str
    model_requested: str
    agent_exit_code: int | None
    agent: EvaluationAgentSummary
    workspace: EvaluationWorkspaceChanges
    verification: EvaluationVerification
    classification: str
    template_digest: str
    source_commit: str | None
    source_dirty: bool | None
    infrastructure_error: str | None


class EvaluationRunListItem(ApiModel):
    run_id: str
    schema_version: int
    model_requested: str
    source_commit: str | None
    source_dirty: bool | None
    total_trials: int
    verified_successes: int
    verified_success_rate: float
    duration_seconds: EvaluationMetricStats
    total_tokens: EvaluationMetricStats
    tasks: dict[str, EvaluationTaskSummary]


class EvaluationRunListResponse(ApiModel):
    runs: list[EvaluationRunListItem]


class EvaluationRunResponse(EvaluationRunListItem):
    classifications: dict[str, int]
    trials: list[EvaluationTrial]


__all__ = ["EvaluationRunListResponse", "EvaluationRunResponse"]
