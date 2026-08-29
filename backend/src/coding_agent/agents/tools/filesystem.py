"""基于已校验工作区抽象实现文件系统工具。"""

import codecs
import fnmatch
import hashlib
import os
import re
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from coding_agent.agents.security.workspace import Workspace, WorkspaceError

from .contracts import (
    ToolError,
    optional_boolean,
    optional_integer,
    optional_string,
    reject_unknown,
    require_string,
)


_LIST_SCAN_LIMIT = 10_000


def list_files(workspace: Workspace, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """按稳定顺序递归列出文件，同时限制返回量和实际扫描量。

    :param workspace: 提供路径解析、保护规则和链接检测的工作区对象。
    :param arguments: 起始目录、可选 glob 和最大返回条目数。
    :return: 包含文件条目、扫描统计和截断标志的工具数据。
    :raises ToolError: 参数或 glob 不合法。
    :raises WorkspaceError: 目标目录越界、受保护或不存在。
    """

    # 第一步：校验目录、可选 glob 和返回数量上限。
    reject_unknown(arguments, {"path", "glob", "max_entries"})
    relative_directory = require_string(arguments, "path", max_length=1024)
    pattern = optional_string(arguments, "glob", max_length=256)
    if pattern is not None:
        _validate_glob(pattern)
    max_entries = optional_integer(
        arguments, "max_entries", default=500, minimum=1, maximum=500
    )

    start = workspace.resolve_existing(
        relative_directory,
        expected="directory",
        allow_reparse=False,
        operation="read",
    )
    entries: list[dict[str, Any]] = []
    skipped_errors = 0
    truncated = False
    scanned = 0
    scan_limit_reached = False
    stack = [start]

    # 第二步：使用显式栈深度优先遍历，避免递归深度受目录层级影响。
    while stack and not truncated and not scan_limit_reached:
        directory = stack.pop()
        try:
            children: list[os.DirEntry[str]] = []
            with os.scandir(directory) as iterator:
                for child in iterator:
                    if scanned >= _LIST_SCAN_LIMIT:
                        scan_limit_reached = True
                        break
                    scanned += 1
                    children.append(child)
            children.sort(key=lambda item: (item.name.casefold(), item.name))
        except OSError:
            skipped_errors += 1
            continue

        # 第三步：识别条目类型；不跟随重解析点，并跳过受保护路径。
        directories_to_visit: list[Path] = []
        for child in children:
            child_path = Path(child.path)
            try:
                relative = workspace.relative_label(child_path)
                if workspace.should_skip_listing(relative):
                    continue
                is_reparse = _dir_entry_is_reparse(child)
                if is_reparse:
                    kind = "link"
                    size = None
                elif child.is_dir(follow_symlinks=False):
                    kind = "directory"
                    size = None
                    directories_to_visit.append(child_path)
                elif child.is_file(follow_symlinks=False):
                    kind = "file"
                    size = child.stat(follow_symlinks=False).st_size
                else:
                    kind = "other"
                    size = None
            except (OSError, WorkspaceError):
                skipped_errors += 1
                continue

            if pattern is not None and not fnmatch.fnmatchcase(relative.casefold(), pattern.casefold()):
                continue
            if len(entries) >= max_entries:
                truncated = True
                break
            item: dict[str, Any] = {"path": relative, "type": kind}
            if size is not None:
                item["size_bytes"] = size
            entries.append(item)

        # 栈是后进先出结构，反向压栈才能保持与当前排序一致的遍历顺序。
        stack.extend(reversed(directories_to_visit))

    return {
        "data": {"entries": entries},
        "meta": {
            "returned": len(entries),
            "truncated": truncated or scan_limit_reached,
            "skipped_errors": skipped_errors,
            "scanned": scanned,
            "scan_limit_reached": scan_limit_reached,
        },
    }


def read_file(
    workspace: Workspace,
    arguments: Mapping[str, Any],
    *,
    max_chars: int = 20_000,
    max_file_bytes: int = 2_000_000,
) -> dict[str, Any]:
    """在字节和字符双重限制下读取 UTF-8 文本的指定行区间。

    :param workspace: 限制读取范围并保护敏感路径的工作区对象。
    :param arguments: 文件路径及可选起止行号。
    :param max_chars: 单次返回给模型的正文最大字符数。
    :param max_file_bytes: 允许读取的完整文件最大字节数。
    :return: 文件正文、路径以及哈希、编码、换行等快照元数据。
    :raises ToolError: 参数、行范围、文件大小或文本编码不合法。
    :raises WorkspaceError: 文件越界、受保护或不存在。
    """

    # 第一步：解析目标路径和行范围，再通过 Workspace 锁定工作区内文件。
    reject_unknown(arguments, {"path", "start_line", "end_line"})
    relative = require_string(arguments, "path", max_length=1024)
    start_line = optional_integer(arguments, "start_line", default=1, minimum=1, maximum=10_000_000)
    end_line: int | None = None
    if "end_line" in arguments:
        end_line = optional_integer(
            arguments, "end_line", default=start_line, minimum=1, maximum=10_000_000
        )
        if end_line < start_line:
            raise ToolError("invalid_line_range", "end_line must be greater than or equal to start_line.")

    target = workspace.resolve_existing(relative, expected="file", operation="read")
    # 第二步：按字节上限读取并解码，只允许 Agent 文本工具支持的 UTF-8 文件。
    data = _read_limited(target, max_file_bytes)
    text, encoding, has_bom = _decode_utf8_text(data)
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    # 第三步：截取调用方请求的行区间，并独立应用响应字符上限。
    selected_end = total_lines if end_line is None else min(end_line, total_lines)
    selected = "" if start_line > total_lines else "".join(lines[start_line - 1 : selected_end])
    truncated = len(selected) > max_chars
    returned = selected[:max_chars]

    # 第四步：附带快照哈希和文本格式，供后续 replace_text 做并发校验。
    normalized_path = _normalized_relative(workspace, relative)
    return {
        "data": {"path": normalized_path, "content": returned},
        "meta": {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "encoding": encoding,
            "bom": has_bom,
            "newline": _newline_style(text),
            "start_line": start_line,
            "end_line": selected_end,
            "total_lines": total_lines,
            "returned_chars": len(returned),
            "truncated": truncated,
        },
    }


def make_directory(workspace: Workspace, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """安全且幂等地创建一个工作区目录。

    :param workspace: 提供路径、保护规则和链接边界的工作区对象。
    :param arguments: 目录路径及是否创建缺失父目录。
    :return: 规范目录路径和实际创建数量。
    :raises ToolError: 参数类型或长度不合法。
    :raises WorkspaceError: 目录路径越界、受保护、链接化或无法创建。
    """

    reject_unknown(arguments, {"path", "parents"})
    relative = require_string(arguments, "path", max_length=1024)
    parents = optional_boolean(arguments, "parents", default=True)
    target, created_count = workspace.create_directory(relative, parents=parents)
    return {
        "data": {"path": workspace.relative_label(target)},
        "meta": {
            "created": created_count > 0,
            "created_count": created_count,
        },
    }


def write_file(
    workspace: Workspace,
    arguments: Mapping[str, Any],
    *,
    max_chars: int = 500_000,
) -> dict[str, Any]:
    """以仅创建模式原子写入 UTF-8 文件，禁止覆盖已有目标。

    :param workspace: 提供安全路径解析和原子创建能力的工作区对象。
    :param arguments: 新文件的相对路径和完整文本内容。
    :param max_chars: 新文件正文允许包含的最大字符数。
    :return: 新文件路径及哈希、字节数、编码和换行元数据。
    :raises ToolError: 参数过大或正文不能编码为 UTF-8。
    :raises WorkspaceError: 路径越界、受保护或目标已存在。
    """

    # 第一步：校验路径和正文，并在落盘前完成 UTF-8 编码。
    reject_unknown(arguments, {"path", "content"})
    relative = require_string(arguments, "path", max_length=1024)
    content = require_string(
        arguments,
        "content",
        allow_empty=True,
        max_length=max_chars,
    )
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ToolError("invalid_utf8_text", "content cannot be encoded as UTF-8.") from exc
    # 第二步：由 Workspace 执行仅创建原子写入，避免覆盖已有文件。
    target = workspace.atomic_create(relative, data)
    return {
        "data": {"path": workspace.relative_label(target)},
        "meta": {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "encoding": "utf-8",
            "bom": False,
            "newline": _newline_style(content),
        },
    }


def replace_text(
    workspace: Workspace,
    arguments: Mapping[str, Any],
    *,
    max_file_bytes: int = 2_000_000,
    max_new_chars: int = 500_000,
) -> dict[str, Any]:
    """校验文件快照后执行唯一文本替换，并原子发布新内容。

    :param workspace: 提供受限读取和原子替换能力的工作区对象。
    :param arguments: 路径、旧文本、新文本、预期哈希和预期匹配次数。
    :param max_file_bytes: 允许编辑的原文件最大字节数。
    :param max_new_chars: 新文本参数和编辑后完整文件的字符上限。
    :return: 替换数量及修改前后的哈希、大小和文本格式元数据。
    :raises ToolError: 哈希过期、匹配数不唯一、文件过大或编码不合法。
    :raises WorkspaceError: 文件越界、受保护或发布前发生并发修改。
    """

    # 第一步：读取并校验原文件，保留换行风格和内容哈希作为并发修改依据。
    reject_unknown(
        arguments,
        {"path", "old_text", "new_text", "expected_sha256", "expected_matches"},
    )
    relative = require_string(arguments, "path", max_length=1024)
    old_text = require_string(arguments, "old_text", max_length=max_new_chars)
    new_text = require_string(
        arguments,
        "new_text",
        allow_empty=True,
        max_length=max_new_chars,
    )
    expected_sha256 = require_string(arguments, "expected_sha256", max_length=64).lower()
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ToolError("invalid_sha256", "expected_sha256 must contain exactly 64 hexadecimal characters.")
    expected_matches = optional_integer(
        arguments,
        "expected_matches",
        default=1,
        minimum=1,
        maximum=1,
    )
    if expected_matches != 1:  # 显式保留该判断，强调协议只允许唯一匹配。
        raise ToolError("invalid_expected_matches", "P0 replace_text requires exactly one match.")

    target = workspace.resolve_existing(relative, expected="file", operation="write")
    original = _read_limited(target, max_file_bytes)
    current_sha256 = hashlib.sha256(original).hexdigest()
    if current_sha256 != expected_sha256:
        raise ToolError("stale_file", "The file hash no longer matches; read the file again before editing.")
    text, encoding, has_bom = _decode_utf8_text(original)
    match_count = text.count(old_text)
    if match_count != 1:
        raise ToolError(
            "match_count_mismatch",
            f"replace_text expected one literal match but found {match_count}.",
            data={"path": _normalized_relative(workspace, relative), "match_count": match_count},
        )

    # 第二步：沿用原文件的换行和 BOM 风格，避免一次局部修改产生全文件差异。
    source_newline = _newline_style(text)
    normalized_new_text = _normalize_replacement_newlines(new_text, source_newline)
    updated = text.replace(old_text, normalized_new_text, 1)
    if len(updated) > max_new_chars:
        raise ToolError("edited_file_too_large", "The edited file exceeds the configured text limit.")
    try:
        body = updated.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ToolError("invalid_utf8_text", "The replacement cannot be encoded as UTF-8.") from exc
    updated_bytes = (codecs.BOM_UTF8 + body) if has_bom else body
    # 第三步：发布前再次比对哈希，再以原子替换提交修改。
    workspace.atomic_replace(relative, updated_bytes, expected_sha256=expected_sha256)

    return {
        "data": {"path": _normalized_relative(workspace, relative), "replacements": 1},
        "meta": {
            "before_sha256": expected_sha256,
            "after_sha256": hashlib.sha256(updated_bytes).hexdigest(),
            "before_size_bytes": len(original),
            "after_size_bytes": len(updated_bytes),
            "encoding": encoding,
            "bom": has_bom,
            "newline": _newline_style(updated),
        },
    }


def delete_file(
    workspace: Workspace,
    arguments: Mapping[str, Any],
    *,
    max_file_bytes: int = 2_000_000,
) -> dict[str, Any]:
    """在最近读取的哈希仍匹配时删除一个普通工作区文件。

    :param workspace: 提供路径边界、链接拒绝和删除前复核的工作区对象。
    :param arguments: 文件路径和最近一次 ``read_file`` 返回的 SHA-256。
    :param max_file_bytes: 允许删除的文件大小上限。
    :return: 删除路径以及删除前哈希和大小元数据。
    :raises ToolError: 参数或哈希格式不合法。
    :raises WorkspaceError: 文件越界、受保护、变化、过大或无法删除。
    """

    reject_unknown(arguments, {"path", "expected_sha256"})
    relative = require_string(arguments, "path", max_length=1024)
    expected_sha256 = require_string(
        arguments, "expected_sha256", max_length=64
    ).lower()
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ToolError(
            "invalid_sha256",
            "expected_sha256 must contain exactly 64 hexadecimal characters.",
        )
    path, size = workspace.delete_file(
        relative,
        expected_sha256=expected_sha256,
        max_file_bytes=max_file_bytes,
    )
    return {
        "data": {"path": path, "deleted": True},
        "meta": {"sha256": expected_sha256, "size_bytes": size},
    }


def _read_limited(path: Path, limit: int) -> bytes:
    """读取不超过指定字节上限的完整文件。

    :param path: 要读取的已解析文件路径。
    :param limit: 允许读取的最大字节数。
    :return: 完整文件字节。
    :raises ToolError: 文件无法读取或大小超过限制。
    """

    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as exc:
        raise ToolError("file_read_failed", "The file could not be read.") from exc
    if len(data) > limit:
        raise ToolError("file_too_large", f"The file exceeds the {limit}-byte read limit.")
    return data


def _decode_utf8_text(data: bytes) -> tuple[str, str, bool]:
    """识别 UTF-8 BOM 并拒绝二进制或非 UTF-8 内容。

    :param data: 完整文件字节。
    :return: 解码文本、编码标签以及是否带 BOM。
    :raises ToolError: 内容含空字节或不能按 UTF-8 解码。
    """

    has_bom = data.startswith(codecs.BOM_UTF8)
    body = data[len(codecs.BOM_UTF8) :] if has_bom else data
    if b"\x00" in body:
        raise ToolError("binary_file", "Binary files are not supported by text tools.")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError("non_utf8_file", "Only UTF-8 and UTF-8-SIG text files are supported.") from exc
    return text, "utf-8-sig" if has_bom else "utf-8", has_bom


def _newline_style(text: str) -> str:
    """识别文本使用的换行约定。

    :param text: 已解码的完整文本。
    :return: ``crlf``、``lf``、``cr``、``mixed`` 或 ``none``。
    """

    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    styles = sum(bool(count) for count in (crlf, lf, cr))
    if styles == 0:
        return "none"
    if styles > 1:
        return "mixed"
    if crlf:
        return "crlf"
    if lf:
        return "lf"
    return "cr"


def _normalize_replacement_newlines(text: str, source_style: str) -> str:
    """使替换文本匹配源文件的单一换行约定。

    混合换行或没有换行的源文件保持原样，因为这两种情况下都不存在明确约定。

    :param text: 模型提供的替换文本。
    :param source_style: ``_newline_style`` 返回的源文件换行标签。
    :return: 换行符与源文件单一约定一致的新文本。
    """

    replacements = {"crlf": "\r\n", "lf": "\n", "cr": "\r"}
    replacement = replacements.get(source_style)
    if replacement is None:
        return text
    return re.sub(r"\r\n|\r|\n", lambda _match: replacement, text)


def _normalized_relative(workspace: Workspace, relative: str) -> str:
    """将任意受支持相对路径规范化为 POSIX 展示形式。

    :param workspace: 负责校验路径片段的工作区对象。
    :param relative: 调用方提供的相对路径文本。
    :return: 使用正斜杠的规范相对路径，根目录表示为 ``.``。
    """

    parts = workspace.relative_parts(relative)
    return PurePosixPath(*parts).as_posix() if parts else "."


def _validate_glob(pattern: str) -> None:
    """确认 glob 不包含绝对路径、父目录或控制字符语法。

    :param pattern: 模型提供的 glob 模式。
    :raises ToolError: 模式可能逃逸工作区或包含不支持字符。
    """

    if "\x00" in pattern or any(ord(character) < 32 for character in pattern):
        raise ToolError("invalid_glob", "The glob contains invalid characters.")
    windows = PureWindowsPath(pattern)
    parts = PurePosixPath(pattern.replace("\\", "/")).parts
    if windows.drive or windows.root or ".." in parts:
        raise ToolError("invalid_glob", "The glob must remain relative to the workspace.")
    if ":" in pattern:
        raise ToolError("invalid_glob", "Windows drive and ADS syntax is not allowed in globs.")


def _dir_entry_is_reparse(entry: os.DirEntry[str]) -> bool:
    """保守判断目录项是否为符号链接或 Windows 重解析点。

    :param entry: ``os.scandir`` 返回的目录项。
    :return: 条目是链接、重解析点或无法安全读取元数据时为 ``True``。
    """

    try:
        metadata = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return entry.is_symlink() or bool(attributes & reparse_flag)


__all__ = [
    "delete_file",
    "list_files",
    "make_directory",
    "read_file",
    "replace_text",
    "write_file",
]
