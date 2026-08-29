"""验证文件修改和检查命令之间的状态变化。"""

from coding_agent.agents.change_check import ChangeCheck, command_check_kind


def observe(
    check: ChangeCheck,
    tool_name: str,
    *,
    ok: bool = True,
    exit_code: int | None = None,
    sequence: int = 1,
    argv: list[str] | None = None,
) -> None:
    check.observe(
        tool_name=tool_name,
        arguments={"argv": argv} if argv is not None else {},
        ok=ok,
        exit_code=exit_code,
        sequence=sequence,
    )


def test_change_requires_a_later_successful_check() -> None:
    check = ChangeCheck()

    observe(check, "replace_text")
    assert check.summary().status == "needs_check"

    observe(
        check,
        "run_command",
        argv=["python", "-m", "pytest"],
        exit_code=0,
        sequence=2,
    )
    assert check.summary().as_dict() == {
        "status": "passed",
        "change_version": 1,
        "checked_version": 1,
        "check_kind": "test",
        "tool_sequence": 2,
        "exit_code": 0,
    }

    observe(check, "write_file", sequence=3)
    assert check.summary().status == "outdated"
    assert check.summary().checked_version == 1


def test_failed_file_tool_does_not_create_a_change() -> None:
    check = ChangeCheck()

    observe(check, "write_file", ok=False)

    assert check.summary().status == "no_changes"
    assert check.summary().change_version == 0


def test_explicit_test_failure_is_recorded_but_expected_program_error_is_not() -> None:
    check = ChangeCheck()
    observe(check, "replace_text")
    observe(
        check,
        "run_command",
        argv=["python", "-m", "pytest"],
        ok=False,
        exit_code=1,
        sequence=2,
    )
    assert check.summary().status == "failed"

    observe(
        check,
        "run_command",
        argv=["python", "-m", "pytest"],
        exit_code=0,
        sequence=3,
    )
    observe(
        check,
        "run_command",
        argv=["python", "app.py", "--invalid"],
        ok=False,
        exit_code=2,
        sequence=4,
    )

    summary = check.summary()
    assert summary.status == "passed"
    assert summary.check_kind == "test"
    assert summary.tool_sequence == 3


def test_stronger_current_check_is_not_replaced_by_program_run() -> None:
    check = ChangeCheck()
    observe(check, "write_file")
    observe(
        check,
        "run_command",
        argv=["python", "-m", "pytest"],
        exit_code=0,
        sequence=2,
    )
    observe(
        check,
        "run_command",
        argv=["python", "hello.py"],
        exit_code=0,
        sequence=3,
    )

    summary = check.summary()
    assert summary.check_kind == "test"
    assert summary.tool_sequence == 2


def test_supported_command_kinds_are_simple_and_explicit() -> None:
    assert command_check_kind({"argv": ["python", "-m", "pytest"]}) == "test"
    assert command_check_kind({"argv": ["python.exe", "-m", "compileall", "."]}) == "compile"
    assert command_check_kind({"argv": ["python", "hello.py"]}) == "run"
    assert command_check_kind({"argv": ["node", "--test"]}) == "test"
    assert command_check_kind({"argv": ["node.exe", "--check", "app.js"]}) == "compile"
    assert command_check_kind({"argv": ["git", "status"]}) is None
