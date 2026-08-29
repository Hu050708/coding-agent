"""记录文件修改之后是否运行过对应检查。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from coding_agent.agents.contracts import ChangeCheckSummary


_CHANGE_TOOLS = frozenset(
    {"make_directory", "write_file", "replace_text", "delete_file"}
)
_CHECK_STRENGTH = {"run": 1, "compile": 2, "test": 3}


def command_check_kind(arguments: Mapping[str, Any]) -> str | None:
    """识别当前项目允许记录的测试、编译和程序运行命令。"""

    argv = arguments.get("argv")
    if not isinstance(argv, list) or not argv or not all(
        isinstance(item, str) for item in argv
    ):
        return None

    executable = Path(argv[0]).name.casefold()
    rest = argv[1:]
    if executable in {"pytest", "pytest.exe"}:
        return "test"
    if executable.startswith("python"):
        if len(rest) >= 2 and rest[0] == "-m":
            if rest[1] in {"pytest", "unittest"}:
                return "test"
            if rest[1] == "compileall":
                return "compile"
            return "run"
        if rest and not rest[0].startswith("-") and Path(rest[0]).suffix.casefold() == ".py":
            return "run"
    if executable in {"node", "node.exe"} and rest:
        if rest[0] == "--test":
            return "test"
        if rest[0] == "--check":
            return "compile"
        if not rest[0].startswith("-"):
            return "run"
    return None


class ChangeCheck:
    """维护一次 Agent 运行中的修改和检查先后关系。"""

    def __init__(self) -> None:
        self.status = "no_changes"
        self.change_version = 0
        self.checked_version: int | None = None
        self.check_kind: str | None = None
        self.tool_sequence: int | None = None
        self.exit_code: int | None = None

    def observe(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any] | None,
        ok: bool,
        exit_code: int | None,
        sequence: int,
    ) -> None:
        """根据一条已经完成的工具结果更新检查状态。"""

        if tool_name in _CHANGE_TOOLS:
            if ok:
                self.change_version += 1
                self.status = (
                    "outdated" if self.tool_sequence is not None else "needs_check"
                )
            return

        if tool_name != "run_command" or arguments is None:
            return
        kind = command_check_kind(arguments)
        if kind is None or exit_code is None:
            return

        if ok and exit_code == 0:
            if (
                self.status == "passed"
                and self.checked_version == self.change_version
                and _CHECK_STRENGTH.get(self.check_kind or "", 0)
                >= _CHECK_STRENGTH[kind]
            ):
                return
            self._record_check(kind, sequence=sequence, exit_code=exit_code, passed=True)
        elif kind in {"test", "compile"}:
            self._record_check(kind, sequence=sequence, exit_code=exit_code, passed=False)

    def _record_check(
        self,
        kind: str,
        *,
        sequence: int,
        exit_code: int,
        passed: bool,
    ) -> None:
        self.checked_version = self.change_version
        self.check_kind = kind
        self.tool_sequence = sequence
        self.exit_code = exit_code
        if self.change_version == 0 and passed:
            self.status = "no_changes"
        else:
            self.status = "passed" if passed else "failed"

    def summary(self) -> ChangeCheckSummary:
        """返回可写入运行结果和安全事件的不可变摘要。"""

        return ChangeCheckSummary(
            status=self.status,
            change_version=self.change_version,
            checked_version=self.checked_version,
            check_kind=self.check_kind,
            tool_sequence=self.tool_sequence,
            exit_code=self.exit_code,
        )


__all__ = ["ChangeCheck", "command_check_kind"]
