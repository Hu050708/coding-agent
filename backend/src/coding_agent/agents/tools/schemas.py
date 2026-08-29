"""定义提供给模型供应商的工具 JSON Schema。"""

from __future__ import annotations

import copy
from typing import Any

from coding_agent.agents.security.permission_policy import PermissionMode, PermissionPolicy


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "按稳定顺序列出工作区文件和目录。目录链接只会列出但不会进入，"
                "受保护目录和生成目录会被跳过。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对工作区的目录；使用 '.' 表示工作区根目录。",
                    },
                    "glob": {
                        "type": "string",
                        "description": "可选的不区分大小写 glob，用于匹配工作区相对路径。",
                    },
                    "max_entries": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 500,
                        "description": "最多返回的条目数，默认 500。",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "读取 UTF-8 工作区文件，可选择按一基且包含边界的行号范围读取。"
                "返回原始文本以及哈希、BOM、换行符和截断元数据。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对工作区的文件路径。"},
                    "start_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "返回的第一行（一基行号），默认 1。",
                    },
                    "end_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "可选的最后一行，包含该行。",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": (
                "在 UTF-8 工作区文件中搜索一个单行字面字符串。"
                "读取大型文件前，可先用它定位符号或引用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                        "description": "要查找的单行字面文本。",
                    },
                    "path": {
                        "type": "string",
                        "description": "相对工作区的目录，默认 '.'。",
                    },
                    "glob": {
                        "type": "string",
                        "description": "可选的不区分大小写 glob，用于匹配相对文件路径。",
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "匹配是否区分大小写，默认 true。",
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "description": "最多返回的匹配行数，默认 100。",
                    },
                    "context_lines": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 3,
                        "description": "每个匹配项前后返回的相邻行数，默认 0。",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "原子创建一个新的 UTF-8 文件。该工具绝不覆盖已有文件；"
                "请使用 replace_text 编辑已有文件。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对工作区的新文件路径。"},
                    "content": {
                        "type": "string",
                        "maxLength": 500000,
                        "description": "新文件的完整 UTF-8 内容。",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_text",
            "description": (
                "替换已有 UTF-8 文件中恰好一处字面文本。"
                "预期 SHA-256 必须来自最近一次 read_file 结果。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对工作区的文件路径。"},
                    "old_text": {"type": "string", "description": "精确的已有文本，不得为空。"},
                    "new_text": {"type": "string", "description": "替换后的文本。"},
                    "expected_sha256": {
                        "type": "string",
                        "pattern": "^[0-9a-fA-F]{64}$",
                        "description": "最近一次 read_file 调用返回的 SHA-256。",
                    },
                    "expected_matches": {
                        "type": "integer",
                        "enum": [1],
                        "description": "当前版本要求恰好匹配一次；省略或设为 1。",
                    },
                },
                "required": ["path", "old_text", "new_text", "expected_sha256"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "不经过 shell 运行一个本地可执行程序。argv 必须使用数组；"
                "不支持管道、重定向、复合 shell 语法、批处理文件和 shell 宿主。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 64,
                        "items": {"type": "string"},
                        "description": "将可执行程序及每个参数分别作为字符串提供。",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "相对工作区的执行目录，默认 '.'。",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "minimum": 0.1,
                        "maximum": 120,
                        "description": "命令超时时间，默认 120 秒。",
                    },
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
        },
    },
]


def schemas_for_permission(
    permission: PermissionPolicy | PermissionMode | str,
) -> list[dict[str, Any]]:
    """返回仅包含本次运行可见能力的隔离工具模型。

    :param permission: 已构建权限策略、权限枚举或其字符串值。
    :return: 深拷贝后的可见工具 JSON Schema 列表。
    """

    policy = (
        permission
        if isinstance(permission, PermissionPolicy)
        else PermissionPolicy(PermissionMode.parse(permission))
    )
    return [
        copy.deepcopy(schema)
        for schema in TOOL_SCHEMAS
        if schema.get("function", {}).get("name") in policy.tool_names
    ]


__all__ = ["TOOL_SCHEMAS", "schemas_for_permission"]
