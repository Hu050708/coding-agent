"""验证文件工具的读取限额、列表过滤和并发修改保护。"""

from __future__ import annotations

import codecs
import hashlib
import json
import os
from pathlib import Path

import pytest

from coding_agent.agents.security import Workspace
from coding_agent.agents.tools import ToolRegistry


def decode(payload: str) -> dict:
    value = json.loads(payload)
    assert isinstance(value, dict)
    return value


def make_registry(root: Path, **limits: int) -> ToolRegistry:
    return ToolRegistry(Workspace(root), **limits)


def test_list_files_is_stable_bounded_and_skips_protected_paths(tmp_path: Path) -> None:
    (tmp_path / "z.txt").write_text("z", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "b.py").write_text("b", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret", encoding="utf-8")
    (tmp_path / ".env").write_text("secret", encoding="utf-8")
    registry = make_registry(tmp_path)

    full = decode(registry.execute("list_files", {"path": "."}))
    paths = [entry["path"] for entry in full["data"]["entries"]]
    assert paths == ["a.txt", "dir", "z.txt", "dir/b.py"]
    assert ".git" not in paths
    assert ".env" not in paths

    bounded = decode(registry.execute("list_files", {"path": ".", "max_entries": 2}))
    assert bounded["meta"]["returned"] == 2
    assert bounded["meta"]["truncated"] is True

    filtered = decode(registry.execute("list_files", {"path": ".", "glob": "*.py"}))
    assert [entry["path"] for entry in filtered["data"]["entries"]] == ["dir/b.py"]


def test_list_files_reports_link_without_following_it(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    try:
        os.symlink(outside, root / "outside-link", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    response = decode(make_registry(root).execute("list_files", {"path": "."}))
    assert response["ok"] is True
    assert response["data"]["entries"] == [{"path": "outside-link", "type": "link"}]


def test_list_files_has_independent_scan_limit_for_nonmatching_glob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import coding_agent.agents.tools.filesystem as filesystem

    for index in range(5):
        (tmp_path / f"file-{index}.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(filesystem, "_LIST_SCAN_LIMIT", 3)
    response = decode(
        make_registry(tmp_path).execute("list_files", {"path": ".", "glob": "*.never"})
    )
    assert response["ok"] is True
    assert response["data"]["entries"] == []
    assert response["meta"]["scanned"] == 3
    assert response["meta"]["scan_limit_reached"] is True
    assert response["meta"]["truncated"] is True


def test_read_file_preserves_bom_crlf_ranges_hash_and_limits(tmp_path: Path) -> None:
    raw = codecs.BOM_UTF8 + "第一行\r\nsecond\r\nthird\r\n".encode("utf-8")
    (tmp_path / "text.txt").write_bytes(raw)
    registry = make_registry(tmp_path, max_read_chars=9)

    ranged = decode(
        registry.execute("read_file", {"path": "text.txt", "start_line": 2, "end_line": 3})
    )
    assert ranged["ok"] is True
    assert ranged["data"]["content"] == "second\r\nt"
    assert ranged["meta"]["truncated"] is True
    assert ranged["meta"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert ranged["meta"]["bom"] is True
    assert ranged["meta"]["encoding"] == "utf-8-sig"
    assert ranged["meta"]["newline"] == "crlf"
    assert ranged["meta"]["total_lines"] == 3


@pytest.mark.parametrize(
    ("name", "content", "code"),
    [
        ("binary.bin", b"abc\x00def", "binary_file"),
        ("legacy.txt", b"\xff\xfe", "non_utf8_file"),
    ],
)
def test_read_file_rejects_non_text(name: str, content: bytes, code: str, tmp_path: Path) -> None:
    (tmp_path / name).write_bytes(content)
    response = decode(make_registry(tmp_path).execute("read_file", {"path": name}))
    assert response["ok"] is False
    assert response["error"]["code"] == code


def test_write_file_is_utf8_create_only_and_never_overwrites(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    created = decode(registry.execute("write_file", {"path": "new.txt", "content": "你好\r\n"}))
    assert created["ok"] is True
    assert (tmp_path / "new.txt").read_bytes() == "你好\r\n".encode("utf-8")

    existing = decode(registry.execute("write_file", {"path": "new.txt", "content": "clobber"}))
    assert existing["ok"] is False
    assert existing["error"]["code"] == "path_exists"
    assert (tmp_path / "new.txt").read_bytes() == "你好\r\n".encode("utf-8")


def test_write_file_loses_create_race_without_clobbering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = make_registry(tmp_path)
    real_link = os.link

    def racing_link(source: str | os.PathLike[str], target: str | os.PathLike[str], *args, **kwargs):
        Path(target).write_bytes(b"racer")
        return real_link(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)
    response = decode(registry.execute("write_file", {"path": "race.txt", "content": "ours"}))
    assert response["ok"] is False
    assert response["error"]["code"] == "path_exists"
    assert (tmp_path / "race.txt").read_bytes() == b"racer"
    assert not list(tmp_path.glob(".race.txt.*.tmp"))


def test_replace_text_requires_fresh_hash_unique_match_and_preserves_format(tmp_path: Path) -> None:
    original = codecs.BOM_UTF8 + b"alpha\r\nbeta\r\n"
    target = tmp_path / "text.txt"
    target.write_bytes(original)
    registry = make_registry(tmp_path)
    expected = hashlib.sha256(original).hexdigest()

    response = decode(
        registry.execute(
            "replace_text",
            {
                "path": "text.txt",
                "old_text": "beta",
                "new_text": "gamma\nnext",
                "expected_sha256": expected,
                "expected_matches": 1,
            },
        )
    )
    assert response["ok"] is True
    assert target.read_bytes() == codecs.BOM_UTF8 + b"alpha\r\ngamma\r\nnext\r\n"
    assert response["meta"]["bom"] is True
    assert response["meta"]["newline"] == "crlf"

    stale = decode(
        registry.execute(
            "replace_text",
            {
                "path": "text.txt",
                "old_text": "gamma",
                "new_text": "delta",
                "expected_sha256": expected,
            },
        )
    )
    assert stale["error"]["code"] == "stale_file"


@pytest.mark.parametrize(("content", "old", "matches"), [("abc", "x", 0), ("x x", "x", 2)])
def test_replace_text_rejects_zero_or_multiple_matches(
    tmp_path: Path, content: str, old: str, matches: int
) -> None:
    target = tmp_path / "text.txt"
    raw = content.encode("utf-8")
    target.write_bytes(raw)
    response = decode(
        make_registry(tmp_path).execute(
            "replace_text",
            {
                "path": "text.txt",
                "old_text": old,
                "new_text": "z",
                "expected_sha256": hashlib.sha256(raw).hexdigest(),
            },
        )
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "match_count_mismatch"
    assert response["data"]["match_count"] == matches
    assert target.read_bytes() == raw


def test_all_file_tools_reject_protected_paths(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    registry = make_registry(tmp_path)
    for tool, arguments in (
        ("read_file", {"path": ".git/config"}),
        ("write_file", {"path": ".git/new", "content": "x"}),
        (
            "replace_text",
            {
                "path": ".git/config",
                "old_text": "x",
                "new_text": "y",
                "expected_sha256": hashlib.sha256(b"x").hexdigest(),
            },
        ),
    ):
        response = decode(registry.execute(tool, arguments))
        assert response["ok"] is False
        assert response["error"]["code"] == "protected_path"
