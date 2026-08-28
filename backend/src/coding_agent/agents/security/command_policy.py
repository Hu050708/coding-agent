"""实现保守的命令风险分类与环境变量继承规则。"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath


class CommandDecision(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class CommandRequest:
    argv: tuple[str, ...]
    resolved_argv: tuple[str, ...]
    cwd: Path
    decision: CommandDecision
    reason: str

    @property
    def display(self) -> str:
        """返回供同步本地确认提示使用的未脱敏命令行。"""

        return subprocess.list2cmdline(list(self.argv))


_SHELL_HOSTS = frozenset(
    {
        "cmd",
        "cmd.exe",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "bash",
        "bash.exe",
        "sh",
        "sh.exe",
        "zsh",
        "wsl",
        "wsl.exe",
        "cscript",
        "cscript.exe",
        "wscript",
        "wscript.exe",
        "mshta",
        "mshta.exe",
    }
)
_DESTRUCTIVE_EXECUTABLES = frozenset(
    {
        "diskpart",
        "diskpart.exe",
        "format",
        "format.com",
        "shutdown",
        "shutdown.exe",
        "runas",
        "runas.exe",
        "sudo",
        "su",
        "takeown",
        "takeown.exe",
        "reg",
        "reg.exe",
        "sc",
        "sc.exe",
    }
)
_DANGEROUS_GIT_SUBCOMMANDS = frozenset(
    {
        "push",
        "pull",
        "fetch",
        "clone",
        "remote",
        "reset",
        "clean",
        "rebase",
        "commit",
        "merge",
        "checkout",
        "switch",
        "branch",
        "tag",
        "gc",
        "reflog",
        "update-ref",
        "filter-branch",
    }
)
_DANGEROUS_GIT_DIFF_OPTIONS = frozenset(
    {
        "--ext-diff",
        "--textconv",
        "--no-index",
        "--output",
        "--output-indicator-new",
        "--output-indicator-old",
        "--output-indicator-context",
    }
)
_SAFE_PYTHON_MODULES = frozenset({"pytest", "unittest", "compileall"})
_UNSAFE_TEST_OPTIONS = frozenset(
    {"-c", "-p", "--rootdir", "--confcutdir", "--basetemp", "--override-ini"}
)
_EXACT_SECRET_ENV_NAMES = frozenset(
    {
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_SECRET",
        "SSH_AUTH_SOCK",
        "SSH_ASKPASS",
        "GIT_ASKPASS",
        "DATABASE_URL",
        "PGDATABASE",
        "PGHOST",
        "PGHOSTADDR",
        "PGPASSFILE",
        "PGPASSWORD",
        "PGPORT",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGUSER",
    }
)
_SECRET_ENV_SUFFIXES = (
    "_API_KEY",
    "_ACCESS_KEY",
    "_TOKEN",
    "_SECRET",
    "_PASSWORD",
    "_PASSWD",
    "_DATABASE_URL",
    "_DATABASE_URI",
    "_DB_URL",
    "_CONNECTION_STRING",
)
_UNSAFE_INHERITED_ENV_PREFIXES = ("GIT_CONFIG_",)
_UNSAFE_INHERITED_ENV_NAMES = frozenset(
    {
        "PYTHONHOME",
        "PYTHONPATH",
        "GIT_EXTERNAL_DIFF",
        "GIT_DIFF_OPTS",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
    }
)

_MINIMAL_CHILD_ENV_NAMES = frozenset(
    {
        "COMSPEC",
        "CONDA_DEFAULT_ENV",
        "CONDA_PREFIX",
        "FORCE_COLOR",
        "LANG",
        "NO_COLOR",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "PATH",
        "PATHEXT",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TERM",
        "TMP",
        "TMPDIR",
        "VIRTUAL_ENV",
        "WINDIR",
    }
)


def should_inherit_environment_name(name: str) -> bool:
    """判断继承的环境变量名对子进程是否安全。"""

    upper_name = name.upper()
    return not (
        upper_name in _EXACT_SECRET_ENV_NAMES
        or upper_name in _UNSAFE_INHERITED_ENV_NAMES
        or upper_name.startswith(_UNSAFE_INHERITED_ENV_PREFIXES)
        or upper_name.endswith(_SECRET_ENV_SUFFIXES)
    )


def should_inherit_minimal_environment_name(name: str) -> bool:
    """判断普通子工具是否需要某个非敏感环境变量。"""

    if not should_inherit_environment_name(name):
        return False
    upper_name = name.upper()
    return upper_name in _MINIMAL_CHILD_ENV_NAMES or upper_name.startswith("LC_")


def classify_command(
    original_argv: Sequence[str],
    resolved_argv: Sequence[str],
    *,
    python_executable: str | os.PathLike[str] | None,
) -> tuple[CommandDecision, str]:
    """在不执行文件或进程 I/O 的情况下，对已解析命令参数进行风险分类。"""

    # 第一步：无条件拒绝 shell、批处理、破坏性和提权程序。
    executable_name = Path(resolved_argv[0]).name.casefold()
    suffix = Path(resolved_argv[0]).suffix.casefold()
    if suffix in {".bat", ".cmd"} or executable_name in _SHELL_HOSTS:
        return CommandDecision.DENY, "Shell hosts and batch scripts are outside the P0 command contract."
    if executable_name in _DESTRUCTIVE_EXECUTABLES:
        return CommandDecision.DENY, "The executable is classified as destructive or privileged."

    # 第二步：仅放行固定的 Python 检查模块，任意脚本执行都需要确认。
    same_python = python_executable is not None and (
        _normcase_path(Path(resolved_argv[0])) == _normcase_path(Path(python_executable))
    )
    if same_python:
        if (
            len(original_argv) >= 3
            and original_argv[1] == "-m"
            and original_argv[2] in _SAFE_PYTHON_MODULES
            and not unsafe_test_arguments(original_argv[3:])
        ):
            return CommandDecision.ALLOW, "A fixed test or compile module is allowed."
        return CommandDecision.CONFIRM, "Arbitrary Python execution requires confirmation."

    # 第三步：Git 仅放行经过选项检查的 status/diff，其余子命令拒绝或确认。
    if executable_name in {"git", "git.exe"}:
        if len(original_argv) < 2 or original_argv[1].startswith("-"):
            return CommandDecision.DENY, "Git global options are not accepted by the P0 policy."
        subcommand = original_argv[1].casefold()
        if subcommand in _DANGEROUS_GIT_SUBCOMMANDS:
            return CommandDecision.DENY, "Remote or history-changing Git commands are denied."
        if subcommand == "status":
            return CommandDecision.ALLOW, "Git status is a normal workspace inspection."
        if subcommand == "diff":
            for argument in original_argv[2:]:
                option = argument.split("=", 1)[0].casefold()
                if option in _DANGEROUS_GIT_DIFF_OPTIONS:
                    return CommandDecision.DENY, "The requested git diff option may execute or write externally."
            return CommandDecision.ALLOW, "Git diff is a normal workspace inspection."
        return CommandDecision.CONFIRM, "This Git subcommand is not in the fixed read-only allowlist."

    # 第四步：Node 只放行固定检查形式，所有未知可执行文件采用确认优先策略。
    if executable_name in {"node", "node.exe"} and _safe_node_arguments(original_argv[1:]):
        return CommandDecision.ALLOW, "A workspace-local Node check or test is allowed."

    return CommandDecision.CONFIRM, "The executable is not in the fixed read-only allowlist."


def unsafe_test_arguments(arguments: Sequence[str]) -> bool:
    for index, argument in enumerate(arguments):
        option = argument.split("=", 1)[0]
        if option in _UNSAFE_TEST_OPTIONS:
            return True
        if option.startswith("-"):
            continue
        windows = PureWindowsPath(argument)
        parts = PurePosixPath(argument.replace("\\", "/")).parts
        if windows.drive or windows.root or ".." in parts:
            return True
        if index and arguments[index - 1] in _UNSAFE_TEST_OPTIONS:
            return True
    return False


def _safe_node_arguments(arguments: Sequence[str]) -> bool:
    if tuple(arguments) in {("--version",), ("-v",)}:
        return True
    if not arguments:
        return False
    if arguments[0] in {"--check", "--test"}:
        paths = arguments[1:]
    elif not arguments[0].startswith("-"):
        paths = arguments
    else:
        return False
    if not paths:
        return arguments[0] == "--test"
    for value in paths:
        windows = PureWindowsPath(value)
        parts = PurePosixPath(value.replace("\\", "/")).parts
        if value.startswith("-") or windows.drive or windows.root or ".." in parts:
            return False
    return True


def _normcase_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


__all__ = [
    "CommandDecision",
    "CommandRequest",
    "classify_command",
    "should_inherit_environment_name",
    "should_inherit_minimal_environment_name",
    "unsafe_test_arguments",
]
