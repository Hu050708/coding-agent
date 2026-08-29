"""将现有安全 JSONL trace 汇总为评测指标。"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from .contracts import TraceSummary


class TraceReader:
    """读取一次 CLI 运行生成的最新 trace 文件。"""

    def read_workspace(self, workspace: Path) -> TraceSummary:
        """查找工作区最新 trace；没有 trace 时返回空摘要。"""

        trace_dir = workspace / ".coding-agent-traces"
        candidates = sorted(trace_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime_ns)
        if not candidates:
            return TraceSummary()
        return self.read(candidates[-1], relative_to=workspace)

    def read(self, path: Path, *, relative_to: Path | None = None) -> TraceSummary:
        """逐行容错解析安全事件，不接触提示词、推理或工具正文。"""

        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and isinstance(value.get("event"), str):
                records.append(value)

        started = next((item for item in records if item["event"] == "run_started"), {})
        finished = next(
            (item for item in reversed(records) if item["event"] == "run_finished"),
            {},
        )
        models = [item for item in records if item["event"] == "model_completed"]
        tools = [item for item in records if item["event"] == "tool_completed"]
        tool_counts = Counter(str(item.get("tool", "unknown")) for item in tools)
        error_counts = Counter(
            str(item["error_code"])
            for item in tools
            if item.get("error_code") not in {None, ""}
        )
        usage = finished.get("usage")
        if not isinstance(usage, dict):
            usage = self._sum_usage(models)

        trace_name = path.name
        if relative_to is not None:
            try:
                trace_name = path.relative_to(relative_to).as_posix()
            except ValueError:
                pass
        return TraceSummary(
            requested_model=self._optional_text(started.get("model")),
            response_models=self._unique_text(models, "response_model"),
            system_fingerprints=self._unique_text(models, "system_fingerprint"),
            status=self._optional_text(finished.get("status")),
            reason=self._optional_text(finished.get("reason")),
            verified=str(finished.get("verified", "unknown")),
            model_calls=self._integer(finished.get("model_calls"), default=len(models)),
            tool_calls=self._integer(finished.get("tool_calls"), default=len(tools)),
            usage={str(key): self._integer(value) for key, value in usage.items()},
            duration_ms=self._integer(finished.get("duration_ms")),
            successful_tools=sum(item.get("ok") is True for item in tools),
            failed_tools=sum(item.get("ok") is not True for item in tools),
            tool_counts=dict(sorted(tool_counts.items())),
            error_counts=dict(sorted(error_counts.items())),
            repeat_warnings=sum(item.get("progress_warning") is True for item in tools),
            trace_file=trace_name,
        )

    @staticmethod
    def _sum_usage(models: list[dict[str, Any]]) -> dict[str, int]:
        totals: Counter[str] = Counter()
        for model in models:
            usage = model.get("usage")
            if isinstance(usage, dict):
                totals.update(
                    {
                        str(key): value
                        for key, value in usage.items()
                        if isinstance(value, int) and not isinstance(value, bool)
                    }
                )
        return dict(totals)

    @staticmethod
    def _unique_text(records: list[dict[str, Any]], key: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                value
                for record in records
                if isinstance((value := record.get(key)), str) and value
            )
        )

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _integer(value: object, *, default: int = 0) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else default


__all__ = ["TraceReader"]
