"""验证原生文本搜索的结果语义、资源边界和工作区隔离。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from coding_agent.agents.security import Workspace
from coding_agent.agents.tools import ToolRegistry, search_text


def decode(value: str) -> dict:
    payload = json.loads(value)
    assert isinstance(payload, dict)
    return payload


def test_search_text_returns_stable_locations_and_context(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "z.py").write_text(
        "before\nTarget = 1\nafter\n", encoding="utf-8"
    )
    (tmp_path / "src" / "a.py").write_text(
        "target = 2\nTARGET = 3\n", encoding="utf-8"
    )
    registry = ToolRegistry(Workspace(tmp_path))

    response = decode(
        registry.execute(
            "search_text",
            {
                "query": "target",
                "path": "src",
                "glob": "*.py",
                "case_sensitive": False,
                "context_lines": 1,
            },
        )
    )

    assert response["ok"] is True
    assert response["data"]["matches"] == [
        {
            "path": "src/a.py",
            "line": 1,
            "column": 1,
            "preview": "target = 2",
            "before": [],
            "after": ["TARGET = 3"],
        },
        {
            "path": "src/a.py",
            "line": 2,
            "column": 1,
            "preview": "TARGET = 3",
            "before": ["target = 2"],
            "after": [],
        },
        {
            "path": "src/z.py",
            "line": 2,
            "column": 1,
            "preview": "Target = 1",
            "before": ["before"],
            "after": ["after"],
        },
    ]
    assert response["meta"] == {
        "returned": 3,
        "scanned_files": 2,
        "scanned_bytes": 51,
        "skipped_files": 0,
        "truncated": False,
    }


def test_search_text_defaults_to_case_sensitive_and_one_match_per_line(
    tmp_path: Path,
) -> None:
    (tmp_path / "code.py").write_text("name name\nNAME\n", encoding="utf-8")
    response = decode(
        ToolRegistry(Workspace(tmp_path)).execute("search_text", {"query": "name"})
    )

    assert response["data"]["matches"] == [
        {"path": "code.py", "line": 1, "column": 1, "preview": "name name"}
    ]


def test_search_text_skips_protected_binary_and_non_utf8_files(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("needle", encoding="utf-8")
    (tmp_path / ".env").write_text("needle", encoding="utf-8")
    (tmp_path / "binary.dat").write_bytes(b"needle\x00tail")
    (tmp_path / "legacy.txt").write_bytes(b"needle\xff")
    (tmp_path / "visible.txt").write_text("needle", encoding="utf-8")

    response = decode(
        ToolRegistry(Workspace(tmp_path)).execute("search_text", {"query": "needle"})
    )

    assert [item["path"] for item in response["data"]["matches"]] == ["visible.txt"]
    assert response["meta"]["skipped_files"] == 2


def test_search_text_bounds_results_files_bytes_and_output(tmp_path: Path) -> None:
    for index in range(4):
        (tmp_path / f"{index}.txt").write_text(f"needle {index}\n", encoding="utf-8")
    workspace = Workspace(tmp_path)

    result_bound = search_text(workspace, {"query": "needle", "max_results": 2})
    assert len(result_bound["data"]["matches"]) == 2
    assert result_bound["meta"]["truncated"] is True

    file_bound = search_text(workspace, {"query": "needle"}, max_files=2)
    assert file_bound["meta"]["scanned_files"] == 2
    assert file_bound["meta"]["truncated"] is True

    byte_bound = search_text(workspace, {"query": "needle"}, max_total_bytes=12)
    assert byte_bound["meta"]["scanned_files"] == 1
    assert byte_bound["meta"]["truncated"] is True

    output_bound = search_text(workspace, {"query": "needle"}, max_output_chars=5)
    assert output_bound["data"]["matches"] == []
    assert output_bound["meta"]["truncated"] is True


def test_search_file_limit_counts_files_that_do_not_match_glob(tmp_path: Path) -> None:
    (tmp_path / "0.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "1.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "2.py").write_text("needle", encoding="utf-8")

    response = search_text(
        Workspace(tmp_path),
        {"query": "needle", "glob": "*.py"},
        max_files=2,
    )

    assert response["data"]["matches"] == []
    assert response["meta"]["scanned_files"] == 0
    assert response["meta"]["truncated"] is True


def test_search_text_rejects_escape_unknown_arguments_and_multiline_query(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry(Workspace(tmp_path))
    for arguments, code in (
        ({"query": "x", "path": "../outside"}, "path_traversal"),
        ({"query": "x", "regex": True}, "unknown_argument"),
        ({"query": "x\ny"}, "invalid_argument"),
        ({"query": "x", "case_sensitive": "yes"}, "invalid_argument"),
    ):
        response = decode(registry.execute("search_text", arguments))
        assert response["ok"] is False
        assert response["error"]["code"] == code


def test_search_text_does_not_follow_directory_links(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "visible.txt").write_text("needle", encoding="utf-8")
    (outside / "secret.txt").write_text("needle", encoding="utf-8")
    try:
        os.symlink(outside, root / "linked", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    response = decode(
        ToolRegistry(Workspace(root)).execute("search_text", {"query": "needle"})
    )
    assert [item["path"] for item in response["data"]["matches"]] == ["visible.txt"]


def test_search_text_schema_is_visible_and_read_only_in_every_permission(
    tmp_path: Path,
) -> None:
    for mode in ("ask", "agent", "workspace_full"):
        registry = ToolRegistry(Workspace(tmp_path), permission_mode=mode)
        names = {item["function"]["name"] for item in registry.schemas}
        assert "search_text" in names
        response = decode(registry.execute("search_text", {"query": "missing"}))
        assert response["ok"] is True
