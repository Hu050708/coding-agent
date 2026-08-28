"""实现有界、稳定且不依赖 shell 的工作区文本搜索。"""

from __future__ import annotations

import codecs
import fnmatch
import os
from pathlib import Path
from typing import Any, Mapping

from coding_agent.agents.security import Workspace, WorkspaceError

from .contracts import (
    ToolError,
    optional_integer,
    optional_string,
    reject_unknown,
    require_string,
)


_DEFAULT_MAX_FILES = 2_000
_DEFAULT_MAX_TOTAL_BYTES = 20_000_000
_DEFAULT_MAX_FILE_BYTES = 2_000_000
_DEFAULT_MAX_OUTPUT_CHARS = 20_000
_MAX_PREVIEW_CHARS = 500
_MAX_DIRECTORY_ENTRIES = 10_000


def search_text(
    workspace: Workspace,
    arguments: Mapping[str, Any],
    *,
    max_files: int = _DEFAULT_MAX_FILES,
    max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
    max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
    max_output_chars: int = _DEFAULT_MAX_OUTPUT_CHARS,
) -> dict[str, Any]:
    """在工作区 UTF-8 文件中搜索单行字面文本。"""

    # 第一步：解析搜索条件和返回预算，提前拒绝多行查询与无效 glob。
    reject_unknown(
        arguments,
        {"query", "path", "glob", "case_sensitive", "max_results", "context_lines"},
    )
    query = require_string(arguments, "query", max_length=512)
    if "\r" in query or "\n" in query:
        raise ToolError("invalid_argument", "query must be a single line of text.")
    relative_directory = optional_string(arguments, "path", default=".", max_length=1024)
    pattern = optional_string(arguments, "glob", max_length=256)
    if pattern is not None and ("\x00" in pattern or "\r" in pattern or "\n" in pattern):
        raise ToolError("invalid_glob", "glob contains unsupported characters.")
    case_sensitive = _optional_boolean(arguments, "case_sensitive", default=True)
    max_results = optional_integer(
        arguments, "max_results", default=100, minimum=1, maximum=200
    )
    context_lines = optional_integer(
        arguments, "context_lines", default=0, minimum=0, maximum=3
    )

    # 第二步：确定工作区内的搜索起点，并按稳定顺序收集候选文件。
    start = workspace.resolve_existing(
        relative_directory or ".",
        expected="directory",
        allow_reparse=False,
        operation="read",
    )
    candidates, scan_limit_reached, skipped_errors = _candidate_files(
        workspace,
        start,
        pattern=pattern,
        max_files=max_files,
    )

    matches: list[dict[str, Any]] = []
    scanned_files = 0
    scanned_bytes = 0
    skipped_files = skipped_errors
    output_chars = 0
    output_limit_reached = False
    truncated = scan_limit_reached
    needle = query if case_sensitive else query.casefold()

    # 第三步：在文件数、字节数和单文件大小预算内读取 UTF-8 文本。
    for target, relative, size in candidates:
        if len(matches) >= max_results:
            truncated = True
            break
        if size > max_file_bytes:
            skipped_files += 1
            continue
        if scanned_bytes + size > max_total_bytes:
            truncated = True
            break
        try:
            with target.open("rb") as stream:
                raw = stream.read(max_file_bytes + 1)
        except OSError:
            skipped_files += 1
            continue
        if len(raw) > max_file_bytes:
            skipped_files += 1
            continue
        if scanned_bytes + len(raw) > max_total_bytes:
            truncated = True
            break
        scanned_files += 1
        scanned_bytes += len(raw)
        if b"\x00" in raw:
            skipped_files += 1
            continue
        try:
            text = raw.decode("utf-8-sig" if raw.startswith(codecs.BOM_UTF8) else "utf-8")
        except UnicodeDecodeError:
            skipped_files += 1
            continue

        # 第四步：逐行匹配字面文本，同时构建可选上下文和有界预览。
        lines = text.splitlines()
        for index, line in enumerate(lines):
            haystack = line if case_sensitive else line.casefold()
            column = haystack.find(needle)
            if column < 0:
                continue
            item: dict[str, Any] = {
                "path": relative,
                "line": index + 1,
                "column": column + 1,
                "preview": _bounded_line(line),
            }
            if context_lines:
                before_start = max(0, index - context_lines)
                after_end = min(len(lines), index + context_lines + 1)
                item["before"] = [
                    _bounded_line(value) for value in lines[before_start:index]
                ]
                item["after"] = [
                    _bounded_line(value) for value in lines[index + 1 : after_end]
                ]
            item_chars = _item_chars(item)
            if output_chars + item_chars > max_output_chars:
                truncated = True
                output_limit_reached = True
                break
            matches.append(item)
            output_chars += item_chars
            if len(matches) >= max_results:
                truncated = True
                break
        if output_limit_reached or (truncated and (
            len(matches) >= max_results or output_chars >= max_output_chars
        )):
            break

    # 第五步：返回匹配项及扫描统计，让 Agent 能判断结果是否被截断。
    return {
        "data": {"matches": matches},
        "meta": {
            "returned": len(matches),
            "scanned_files": scanned_files,
            "scanned_bytes": scanned_bytes,
            "skipped_files": skipped_files,
            "truncated": truncated,
        },
    }


def _candidate_files(
    workspace: Workspace,
    start: Path,
    *,
    pattern: str | None,
    max_files: int,
) -> tuple[list[tuple[Path, str, int]], bool, int]:
    """遍历工作区目录，返回满足 glob 的稳定候选文件列表。"""

    # 第一步：使用显式栈遍历目录，限制实际访问的目录项和文件数量。
    candidates: list[tuple[Path, str, int]] = []
    skipped_errors = 0
    limit_reached = False
    visited_files = 0
    visited_entries = 0
    stack = [start]
    while stack and not limit_reached:
        directory = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda item: (item.name.casefold(), item.name))
        except OSError:
            skipped_errors += 1
            continue
        # 第二步：跳过受保护路径、链接和非普通文件，并记录无法读取的条目。
        directories: list[Path] = []
        for child in children:
            if visited_entries >= _MAX_DIRECTORY_ENTRIES:
                limit_reached = True
                break
            visited_entries += 1
            child_path = Path(child.path)
            try:
                relative = workspace.relative_label(child_path)
                if workspace.should_skip_listing(relative):
                    continue
                if workspace.is_reparse_point(child_path):
                    continue
                if child.is_dir(follow_symlinks=False):
                    directories.append(child_path)
                    continue
                if not child.is_file(follow_symlinks=False):
                    continue
                if visited_files >= max_files:
                    limit_reached = True
                    break
                visited_files += 1
                if pattern is not None and not fnmatch.fnmatchcase(
                    relative.casefold(), pattern.casefold()
                ):
                    continue
                size = child.stat(follow_symlinks=False).st_size
            except (OSError, WorkspaceError):
                skipped_errors += 1
                continue
            candidates.append((child_path, relative, size))
        stack.extend(reversed(directories))
    # 第三步：最终排序与文件系统枚举顺序解耦，保证相同工作区得到稳定结果。
    candidates.sort(key=lambda item: (item[1].casefold(), item[1]))
    return candidates, limit_reached, skipped_errors


def _optional_boolean(arguments: Mapping[str, Any], name: str, *, default: bool) -> bool:
    if name not in arguments:
        return default
    value = arguments[name]
    if not isinstance(value, bool):
        raise ToolError("invalid_argument", f"{name} must be a boolean.")
    return value


def _bounded_line(value: str) -> str:
    return value[:_MAX_PREVIEW_CHARS]


def _item_chars(item: Mapping[str, Any]) -> int:
    total = sum(len(value) for value in item.values() if isinstance(value, str))
    for name in ("before", "after"):
        values = item.get(name)
        if isinstance(values, list):
            total += sum(len(value) for value in values if isinstance(value, str))
    return total


__all__ = ["search_text"]
