"""把逐次 JSON 结果汇总成机器可读摘要和中文 Markdown。"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import mean, median
from typing import Iterable

from .contracts import TrialResult


class BenchmarkReporter:
    """持久化单次结果并生成描述性统计。"""

    def write_trial(self, directory: Path, result: TrialResult) -> Path:
        """将一份试验结果写入对应试验目录。"""

        path = directory / "trial.json"
        self._write_json(path, result.as_dict())
        return path

    def write_summary(
        self,
        output: Path,
        trials: Iterable[TrialResult],
        *,
        model: str,
        source_commit: str | None,
        source_dirty: bool | None,
    ) -> tuple[Path, Path]:
        """生成 ``summary.json`` 和 ``BENCHMARK_REPORT.md``。"""

        items = tuple(trials)
        summary = self._summary_payload(
            items,
            model=model,
            source_commit=source_commit,
            source_dirty=source_dirty,
        )
        json_path = output / "summary.json"
        markdown_path = output / "BENCHMARK_REPORT.md"
        self._write_json(json_path, summary)
        markdown_path.write_text(
            self._render_markdown(items, summary),
            encoding="utf-8",
            newline="\n",
        )
        return json_path, markdown_path

    @staticmethod
    def _summary_payload(
        trials: tuple[TrialResult, ...],
        *,
        model: str,
        source_commit: str | None,
        source_dirty: bool | None,
    ) -> dict[str, object]:
        classifications = Counter(item.classification for item in trials)
        check_statuses = Counter(
            str(item.trace.change_check.get("status", "unknown")) for item in trials
        )
        current_checks = sum(
            item.trace.change_check.get("status") == "passed" for item in trials
        )
        check_verifier_mismatches = sum(
            (item.trace.change_check.get("status") == "passed")
            != item.verification.passed
            for item in trials
        )
        durations = [item.trace.duration_ms / 1000 for item in trials]
        tokens = [item.trace.usage.get("total_tokens", 0) for item in trials]
        by_task: dict[str, dict[str, object]] = {}
        grouped: defaultdict[str, list[TrialResult]] = defaultdict(list)
        for item in trials:
            grouped[item.task_id].append(item)
        for task_id, task_trials in grouped.items():
            verifier_successes = sum(item.verification.passed for item in task_trials)
            end_to_end_successes = sum(
                item.classification == "success" for item in task_trials
            )
            by_task[task_id] = {
                "title": task_trials[0].task_title,
                "runs": len(task_trials),
                "successes": verifier_successes,
                "success_rate": verifier_successes / len(task_trials),
                "end_to_end_successes": end_to_end_successes,
                "end_to_end_success_rate": end_to_end_successes / len(task_trials),
            }
        verifier_success_count = sum(item.verification.passed for item in trials)
        end_to_end_success_count = classifications.get("success", 0)
        return {
            "schema_version": 1,
            "model_requested": model,
            "source_commit": source_commit,
            "source_dirty": source_dirty,
            "total_trials": len(trials),
            "verified_successes": verifier_success_count,
            "verified_success_rate": verifier_success_count / len(trials) if trials else 0.0,
            "end_to_end_successes": end_to_end_success_count,
            "end_to_end_success_rate": (
                end_to_end_success_count / len(trials) if trials else 0.0
            ),
            "classifications": dict(sorted(classifications.items())),
            "change_check_statuses": dict(sorted(check_statuses.items())),
            "current_checks": current_checks,
            "check_verifier_mismatches": check_verifier_mismatches,
            "duration_seconds": {
                "mean": mean(durations) if durations else 0.0,
                "median": median(durations) if durations else 0.0,
                "maximum": max(durations, default=0.0),
            },
            "total_tokens": {
                "mean": mean(tokens) if tokens else 0.0,
                "median": median(tokens) if tokens else 0.0,
                "maximum": max(tokens, default=0),
            },
            "tasks": by_task,
            "trials": [item.as_dict() for item in trials],
        }

    @staticmethod
    def _render_markdown(
        trials: tuple[TrialResult, ...], summary: dict[str, object]
    ) -> str:
        verified_rate = float(summary["verified_success_rate"]) * 100
        end_to_end_rate = float(summary["end_to_end_success_rate"]) * 100
        lines = [
            "# Coding Agent 可复现评测报告",
            "",
            "本报告使用固定任务模板、全新临时工作区和工作区外独立验收器。",
            "模型最终回答不作为成功依据；外部验收和 Agent 端到端运行结果分别统计。",
            "",
            "## 总览",
            "",
            f"- 请求模型：`{summary['model_requested']}`",
            f"- 源码提交：`{summary['source_commit'] or 'unknown'}`",
            f"- 工作区有未提交改动：`{summary['source_dirty']}`",
            f"- 独立验收成功：{summary['verified_successes']}/{summary['total_trials']}（{verified_rate:.1f}%）",
            f"- 端到端成功：{summary['end_to_end_successes']}/{summary['total_trials']}（{end_to_end_rate:.1f}%）",
            f"- 最后修改后检查通过：{summary['current_checks']}/{summary['total_trials']}",
            f"- 内部检查与外部验收不一致：{summary['check_verifier_mismatches']} 次",
            "",
            "## 分任务结果",
            "",
            "| 任务 | 类别 | 轮次 | 外部验收 | 端到端结果 | 修改后检查 | 模型调用 | 工具调用 | Token | 耗时 |",
            "|---|---|---:|---|---|---|---:|---:|---:|---:|",
        ]
        for trial in trials:
            check_status = str(trial.trace.change_check.get("status", "unknown"))
            check_kind = trial.trace.change_check.get("check_kind")
            check_label = {
                "passed": f"通过（{check_kind or 'check'}）",
                "failed": "未通过",
                "outdated": "已过期",
                "needs_check": "未检查",
                "no_changes": "未修改",
            }.get(check_status, "未知")
            lines.append(
                "| "
                f"{trial.task_title} | {trial.category} | {trial.repeat_index} | "
                f"{'通过' if trial.verification.passed else '未通过'} | "
                f"{trial.classification} | {check_label} | {trial.trace.model_calls} | "
                f"{trial.trace.tool_calls} | {trial.trace.usage.get('total_tokens', 0)} | "
                f"{trial.trace.duration_ms / 1000:.1f}s |"
            )
        lines.extend(
            [
                "",
                "## 失败分布",
                "",
            ]
        )
        classifications = summary["classifications"]
        assert isinstance(classifications, dict)
        if classifications:
            for name, count in classifications.items():
                lines.append(f"- `{name}`：{count}")
        else:
            lines.append("- 尚无试验结果。")
        lines.extend(
            [
                "",
                "## 解释边界",
                "",
                "- `deepseek-v4-flash` 是滚动模型别名，实际响应模型和 fingerprint 以每轮 JSON 为准。",
                "- 这里只提供小样本描述性统计，不声称具有统计显著性。",
                "- verifier 是独立子进程和工作区边界，不是操作系统级沙箱。",
                "- 原始 trace 不包含提示词、推理、文件内容、命令输出或 API 凭据。",
                "",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )


__all__ = ["BenchmarkReporter"]
