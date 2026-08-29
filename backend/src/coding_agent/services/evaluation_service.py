"""读取可复现评测器生成的安全汇总报告。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .errors import ApplicationError


_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_LIST_FIELDS = (
    "schema_version",
    "model_requested",
    "source_commit",
    "source_dirty",
    "total_trials",
    "verified_successes",
    "verified_success_rate",
    "end_to_end_successes",
    "end_to_end_success_rate",
    "duration_seconds",
    "total_tokens",
    "tasks",
)


@dataclass(frozen=True, slots=True)
class EvaluationReportService:
    """把固定目录中的 benchmark JSON 投影成只读 Web 视图。"""

    root: Path

    def list_runs(self) -> list[dict[str, Any]]:
        """列出所有结构完整的评测运行，最近生成的排在前面。"""

        if not self.root.is_dir():
            return []
        items: list[tuple[float, dict[str, Any]]] = []
        for directory in self.root.iterdir():
            if not directory.is_dir() or not _RUN_ID_PATTERN.fullmatch(directory.name):
                continue
            try:
                detail = self._load(directory.name)
                item = {"run_id": directory.name}
                item.update({field: detail[field] for field in _LIST_FIELDS})
                items.append((directory.stat().st_mtime, item))
            except (ApplicationError, KeyError, OSError):
                continue
        items.sort(key=lambda item: item[0], reverse=True)
        return [item for _modified, item in items]

    def get_run(self, run_id: str) -> dict[str, Any]:
        """读取一份完整评测汇总，不暴露 trial 工作区或原始日志。"""

        if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
            raise self._not_found()
        return self._load(run_id)

    def _load(self, run_id: str) -> dict[str, Any]:
        """解析一份 summary.json，并将目录名作为稳定运行标识。"""

        root = self.root.resolve()
        directory = (root / run_id).resolve()
        if directory.parent != root:
            raise self._not_found()
        summary_path = directory / "summary.json"
        if not summary_path.is_file():
            raise self._not_found()
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ApplicationError(
                500,
                "evaluation_report_invalid",
                "The evaluation report could not be read.",
            ) from exc
        if not isinstance(payload, dict):
            raise ApplicationError(
                500,
                "evaluation_report_invalid",
                "The evaluation report has an invalid structure.",
            )
        classifications = payload.get("classifications", {})
        end_to_end_successes = (
            classifications.get("success", 0)
            if isinstance(classifications, dict)
            else 0
        )
        total_trials = payload.get("total_trials", 0)
        payload.setdefault("end_to_end_successes", end_to_end_successes)
        payload.setdefault(
            "end_to_end_success_rate",
            end_to_end_successes / total_trials if total_trials else 0.0,
        )
        return {**payload, "run_id": run_id}

    @staticmethod
    def _not_found() -> ApplicationError:
        return ApplicationError(
            404,
            "evaluation_run_not_found",
            "The evaluation run was not found.",
        )


__all__ = ["EvaluationReportService"]
