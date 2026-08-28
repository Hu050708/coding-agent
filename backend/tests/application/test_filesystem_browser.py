"""验证目录浏览器的根目录、排序和安全过滤行为。"""

from __future__ import annotations

import os

import pytest

from coding_agent.services import ApplicationError, DirectoryBrowser
from coding_agent.agents.security import WorkspacePolicy


def test_directory_browser_stays_inside_allowed_root(tmp_path):
    root = tmp_path / "allowed"
    alpha = root / "Alpha"
    beta = root / "beta"
    alpha.mkdir(parents=True)
    beta.mkdir()
    (root / "plain.txt").write_text("not a directory", encoding="utf-8")
    browser = DirectoryBrowser(WorkspacePolicy(root))

    result = browser.browse()

    assert result["current_path"] == os.fspath(root.resolve())
    assert result["parent_path"] is None
    assert [entry["name"] for entry in result["entries"]] == ["Alpha", "beta"]

    nested = browser.browse(os.fspath(alpha))
    assert nested["parent_path"] == os.fspath(root.resolve())


def test_directory_browser_rejects_outside_path(tmp_path):
    root = tmp_path / "allowed"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    browser = DirectoryBrowser(WorkspacePolicy(root))

    with pytest.raises(ApplicationError) as exc_info:
        browser.browse(os.fspath(outside))

    assert exc_info.value.code == "workspace_not_allowed"
