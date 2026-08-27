from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping, Sequence

from .command_policy import (
    CommandDecision,
    CommandRequest,
    classify_command,
    should_inherit_environment_name,
)


class WorkspaceError(Exception):
    """A safe, user-facing workspace or command-policy failure."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*')
_WINDOWS_DEVICES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)
_DEFAULT_IGNORED_COMPONENTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
    }
)
_PRIVATE_SUFFIXES = frozenset({".key", ".pem", ".p12", ".pfx", ".der", ".crt", ".cer"})
_PRIVATE_NAMES = frozenset(
    {
        "credentials",
        "credentials.json",
        "secrets.json",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    }
)


def _normcase_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


class Workspace:
    """Workspace-scoped path resolution and command policy.

    The class constrains ClearLoop's own file operations. It deliberately does
    not claim to sandbox an approved subprocess.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        trace_dir_name: str = ".clearloop-traces",
    ) -> None:
        root_path = Path(root).expanduser()
        try:
            resolved = root_path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise WorkspaceError("workspace_not_found", "The workspace directory does not exist.") from exc
        if not resolved.is_dir():
            raise WorkspaceError("workspace_not_directory", "The workspace root must be a directory.")
        self.root = resolved
        self.trace_dir_name = trace_dir_name.casefold()

    # ------------------------------------------------------------------
    # Path validation and containment
    # ------------------------------------------------------------------
    def relative_parts(self, value: str) -> tuple[str, ...]:
        if not isinstance(value, str):
            raise WorkspaceError("invalid_path", "A path must be a string.")
        if not value or "\x00" in value:
            raise WorkspaceError("invalid_path", "A path must be a non-empty relative path.")
        if any(ord(character) < 32 for character in value):
            raise WorkspaceError("invalid_path", "Control characters are not allowed in paths.")

        windows_path = PureWindowsPath(value)
        posix_path = PurePosixPath(value.replace("\\", "/"))
        if windows_path.drive or windows_path.root or windows_path.anchor or posix_path.is_absolute():
            raise WorkspaceError("absolute_path", "Only workspace-relative paths are allowed.")

        parts = tuple(part for part in posix_path.parts if part not in {"", "."})
        for part in parts:
            if part == "..":
                raise WorkspaceError("path_traversal", "Parent-directory traversal is not allowed.")
            if part.endswith((" ", ".")):
                raise WorkspaceError("invalid_windows_path", "Path components may not end in a space or dot.")
            if any(character in _WINDOWS_INVALID_CHARS for character in part):
                raise WorkspaceError("invalid_windows_path", "The path contains a Windows-reserved character.")
            device_stem = part.split(".", 1)[0].upper()
            if device_stem in _WINDOWS_DEVICES:
                raise WorkspaceError("reserved_windows_name", "The path uses a reserved Windows device name.")
        return parts

    def lexical_path(self, relative: str) -> Path:
        return self.root.joinpath(*self.relative_parts(relative))

    def _ensure_contained(self, path: Path) -> None:
        try:
            common = os.path.commonpath((_normcase_path(self.root), _normcase_path(path)))
        except ValueError as exc:
            raise WorkspaceError("path_outside_workspace", "The path resolves outside the workspace.") from exc
        if common != _normcase_path(self.root):
            raise WorkspaceError("path_outside_workspace", "The path resolves outside the workspace.")

    @staticmethod
    def is_reparse_point(path: Path) -> bool:
        try:
            metadata = path.lstat()
        except OSError:
            return False
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return path.is_symlink() or bool(attributes & reparse_flag)

    def resolve_existing(
        self,
        relative: str,
        *,
        expected: str | None = None,
        allow_reparse: bool = True,
        operation: str = "read",
    ) -> Path:
        parts = self.relative_parts(relative)
        self._check_protected(parts, operation=operation)
        lexical = self.root.joinpath(*parts)
        if not os.path.lexists(lexical):
            raise WorkspaceError("path_not_found", "The requested workspace path does not exist.")
        if not allow_reparse and lexical != self.root and self.is_reparse_point(lexical):
            raise WorkspaceError("reparse_point_not_allowed", "Directory links are not followed by this operation.")
        try:
            resolved = lexical.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise WorkspaceError("unresolvable_path", "The requested path cannot be resolved safely.") from exc
        self._ensure_contained(resolved)
        if expected == "file" and not resolved.is_file():
            raise WorkspaceError("not_a_file", "The requested path is not a regular file.")
        if expected == "directory" and not resolved.is_dir():
            raise WorkspaceError("not_a_directory", "The requested path is not a directory.")
        return resolved

    def resolve_new_file(self, relative: str) -> Path:
        parts = self.relative_parts(relative)
        if not parts:
            raise WorkspaceError("invalid_path", "A file path is required.")
        self._check_protected(parts, operation="write")
        target = self.root.joinpath(*parts)
        if os.path.lexists(target):
            raise WorkspaceError("path_exists", "write_file only creates new files; the target already exists.")
        parent_lexical = target.parent
        if not os.path.lexists(parent_lexical):
            raise WorkspaceError("parent_not_found", "The target parent directory does not exist.")
        try:
            parent = parent_lexical.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise WorkspaceError("unresolvable_parent", "The target parent cannot be resolved safely.") from exc
        self._ensure_contained(parent)
        if not parent.is_dir():
            raise WorkspaceError("parent_not_directory", "The target parent is not a directory.")
        resolved_target = parent / target.name
        self._ensure_contained(resolved_target)
        return resolved_target

    def relative_label(self, path: Path) -> str:
        self._ensure_contained(path)
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("path_outside_workspace", "The path is outside the workspace.") from exc
        return relative.as_posix() or "."

    def should_skip_listing(self, relative: str) -> bool:
        parts = self.relative_parts(relative)
        return any(self._is_ignored_component(part) for part in parts) or self._is_credential_name(
            parts[-1] if parts else ""
        )

    def _check_protected(self, parts: Sequence[str], *, operation: str) -> None:
        if any(self._is_ignored_component(part) for part in parts):
            raise WorkspaceError("protected_path", "The requested path is protected from tool access.")
        if any(self._is_credential_name(part) for part in parts):
            raise WorkspaceError("protected_credential", "Credential and private-key files are protected.")

    def _is_ignored_component(self, component: str) -> bool:
        lowered = component.casefold()
        return lowered in _DEFAULT_IGNORED_COMPONENTS or lowered == self.trace_dir_name

    @staticmethod
    def _is_credential_name(name: str) -> bool:
        lowered = name.casefold()
        if lowered == ".env.example":
            return False
        if lowered == ".env" or lowered.startswith(".env."):
            return True
        if lowered in _PRIVATE_NAMES or Path(lowered).suffix in _PRIVATE_SUFFIXES:
            return True
        return lowered.startswith(("id_rsa.", "id_dsa.", "id_ecdsa.", "id_ed25519."))

    # ------------------------------------------------------------------
    # Atomic file publication
    # ------------------------------------------------------------------
    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def sha256_path(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def atomic_create(self, relative: str, data: bytes) -> Path:
        """Publish a new file atomically without ever replacing an existing one."""

        target = self.resolve_new_file(relative)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())

            # Revalidate immediately before publication. os.link is the
            # fail-if-exists atomic step; unlike os.replace it cannot clobber a
            # file created by a racing process.
            current_target = self.resolve_new_file(relative)
            if current_target != target:
                raise WorkspaceError("path_changed", "The target path changed before publication.")
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise WorkspaceError(
                    "path_exists", "The target appeared before write_file could publish the new file."
                ) from exc
            except OSError as exc:
                raise WorkspaceError(
                    "atomic_create_unsupported",
                    "The filesystem could not atomically publish a create-only file.",
                ) from exc
            return target
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def atomic_replace(self, relative: str, data: bytes, *, expected_sha256: str) -> Path:
        target = self.resolve_existing(relative, expected="file", operation="write")
        if self.sha256_path(target) != expected_sha256:
            raise WorkspaceError("stale_file", "The file changed after it was read; read it again before editing.")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))
            except OSError:
                pass

            current_target = self.resolve_existing(relative, expected="file", operation="write")
            if current_target != target or self.sha256_path(current_target) != expected_sha256:
                raise WorkspaceError("stale_file", "The file changed before the edit could be published.")
            try:
                os.replace(temporary, current_target)
            except OSError as exc:
                raise WorkspaceError("atomic_replace_failed", "The edited file could not be published.") from exc
            return current_target
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Child environment and command policy
    # ------------------------------------------------------------------
    def sanitized_environment(self, source: Mapping[str, str] | None = None) -> dict[str, str]:
        source_environment = os.environ if source is None else source
        cleaned: dict[str, str] = {}
        for name, value in source_environment.items():
            if not should_inherit_environment_name(name):
                continue
            cleaned[name] = value

        path_name = next((name for name in cleaned if name.upper() == "PATH"), "PATH")
        raw_path = cleaned.get(path_name, "")
        safe_entries: list[str] = []
        seen: set[str] = set()
        for entry in raw_path.split(os.pathsep):
            entry = entry.strip().strip('"')
            if not entry:
                continue
            candidate = Path(os.path.expandvars(entry))
            if not candidate.is_absolute():
                continue
            try:
                resolved = candidate.resolve(strict=False)
            except (OSError, RuntimeError):
                continue
            normalized = _normcase_path(resolved)
            if normalized in seen:
                continue
            try:
                self._ensure_contained(resolved)
            except WorkspaceError:
                pass
            else:
                # A PATH entry inside the repository could shadow python/git.
                continue
            seen.add(normalized)
            safe_entries.append(os.fspath(resolved))

        executable_dir = os.fspath(Path(sys.executable).resolve().parent)
        if _normcase_path(Path(executable_dir)) not in seen:
            safe_entries.insert(0, executable_dir)
        cleaned[path_name] = os.pathsep.join(safe_entries)
        cleaned["NoDefaultCurrentDirectoryInExePath"] = "1"
        return cleaned

    def resolve_executable(self, executable: str, *, cwd: Path, environment: Mapping[str, str]) -> Path:
        if not isinstance(executable, str) or not executable or "\x00" in executable:
            raise WorkspaceError("invalid_executable", "The command executable is invalid.")
        windows = PureWindowsPath(executable)
        has_path_syntax = bool(windows.drive or windows.root or "/" in executable or "\\" in executable)
        if has_path_syntax:
            if windows.drive or windows.root:
                candidate = Path(executable)
            else:
                candidate = cwd.joinpath(*self.relative_parts(executable))
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise WorkspaceError("executable_not_found", "The requested executable was not found.") from exc
        else:
            path_value = next((value for name, value in environment.items() if name.upper() == "PATH"), "")
            found = shutil.which(executable, path=path_value)
            if found is None:
                raise WorkspaceError("executable_not_found", "The requested executable was not found.")
            resolved = Path(found).resolve(strict=True)

        if not resolved.is_file():
            raise WorkspaceError("executable_not_file", "The resolved executable is not a file.")
        if not has_path_syntax:
            try:
                self._ensure_contained(resolved)
            except WorkspaceError:
                pass
            else:
                raise WorkspaceError(
                    "workspace_executable_shadowing",
                    "A workspace-local executable may not shadow a PATH command.",
                )
        return resolved

    def prepare_command(self, argv: Sequence[str], *, cwd: str = ".") -> CommandRequest:
        if isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence) or not argv:
            raise WorkspaceError("invalid_argv", "argv must be a non-empty array of strings.")
        if len(argv) > 64:
            raise WorkspaceError("invalid_argv", "argv contains too many elements.")
        normalized: list[str] = []
        total_characters = 0
        for argument in argv:
            if not isinstance(argument, str) or not argument or "\x00" in argument:
                raise WorkspaceError("invalid_argv", "Every argv element must be a non-empty string.")
            if len(argument) > 4096:
                raise WorkspaceError("invalid_argv", "An argv element is too long.")
            total_characters += len(argument)
            normalized.append(argument)
        if total_characters > 30_000:
            raise WorkspaceError("invalid_argv", "The command line is too long.")

        resolved_cwd = self.resolve_existing(cwd, expected="directory", operation="execute")
        environment = self.sanitized_environment()
        executable = self.resolve_executable(normalized[0], cwd=resolved_cwd, environment=environment)
        resolved_argv = (os.fspath(executable), *normalized[1:])
        try:
            current_python: Path | None = Path(sys.executable).resolve()
        except OSError:
            current_python = None
        decision, reason = classify_command(
            normalized,
            resolved_argv,
            python_executable=current_python,
        )
        return CommandRequest(
            argv=tuple(normalized),
            resolved_argv=tuple(resolved_argv),
            cwd=resolved_cwd,
            decision=decision,
            reason=reason,
        )

__all__ = [
    "CommandDecision",
    "CommandRequest",
    "Workspace",
    "WorkspaceError",
]
