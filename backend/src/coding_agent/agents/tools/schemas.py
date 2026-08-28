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
                "List workspace files and directories in stable order. Directory links are listed "
                "but never traversed. Protected and generated directories are skipped."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative directory. Use '.' for the workspace root.",
                    },
                    "glob": {
                        "type": "string",
                        "description": "Optional case-insensitive glob matched against workspace-relative paths.",
                    },
                    "max_entries": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 500,
                        "description": "Maximum number of returned entries; defaults to 500.",
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
                "Read a UTF-8 workspace file, optionally by inclusive 1-based line range. "
                "Returns the exact text plus hash, BOM, newline, and truncation metadata."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "start_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "First 1-based line to return; defaults to 1.",
                    },
                    "end_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Optional inclusive final line.",
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
                "Search UTF-8 workspace files for one literal single-line string. "
                "Use this to locate symbols or references before reading large files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                        "description": "Literal single-line text to find.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative directory; defaults to '.'.",
                    },
                    "glob": {
                        "type": "string",
                        "description": "Optional case-insensitive glob matched against relative file paths.",
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Whether matching is case-sensitive; defaults to true.",
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "description": "Maximum returned matching lines; defaults to 100.",
                    },
                    "context_lines": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 3,
                        "description": "Adjacent lines returned before and after each match; defaults to 0.",
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
                "Create one new UTF-8 file atomically. This tool never overwrites an existing file; "
                "use replace_text to edit an existing file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative new file path."},
                    "content": {
                        "type": "string",
                        "maxLength": 500000,
                        "description": "Complete UTF-8 content for the new file.",
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
                "Replace exactly one literal text occurrence in an existing UTF-8 file. "
                "The expected SHA-256 must come from the latest read_file result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "old_text": {"type": "string", "description": "Exact existing text; may not be empty."},
                    "new_text": {"type": "string", "description": "Replacement text."},
                    "expected_sha256": {
                        "type": "string",
                        "pattern": "^[0-9a-fA-F]{64}$",
                        "description": "SHA-256 returned by the latest read_file call.",
                    },
                    "expected_matches": {
                        "type": "integer",
                        "enum": [1],
                        "description": "P0 requires exactly one match; omit or set to 1.",
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
                "Run one local executable without a shell. Pass argv as an array; pipes, redirection, "
                "compound shell syntax, batch files, and shell hosts are not supported."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 64,
                        "items": {"type": "string"},
                        "description": "Executable and arguments as separate strings.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Workspace-relative working directory; defaults to '.'.",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "minimum": 0.1,
                        "maximum": 120,
                        "description": "Command timeout; defaults to 120 seconds.",
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
    """返回仅包含本次运行可见能力的隔离工具模型。"""

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
