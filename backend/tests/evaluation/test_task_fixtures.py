"""证明每个任务的原始模板失败，而工作区外参考修复可以通过。"""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from evaluation.core.catalog import TaskCatalog, TASKS_ROOT
from evaluation.tasks.category_filter.verifier import CategoryFilterVerifier
from evaluation.tasks.config_precedence.verifier import ConfigPrecedenceVerifier
from evaluation.tasks.date_boundary.verifier import DateBoundaryVerifier


CASES = (
    (
        "date_boundary",
        DateBoundaryVerifier,
        TASKS_ROOT / "date_boundary" / "reference",
    ),
    (
        "category_filter",
        CategoryFilterVerifier,
        TASKS_ROOT / "category_filter" / "reference",
    ),
    (
        "config_precedence",
        ConfigPrecedenceVerifier,
        TASKS_ROOT / "config_precedence" / "reference",
    ),
)


@pytest.mark.parametrize(("task_id", "verifier_type", "reference"), CASES)
def test_baseline_fails_and_reference_solution_passes(
    tmp_path: Path,
    task_id,
    verifier_type,
    reference: Path,
) -> None:
    task = TaskCatalog().select([task_id])[0]
    candidate = tmp_path / task_id
    shutil.copytree(
        task.template_dir,
        candidate,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )

    baseline = verifier_type(candidate).verify()
    assert not all(check.passed for check in baseline)

    for source in reference.rglob("*"):
        if not source.is_file():
            continue
        destination = candidate / source.relative_to(reference)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    corrected = verifier_type(candidate).verify()
    assert all(check.passed for check in corrected), [
        (check.name, check.detail) for check in corrected if not check.passed
    ]


def test_catalog_templates_and_task_prompts_exist() -> None:
    for task in TaskCatalog().all():
        assert task.template_dir.is_dir()
        assert (task.template_dir / "TASK.md").is_file()
