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
    optional_integer,
    optional_string,
    reject_unknown,
    require_string,
)


_LIST_SCAN_LIMIT = 10_000


def list_files(workspace: Workspace, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """按稳定顺序递归列出文件，同时限制返回量和实际扫描量。"""

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
    """在字节和字符双重限制下读取 UTF-8 文本的指定行区间。"""

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


def write_file(
    workspace: Workspace,
    arguments: Mapping[str, Any],
    *,
    max_chars: int = 500_000,
) -> dict[str, Any]:
    """以仅创建模式原子写入 UTF-8 文件，禁止覆盖已有目标。"""

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
    """校验文件快照后执行唯一文本替换，并原子发布新内容。"""

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


def _read_limited(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as exc:
        raise ToolError("file_read_failed", "The file could not be read.") from exc
    if len(data) > limit:
        raise ToolError("file_too_large", f"The file exceeds the {limit}-byte read limit.")
    return data


def _decode_utf8_text(data: bytes) -> tuple[str, str, bool]:
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
    """

    replacements = {"crlf": "\r\n", "lf": "\n", "cr": "\r"}
    replacement = replacements.get(source_style)
    if replacement is None:
        return text
    return re.sub(r"\r\n|\r|\n", lambda _match: replacement, text)


def _normalized_relative(workspace: Workspace, relative: str) -> str:
    parts = workspace.relative_parts(relative)
    return PurePosixPath(*parts).as_posix() if parts else "."


def _validate_glob(pattern: str) -> None:
    if "\x00" in pattern or any(ord(character) < 32 for character in pattern):
        raise ToolError("invalid_glob", "The glob contains invalid characters.")
    windows = PureWindowsPath(pattern)
    parts = PurePosixPath(pattern.replace("\\", "/")).parts
    if windows.drive or windows.root or ".." in parts:
        raise ToolError("invalid_glob", "The glob must remain relative to the workspace.")
    if ":" in pattern:
        raise ToolError("invalid_glob", "Windows drive and ADS syntax is not allowed in globs.")


def _dir_entry_is_reparse(entry: os.DirEntry[str]) -> bool:
    try:
        metadata = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return entry.is_symlink() or bool(attributes & reparse_flag)


__all__ = ["list_files", "read_file", "replace_text", "write_file"]
