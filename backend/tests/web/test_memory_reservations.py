from __future__ import annotations

import threading
import time

import pytest

from coding_agent.runs.agent_runner import RunOutcome
from coding_agent.runs.run_manager import RunManager, RunManagerError
from coding_agent.security import WorkspacePolicy


class HoldingRunner:
    ready = True
    model = "fake-deepseek"

    def __init__(self) -> None:
        self.started = threading.Event()

    def run(self, spec, *, cancel_event, confirm_command, trace):
        self.started.set()
        cancel_event.wait(timeout=3)
        return _outcome("cancelled" if cancel_event.is_set() else "failed")


class ImmediateRunner:
    ready = True
    model = "fake-deepseek"

    def run(self, spec, *, cancel_event, confirm_command, trace):
        return _outcome("model_finished")


def _outcome(status: str) -> RunOutcome:
    return RunOutcome(
        status=status,
        reason="model_final" if status == "model_finished" else "user_cancelled",
        final_content="done" if status == "model_finished" else None,
        model_calls=1,
        tool_calls=0,
        usage={
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
        },
        duration_seconds=0.01,
    )


def _manager(root, runner, *, max_active_runs=1):
    return RunManager(
        runner=runner,
        workspace_policy=WorkspacePolicy(root),
        max_active_runs=max_active_runs,
        run_deadline_seconds=3,
    )


def _wait_idle(manager: RunManager, timeout: float = 2) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if manager.active_runs == 0:
            return
        time.sleep(0.005)
    raise AssertionError("manager did not release its active workspace")


def test_active_run_blocks_same_workspace_mutation_but_not_other_workspace(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    runner = HoldingRunner()
    manager = _manager(tmp_path, runner)
    try:
        run = manager.create(workspace=str(first), task="hold")
        assert runner.started.wait(timeout=1)

        with pytest.raises(RunManagerError) as busy:
            with manager.reserve_memory_mutation(str(first)):
                pass
        assert busy.value.code == "memory_workspace_busy"

        with manager.reserve_memory_mutation(str(second)) as resolved:
            assert resolved == second.resolve()

        with pytest.raises(RunManagerError) as ineligible:
            manager.validate_memory_source(run["run_id"], str(first))
        assert ineligible.value.code == "memory_source_run_ineligible"

        manager.cancel(run["run_id"])
        _wait_idle(manager)
        with manager.reserve_memory_mutation(str(first)):
            pass
    finally:
        manager.shutdown(wait=True)


def test_mutation_reservation_blocks_run_and_releases_after_exception(tmp_path):
    workspace = tmp_path / "project"
    other = tmp_path / "other"
    workspace.mkdir()
    other.mkdir()
    manager = _manager(tmp_path, ImmediateRunner())
    try:
        with pytest.raises(RuntimeError, match="service failed"):
            with manager.reserve_memory_mutation(str(workspace)):
                with pytest.raises(RunManagerError) as blocked:
                    manager.create(workspace=str(workspace), task="must not start")
                assert blocked.value.code == "memory_mutation_in_progress"

                # Reservations are workspace-scoped, not a global write lock.
                other_run = manager.create(workspace=str(other), task="allowed")
                assert other_run["run_id"]
                raise RuntimeError("service failed")

        _wait_idle(manager)
        started = manager.create(workspace=str(workspace), task="reservation released")
        assert started["run_id"]
        _wait_idle(manager)
    finally:
        manager.shutdown(wait=True)


def test_run_create_and_memory_reservation_race_has_exactly_one_winner(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    runner = HoldingRunner()
    manager = _manager(tmp_path, runner)
    barrier = threading.Barrier(2)
    other_attempt_finished = threading.Event()
    results: list[tuple[str, str]] = []
    results_lock = threading.Lock()

    def record(kind: str, value: str) -> None:
        with results_lock:
            results.append((kind, value))

    def mutate() -> None:
        barrier.wait(timeout=2)
        try:
            with manager.reserve_memory_mutation(str(workspace)):
                record("winner", "mutation")
                other_attempt_finished.wait(timeout=2)
        except RunManagerError as exc:
            record("loser", exc.code)
        finally:
            other_attempt_finished.set()

    def create_run() -> None:
        barrier.wait(timeout=2)
        try:
            run = manager.create(workspace=str(workspace), task="race")
            record("winner", f"run:{run['run_id']}")
        except RunManagerError as exc:
            record("loser", exc.code)
        finally:
            other_attempt_finished.set()

    mutation_thread = threading.Thread(target=mutate)
    run_thread = threading.Thread(target=create_run)
    try:
        mutation_thread.start()
        run_thread.start()
        mutation_thread.join(timeout=3)
        run_thread.join(timeout=3)
        assert not mutation_thread.is_alive()
        assert not run_thread.is_alive()

        winners = [value for kind, value in results if kind == "winner"]
        losers = [value for kind, value in results if kind == "loser"]
        assert len(winners) == 1
        assert len(losers) == 1
        if winners[0] == "mutation":
            assert losers == ["memory_mutation_in_progress"]
        else:
            assert winners[0].startswith("run:")
            assert losers == ["memory_workspace_busy"]
            manager.cancel(winners[0].split(":", 1)[1])
            _wait_idle(manager)
    finally:
        manager.shutdown(wait=True)
