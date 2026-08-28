"""验证工作区路径约束、原子写入和环境变量隔离。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from coding_agent.agents.security import CommandDecision, Workspace, WorkspaceError
from coding_agent.agents.security.command_policy import classify_command
from coding_agent.agents.security.command_policy import (
    CommandDecision as PolicyCommandDecision,
    CommandRequest as PolicyCommandRequest,
    should_inherit_environment_name,
)
from coding_agent.agents.security.workspace import (
    CommandDecision as WorkspaceCommandDecision,
    CommandRequest as WorkspaceCommandRequest,
)


def test_workspace_root_must_exist_and_be_directory(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="does not exist"):
        Workspace(tmp_path / "missing")

    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="must be a directory"):
        Workspace(file_path)


def test_command_policy_split_preserves_class_identity_and_environment_rules() -> None:
    assert CommandDecision is PolicyCommandDecision is WorkspaceCommandDecision
    assert PolicyCommandRequest is WorkspaceCommandRequest
    assert should_inherit_environment_name("KEEP_ME") is True
    assert should_inherit_environment_name("DeepSeek_Api_Key") is False
    assert should_inherit_environment_name("GIT_CONFIG_COUNT") is False
    assert should_inherit_environment_name("CODING_AGENT_DATABASE_URL") is False
    assert should_inherit_environment_name("PGPASSWORD") is False


@pytest.mark.parametrize(
    "unsafe",
    [
        "../escape.txt",
        "a/../../escape.txt",
        "C:relative.txt",
        r"C:\absolute.txt",
        r"\rooted.txt",
        r"\\server\share\file.txt",
        r"\\?\C:\device.txt",
        r"\\.\NUL",
        "name:stream",
        "dir/name:stream",
        "CON.txt",
        "dir/AuX.json",
        "LPT9.",
        "trailing-space ",
        "trailing-dot.",
        "bad|name.txt",
    ],
)
def test_windows_unsafe_paths_are_rejected_on_every_platform(tmp_path: Path, unsafe: str) -> None:
    workspace = Workspace(tmp_path)
    with pytest.raises(WorkspaceError):
        workspace.lexical_path(unsafe)


def test_normal_relative_path_is_accepted(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    assert workspace.lexical_path(r"src\main.py") == tmp_path / "src" / "main.py"


def test_protected_and_credential_paths_are_blocked(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    (tmp_path / ".env").write_text("secret", encoding="utf-8")
    (tmp_path / ".env.local").write_text("secret", encoding="utf-8")
    (tmp_path / "private.pem").write_text("secret", encoding="utf-8")
    (tmp_path / ".env.example").write_text("NAME=", encoding="utf-8")
    workspace = Workspace(tmp_path)

    for relative in (".git/config", ".env", ".env.local", "private.pem"):
        with pytest.raises(WorkspaceError):
            workspace.resolve_existing(relative, expected="file")

    assert workspace.resolve_existing(".env.example", expected="file") == tmp_path / ".env.example"


def test_credential_named_directory_cannot_bypass_protection(tmp_path: Path) -> None:
    credential_directory = tmp_path / ".env"
    credential_directory.mkdir()
    (credential_directory / "nested.txt").write_text("secret", encoding="utf-8")
    workspace = Workspace(tmp_path)

    with pytest.raises(WorkspaceError, match="Credential"):
        workspace.resolve_existing(".env/nested.txt", expected="file")
    with pytest.raises(WorkspaceError, match="Credential"):
        workspace.resolve_new_file(".env/new.txt")


def test_existing_symlink_cannot_escape_workspace(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = root / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    workspace = Workspace(root)
    with pytest.raises(WorkspaceError, match="outside"):
        workspace.resolve_existing("link/secret.txt", expected="file")


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows-specific boundary")
def test_junction_cannot_escape_workspace(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    junction = root / "junction"
    cmd = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    completed = __import__("subprocess").run(
        [os.fspath(cmd), "/d", "/c", "mklink", "/J", os.fspath(junction), os.fspath(outside)],
        capture_output=True,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip("junction creation unavailable")

    workspace = Workspace(root)
    try:
        assert workspace.is_reparse_point(junction)
        with pytest.raises(WorkspaceError, match="outside"):
            workspace.resolve_existing("junction/secret.txt", expected="file")
    finally:
        os.rmdir(junction)


def test_sanitized_environment_removes_secrets_and_workspace_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    fake_bin = root / "bin"
    safe_bin = tmp_path / "safe-bin"
    fake_bin.mkdir(parents=True)
    safe_bin.mkdir()
    workspace = Workspace(root)
    source = {
        "Path": os.pathsep.join((os.fspath(fake_bin), os.fspath(safe_bin), ".")),
        "DeepSeek_Api_Key": "secret",
        "CUSTOM_TOKEN": "secret",
        "PYTHONPATH": "unsafe",
        "GIT_EXTERNAL_DIFF": "unsafe",
        "GIT_CONFIG_COUNT": "1",
        "KEEP_ME": "yes",
    }

    cleaned = workspace.sanitized_environment(source)
    cleaned_upper = {key.upper(): value for key, value in cleaned.items()}
    assert "DEEPSEEK_API_KEY" not in cleaned_upper
    assert "CUSTOM_TOKEN" not in cleaned_upper
    assert "PYTHONPATH" not in cleaned_upper
    assert "GIT_EXTERNAL_DIFF" not in cleaned_upper
    assert "GIT_CONFIG_COUNT" not in cleaned_upper
    assert cleaned["KEEP_ME"] == "yes"
    path_value = next(value for key, value in cleaned.items() if key.upper() == "PATH")
    entries = [Path(entry).resolve() for entry in path_value.split(os.pathsep)]
    assert fake_bin.resolve() not in entries
    assert safe_bin.resolve() in entries
    assert Path(sys.executable).resolve().parent in entries


def test_minimal_child_environment_drops_unrelated_and_database_variables(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    cleaned = workspace.sanitized_environment(
        {
            "PATH": os.fspath(Path(sys.executable).resolve().parent),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\\Windows"),
            "TEMP": os.fspath(tmp_path),
            "KEEP_ME": "not required by child tools",
            "CODING_AGENT_DATABASE_URL": "postgresql://user:secret@localhost/db",
            "PGPASSWORD": "secret",
            "SOME_DATABASE_URI": "postgresql://secret",
        },
        minimal=True,
    )
    names = {name.upper() for name in cleaned}
    assert "SYSTEMROOT" in names
    assert "KEEP_ME" not in names
    assert "CODING_AGENT_DATABASE_URL" not in names
    assert "PGPASSWORD" not in names
    assert "SOME_DATABASE_URI" not in names


def test_command_policy_allow_confirm_and_deny(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    allowed = workspace.prepare_command([sys.executable, "-m", "unittest"], cwd=".")
    assert allowed.decision is CommandDecision.ALLOW

    confirmed = workspace.prepare_command([sys.executable, "-c", "print('ok')"], cwd=".")
    assert confirmed.decision is CommandDecision.CONFIRM
    assert confirmed.argv[2] == "print('ok')"
    assert "print('ok')" in confirmed.display

    if os.name == "nt":
        shell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    else:
        shell_name = shutil.which("sh")
        if shell_name is None:
            pytest.skip("no shell executable available")
        shell = Path(shell_name)
    denied = workspace.prepare_command([os.fspath(shell), "ignored"], cwd=".")
    assert denied.decision is CommandDecision.DENY


def test_normal_git_inspection_is_allowed_for_agent_mode() -> None:
    status, _ = classify_command(
        ["git", "status"],
        [r"C:\\Program Files\\Git\\cmd\\git.exe", "status"],
        python_executable=None,
    )
    diff, _ = classify_command(
        ["git", "diff", "--check"],
        [r"C:\\Program Files\\Git\\cmd\\git.exe", "diff", "--check"],
        python_executable=None,
    )
    assert status is CommandDecision.ALLOW
    assert diff is CommandDecision.ALLOW


def test_node_workspace_checks_are_normal_but_inline_code_is_risky() -> None:
    executable = r"C:\Program Files\nodejs\node.exe"
    check, _ = classify_command(
        ["node", "--check", "src/app.js"],
        [executable, "--check", "src/app.js"],
        python_executable=None,
    )
    test, _ = classify_command(
        ["node", "smoke-test.js"],
        [executable, "smoke-test.js"],
        python_executable=None,
    )
    inline, _ = classify_command(
        ["node", "-e", "process.exit(0)"],
        [executable, "-e", "process.exit(0)"],
        python_executable=None,
    )
    assert check is CommandDecision.ALLOW
    assert test is CommandDecision.ALLOW
    assert inline is CommandDecision.CONFIRM


def test_workspace_path_entry_cannot_shadow_executable(tmp_path: Path) -> None:
    root = tmp_path / "root"
    fake_bin = root / "bin"
    fake_bin.mkdir(parents=True)
    fake_name = "python.exe" if os.name == "nt" else "python"
    (fake_bin / fake_name).write_bytes(b"not an executable")
    workspace = Workspace(root)

    cleaned = workspace.sanitized_environment({"PATH": os.fspath(fake_bin)})
    path_value = next(value for key, value in cleaned.items() if key.upper() == "PATH")
    assert os.fspath(fake_bin.resolve()) not in path_value.split(os.pathsep)
