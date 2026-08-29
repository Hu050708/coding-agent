"""三个固定评测任务的显式目录。"""

from __future__ import annotations

from pathlib import Path

from .contracts import EvaluationTask


BACKEND_ROOT = Path(__file__).resolve().parents[2]
TASKS_ROOT = BACKEND_ROOT / "evaluation" / "tasks"


class TaskCatalog:
    """通过稳定 ID 提供固定任务，不引入额外配置格式。"""

    def __init__(self) -> None:
        self._tasks = {
            task.task_id: task
            for task in (
                EvaluationTask(
                    task_id="date_boundary",
                    title="修复包含式日期结束边界",
                    category="bug_fix",
                    template_dir=BACKEND_ROOT / "examples" / "date_boundary_bug",
                    verifier_module="evaluation.tasks.date_boundary.verifier",
                ),
                EvaluationTask(
                    task_id="category_filter",
                    title="实现跨文件日志类别筛选",
                    category="multi_file_feature",
                    template_dir=TASKS_ROOT / "category_filter" / "workspace",
                    verifier_module="evaluation.tasks.category_filter.verifier",
                ),
                EvaluationTask(
                    task_id="config_precedence",
                    title="修复配置优先级中的 falsey 值回归",
                    category="regression_fix",
                    template_dir=TASKS_ROOT / "config_precedence" / "workspace",
                    verifier_module="evaluation.tasks.config_precedence.verifier",
                ),
            )
        }

    def all(self) -> tuple[EvaluationTask, ...]:
        """:return: 按注册顺序排列的全部任务。"""

        return tuple(self._tasks.values())

    def select(self, task_ids: list[str] | tuple[str, ...] | None) -> tuple[EvaluationTask, ...]:
        """根据 ID 选择任务；未指定时返回全部任务。"""

        if not task_ids:
            return self.all()
        return tuple(self._tasks[task_id] for task_id in task_ids)

    @property
    def task_ids(self) -> tuple[str, ...]:
        """:return: 可用于 CLI choices 的任务 ID。"""

        return tuple(self._tasks)


__all__ = ["BACKEND_ROOT", "TASKS_ROOT", "TaskCatalog"]
