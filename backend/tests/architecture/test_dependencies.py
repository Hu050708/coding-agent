from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2] / "src" / "coding_agent"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_core_is_provider_and_tool_implementation_independent():
    forbidden = ("openai", "coding_agent.providers", "coding_agent.tools", "coding_agent.security")
    for path in (SOURCE / "core").glob("*.py"):
        imported = _imports(path)
        assert not any(name.startswith(forbidden) for name in imported), (path, imported)


def test_only_provider_layer_imports_openai_sdk():
    sdk_importers = []
    for path in SOURCE.rglob("*.py"):
        if any(name == "openai" or name.startswith("openai.") for name in _imports(path)):
            sdk_importers.append(path.relative_to(SOURCE).as_posix())
    assert sdk_importers == ["providers/deepseek.py"]


def test_provider_depends_on_core_contracts_not_agent_implementation():
    imported = _imports(SOURCE / "providers" / "deepseek.py")
    assert "coding_agent.core.contracts" in imported
    assert "coding_agent.core.agent" not in imported


def test_tool_handlers_depend_on_contracts_not_registry():
    for name in ("command.py", "filesystem.py"):
        imported = _imports(SOURCE / "tools" / name)
        assert "coding_agent.tools.registry" not in imported
        assert "registry" not in imported


def test_command_policy_is_pure_and_does_not_import_workspace_facade():
    imported = _imports(SOURCE / "security" / "command_policy.py")
    assert "coding_agent.security.workspace" not in imported
    assert "workspace" not in imported


def test_memory_layer_does_not_import_run_or_web_orchestration():
    for path in (SOURCE / "memory").glob("*.py"):
        imported = _imports(path)
        assert not any(name.startswith("coding_agent.runs") for name in imported), (
            path,
            imported,
        )
