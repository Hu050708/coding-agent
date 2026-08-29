"""实现路径校验和受限文件访问的文件系统沙箱。"""

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
    should_inherit_minimal_environment_name,
)


class WorkspaceError(Exception):
    """可安全展示给用户的工作区或命令策略错误。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        """创建可安全跨越工具边界的工作区错误。

        :param code: 稳定机器可读错误码。
        :param message: 不含敏感内容的用户可见说明。
        :param retryable: 模型重新读取或调整参数后是否可能成功。
        """

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
    """生成用于安全包含关系比较的绝对平台路径键。

    :param path: 待规范化路径。
    :return: 应用绝对化与平台大小写规则后的字符串。
    """

    return os.path.normcase(os.path.abspath(os.fspath(path)))


class Workspace:
    """工作区范围的路径解析和命令策略。

    本类约束 Coding Agent 自身的文件操作，但不宣称能沙箱化已经批准的子进程。
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        trace_dir_name: str = ".coding-agent-traces",
    ) -> None:
        """创建以一个现有目录为根的文件和命令安全边界。

        :param root: Agent 被允许操作的工作区根目录。
        :param trace_dir_name: 工作区内应始终排除的诊断目录名称。
        :raises WorkspaceError: 根目录不存在、无法解析或不是目录。
        """

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
    # 路径校验与工作区包含关系
    # ------------------------------------------------------------------
    def relative_parts(self, value: str) -> tuple[str, ...]:
        """把用户路径拆成安全的相对路径片段，并拒绝跨平台危险写法。

        :param value: 模型或用户提供的工作区相对路径文本。
        :return: 已移除空段和当前目录段的安全路径片段。
        :raises WorkspaceError: 路径为空、绝对、穿越父目录或含平台危险字符。
        """

        # 第一步：同时按 Windows 和 POSIX 语义检查绝对路径及父目录穿越。
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

        # 第二步：逐段排除 Windows 尾随字符、非法字符和保留设备名。
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
        """在不解析链接的情况下拼接工作区词法路径。

        :param relative: 已受相对路径规则约束的路径文本。
        :return: 以工作区根目录为基准拼接的路径。
        """

        return self.root.joinpath(*self.relative_parts(relative))

    def _ensure_contained(self, path: Path) -> None:
        """确认路径的规范绝对形式仍位于工作区根目录内。

        :param path: 待检查的已解析或候选路径。
        :raises WorkspaceError: 路径跨盘符或位于工作区之外。
        """

        try:
            common = os.path.commonpath((_normcase_path(self.root), _normcase_path(path)))
        except ValueError as exc:
            raise WorkspaceError("path_outside_workspace", "The path resolves outside the workspace.") from exc
        if common != _normcase_path(self.root):
            raise WorkspaceError("path_outside_workspace", "The path resolves outside the workspace.")

    @staticmethod
    def is_reparse_point(path: Path) -> bool:
        """判断路径是否为符号链接或 Windows 重解析点。

        :param path: 待检查路径。
        :return: 检测到链接或重解析属性时返回 ``True``。
        """

        try:
            metadata = path.lstat()
        except OSError:
            return False
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return path.is_symlink() or bool(attributes & reparse_flag)

    def _ensure_no_reparse_components(self, parts: Sequence[str]) -> None:
        """拒绝路径中任何已存在的符号链接或 Windows 重解析点。

        创建目录和删除文件属于结构性修改，不允许借助工作区内链接间接改变目标。

        :param parts: 已校验的工作区相对路径片段。
        :raises WorkspaceError: 任一现有路径组件是链接或重解析点。
        """

        current = self.root
        for part in parts:
            current = current / part
            if os.path.lexists(current) and self.is_reparse_point(current):
                raise WorkspaceError(
                    "reparse_point_not_allowed",
                    "Directory creation and file deletion do not follow links.",
                )

    def resolve_existing(
        self,
        relative: str,
        *,
        expected: str | None = None,
        allow_reparse: bool = True,
        operation: str = "read",
    ) -> Path:
        """解析并校验已存在路径，确保最终目标仍位于工作区内。

        :param relative: 工作区相对路径。
        :param expected: 可选目标类型，支持 ``file`` 或 ``directory``。
        :param allow_reparse: 是否允许入口本身为链接或重解析点。
        :param operation: ``read``、``write`` 或 ``execute``，用于保护策略判断。
        :return: 解析链接后的安全绝对路径。
        :raises WorkspaceError: 路径受保护、不存在、越界或类型不符。
        """

        # 第一步：先检查词法路径和受保护组件，拒绝不存在或禁止访问的入口。
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
        # 第二步：对解析链接后的真实路径再次检查工作区包含关系和预期类型。
        self._ensure_contained(resolved)
        if expected == "file" and not resolved.is_file():
            raise WorkspaceError("not_a_file", "The requested path is not a regular file.")
        if expected == "directory" and not resolved.is_dir():
            raise WorkspaceError("not_a_directory", "The requested path is not a directory.")
        return resolved

    def resolve_new_file(self, relative: str) -> Path:
        """解析尚不存在的新文件路径，并确认其父目录安全可写。

        :param relative: 新文件的工作区相对路径。
        :return: 使用真实安全父目录重建的目标绝对路径。
        :raises WorkspaceError: 目标已存在、父目录无效、路径受保护或越界。
        """

        # 第一步：校验相对路径及受保护目录，并保证目标当前确实不存在。
        parts = self.relative_parts(relative)
        if not parts:
            raise WorkspaceError("invalid_path", "A file path is required.")
        self._check_protected(parts, operation="write")
        target = self.root.joinpath(*parts)
        if os.path.lexists(target):
            raise WorkspaceError("path_exists", "write_file only creates new files; the target already exists.")
        # 第二步：解析真实父目录，阻止符号链接把写入位置带出工作区。
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
        # 第三步：使用已验证的真实父目录重建目标，并再次确认包含关系。
        resolved_target = parent / target.name
        self._ensure_contained(resolved_target)
        return resolved_target

    def relative_label(self, path: Path) -> str:
        """把工作区内绝对路径转换为稳定 POSIX 相对标签。

        :param path: 已解析或候选绝对路径。
        :return: 使用正斜杠的相对路径；根目录返回 ``.``。
        :raises WorkspaceError: 路径不在工作区内。
        """

        self._ensure_contained(path)
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("path_outside_workspace", "The path is outside the workspace.") from exc
        return relative.as_posix() or "."

    def should_skip_listing(self, relative: str) -> bool:
        """判断目录枚举是否应隐藏某个路径。

        :param relative: 工作区相对路径。
        :return: 路径包含缓存、依赖、跟踪目录或凭据文件时返回 ``True``。
        """

        parts = self.relative_parts(relative)
        return any(self._is_ignored_component(part) for part in parts) or self._is_credential_name(
            parts[-1] if parts else ""
        )

    def _check_protected(self, parts: Sequence[str], *, operation: str) -> None:
        """拒绝访问缓存、依赖目录及凭据文件。

        :param parts: 已校验的相对路径片段。
        :param operation: 触发检查的操作名称，用于调用语义说明。
        :raises WorkspaceError: 路径命中保护规则。
        """

        if any(self._is_ignored_component(part) for part in parts):
            raise WorkspaceError("protected_path", "The requested path is protected from tool access.")
        if any(self._is_credential_name(part) for part in parts):
            raise WorkspaceError("protected_credential", "Credential and private-key files are protected.")

    def _is_ignored_component(self, component: str) -> bool:
        """判断单个路径片段是否属于固定忽略目录。

        :param component: 单个文件或目录名称。
        :return: 名称命中依赖、缓存或诊断目录规则时返回 ``True``。
        """

        lowered = component.casefold()
        return lowered in _DEFAULT_IGNORED_COMPONENTS or lowered == self.trace_dir_name

    @staticmethod
    def _is_credential_name(name: str) -> bool:
        """判断文件名是否可能包含凭据或私钥。

        :param name: 单个文件名。
        :return: 名称命中环境文件、密钥或证书规则时返回 ``True``。
        """

        lowered = name.casefold()
        if lowered == ".env.example":
            return False
        if lowered == ".env" or lowered.startswith(".env."):
            return True
        if lowered in _PRIVATE_NAMES or Path(lowered).suffix in _PRIVATE_SUFFIXES:
            return True
        return lowered.startswith(("id_rsa.", "id_dsa.", "id_ecdsa.", "id_ed25519."))

    # ------------------------------------------------------------------
    # 原子文件发布
    # ------------------------------------------------------------------
    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        """计算字节内容的 SHA-256 摘要。

        :param data: 待哈希字节。
        :return: 64 位小写十六进制摘要。
        """

        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def sha256_path(path: Path) -> str:
        """流式计算文件当前内容的 SHA-256 摘要。

        :param path: 待读取文件路径。
        :return: 64 位小写十六进制摘要。
        """

        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def create_directory(
        self, relative: str, *, parents: bool = True
    ) -> tuple[Path, int]:
        """安全创建一个工作区目录，并可按顺序创建缺失父目录。

        已存在的普通目录按幂等成功处理。任一路径组件是文件、链接、受保护路径或
        解析到工作区之外时都会拒绝；创建中途失败会尽力移除本次创建的空目录。

        :param relative: 要创建的工作区相对目录路径。
        :param parents: 是否同时创建缺失的父目录。
        :return: 规范目录路径和本次实际创建的目录数量。
        :raises WorkspaceError: 路径不安全、父目录缺失或目录创建失败。
        """

        parts = self.relative_parts(relative)
        if not parts:
            raise WorkspaceError("invalid_path", "A non-root directory path is required.")
        self._check_protected(parts, operation="write")
        self._ensure_no_reparse_components(parts)
        created: list[Path] = []
        current = self.root
        try:
            for index, part in enumerate(parts):
                lexical = self.root.joinpath(*parts[: index + 1])
                if os.path.lexists(lexical):
                    self._ensure_no_reparse_components(parts[: index + 1])
                    try:
                        resolved = lexical.resolve(strict=True)
                    except (OSError, RuntimeError) as exc:
                        raise WorkspaceError(
                            "unresolvable_path", "The directory path cannot be resolved safely."
                        ) from exc
                    self._ensure_contained(resolved)
                    if not resolved.is_dir():
                        raise WorkspaceError(
                            "parent_not_directory",
                            "A directory path component is not a directory.",
                        )
                    current = resolved
                    continue

                if not parents and index != len(parts) - 1:
                    raise WorkspaceError(
                        "parent_not_found", "The target parent directory does not exist."
                    )
                candidate = current / part
                self._ensure_contained(candidate)
                try:
                    candidate.mkdir()
                    created.append(candidate)
                except FileExistsError:
                    # 并发创建按幂等成功处理，但仍须重新验证类型和链接属性。
                    pass
                except OSError as exc:
                    raise WorkspaceError(
                        "directory_create_failed", "The directory could not be created."
                    ) from exc
                self._ensure_no_reparse_components(parts[: index + 1])
                try:
                    resolved = lexical.resolve(strict=True)
                except (OSError, RuntimeError) as exc:
                    raise WorkspaceError(
                        "unresolvable_path", "The created directory cannot be resolved safely."
                    ) from exc
                self._ensure_contained(resolved)
                if not resolved.is_dir():
                    raise WorkspaceError(
                        "parent_not_directory", "The created path is not a directory."
                    )
                current = resolved
            return current, len(created)
        except Exception:
            for directory in reversed(created):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise

    def atomic_create(self, relative: str, data: bytes) -> Path:
        """原子发布新文件，任何情况下都不覆盖已有目标。

        :param relative: 新文件工作区相对路径。
        :param data: 已完成编码的完整文件字节。
        :return: 成功发布的新文件绝对路径。
        :raises WorkspaceError: 路径不安全、目标出现或文件系统不支持原子仅创建。
        """

        # 第一步：在目标目录创建临时文件，完整写入并刷新到磁盘。
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

            # 第二步：发布前重新校验路径。os.link 提供“已存在即失败”的原子步骤，
            # 与 os.replace 不同，它不会覆盖并发进程刚创建的文件。
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
        """仅在内容哈希未变化时，以临时文件原子替换已有文件。

        :param relative: 已有文件的工作区相对路径。
        :param data: 要发布的完整新文件字节。
        :param expected_sha256: 最近读取时获得的原文件内容哈希。
        :return: 成功替换的目标绝对路径。
        :raises WorkspaceError: 文件并发变化、路径不安全或原子发布失败。
        """

        # 第一步：写入临时文件并尽量继承原文件权限。
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

            # 第二步：发布前重新解析路径并比对哈希，阻止检查与使用之间的并发修改。
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

    def delete_file(
        self,
        relative: str,
        *,
        expected_sha256: str,
        max_file_bytes: int,
    ) -> tuple[str, int]:
        """仅在普通文件内容未变化时删除一个工作区文件。

        :param relative: 待删除文件的工作区相对路径。
        :param expected_sha256: 最近一次读取获得的完整文件哈希。
        :param max_file_bytes: 允许删除的文件大小上限。
        :return: 删除前的规范相对路径和字节数。
        :raises WorkspaceError: 文件越界、受保护、过大、变化或无法删除。
        """

        parts = self.relative_parts(relative)
        if not parts:
            raise WorkspaceError("invalid_path", "A file path is required.")
        self._check_protected(parts, operation="write")
        self._ensure_no_reparse_components(parts)
        target = self.resolve_existing(
            relative,
            expected="file",
            allow_reparse=False,
            operation="write",
        )
        try:
            size = target.stat().st_size
        except OSError as exc:
            raise WorkspaceError("file_stat_failed", "The file metadata could not be read.") from exc
        if size > max_file_bytes:
            raise WorkspaceError(
                "file_too_large", f"The file exceeds the {max_file_bytes}-byte deletion limit."
            )
        if self.sha256_path(target) != expected_sha256:
            raise WorkspaceError(
                "stale_file",
                "The file changed after it was read; read it again before deleting.",
                retryable=True,
            )
        label = self.relative_label(target)

        # 删除前重新解析路径、拒绝链接并复核大小和哈希，降低检查与使用间的竞态风险。
        self._ensure_no_reparse_components(parts)
        try:
            current = self.resolve_existing(
                relative,
                expected="file",
                allow_reparse=False,
                operation="write",
            )
        except WorkspaceError as exc:
            if exc.code == "path_not_found":
                raise WorkspaceError(
                    "stale_file",
                    "The file disappeared before deletion.",
                    retryable=True,
                ) from exc
            raise
        try:
            current_size = current.stat().st_size
        except OSError as exc:
            raise WorkspaceError("file_stat_failed", "The file metadata could not be read.") from exc
        if current != target or current_size != size or self.sha256_path(current) != expected_sha256:
            raise WorkspaceError(
                "stale_file",
                "The file changed before deletion; read it again before deleting.",
                retryable=True,
            )
        try:
            current.unlink()
        except FileNotFoundError as exc:
            raise WorkspaceError(
                "stale_file", "The file disappeared before deletion.", retryable=True
            ) from exc
        except OSError as exc:
            raise WorkspaceError("file_delete_failed", "The file could not be deleted.") from exc
        return label, size

    # ------------------------------------------------------------------
    # 子进程环境与命令策略
    # ------------------------------------------------------------------
    def sanitized_environment(
        self,
        source: Mapping[str, str] | None = None,
        *,
        minimal: bool = False,
    ) -> dict[str, str]:
        """构建不含敏感信息的子进程环境。

        命令执行使用 ``minimal=True``。较宽松形式仅用于需要安全解析 PATH 的兼容
        调用方；两种形式都不等同于操作系统级沙箱。

        :param source: 候选环境变量映射；省略时读取当前进程环境。
        :param minimal: 是否只保留普通命令运行所需的最小变量集合。
        :return: 已移除凭据、危险变量和工作区 PATH 项的新环境字典。
        """

        # 第一步：按模式筛选允许继承的环境变量。
        source_environment = os.environ if source is None else source
        cleaned: dict[str, str] = {}
        for name, value in source_environment.items():
            allowed = (
                should_inherit_minimal_environment_name(name)
                if minimal
                else should_inherit_environment_name(name)
            )
            if not allowed:
                continue
            cleaned[name] = value

        # 第二步：规范化、去重 PATH，并剔除工作区内部目录以防可执行文件劫持。
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
                # 仓库内的 PATH 项可能伪装 python、git 等可信命令。
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
        """按受控 PATH 解析可执行文件，并拒绝工作区内的同名命令劫持。

        :param executable: ``argv[0]`` 中的命令名或路径。
        :param cwd: 已解析的工作区内命令工作目录。
        :param environment: 已脱敏且规范化 PATH 的子进程环境。
        :return: 实际将被执行的现有普通文件绝对路径。
        :raises WorkspaceError: 名称非法、文件不存在或工作区命令遮蔽 PATH。
        """

        # 第一步：带路径语法的名称相对工作目录解析，普通名称只通过脱敏 PATH 查找。
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

        # 第二步：确认目标是文件；PATH 命令还必须位于工作区之外。
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
        """校验命令参数、解析执行目标，并返回策略分类所需的不可变请求。

        :param argv: 不经 shell 解释的非空命令参数序列。
        :param cwd: 命令工作区相对目录，默认为工作区根目录。
        :return: 包含原参数、可信可执行路径、目录和风险决定的请求。
        :raises WorkspaceError: 参数、目录或可执行文件不满足安全约束。
        """

        # 第一步：限制参数数量、单项长度和命令行总长度。
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

        # 第二步：使用脱敏环境解析可执行文件，再基于原始及解析后参数评估风险。
        resolved_cwd = self.resolve_existing(cwd, expected="directory", operation="execute")
        environment = self.sanitized_environment(minimal=True)
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
