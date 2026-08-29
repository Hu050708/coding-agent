"""验证分层依赖方向，防止核心层反向依赖外层实现。"""

from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2] / "src" / "coding_agent"
AGENTS = SOURCE / "agents"


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
    forbidden = (
        "openai",
        "coding_agent.agents.tools",
        "coding_agent.agents.security",
    )
    for path in AGENTS.glob("*.py"):
        if path.name == "deepseek.py":
            continue
        imported = _imports(path)
        assert not any(name.startswith(forbidden) for name in imported), (path, imported)


def test_only_provider_layer_imports_openai_sdk():
    sdk_importers = []
    for path in SOURCE.rglob("*.py"):
        if any(name == "openai" or name.startswith("openai.") for name in _imports(path)):
            sdk_importers.append(path.relative_to(SOURCE).as_posix())
    assert sdk_importers == ["agents/providers/deepseek.py"]


def test_deepseek_depends_on_agent_models_not_agent_implementation():
    imported = _imports(AGENTS / "providers" / "deepseek.py")
    assert "coding_agent.agents.contracts" in imported
    assert "coding_agent.agents.agent" not in imported


def test_tool_handlers_depend_on_contracts_not_registry():
    for name in ("command.py", "filesystem.py"):
        imported = _imports(AGENTS / "tools" / name)
        assert "coding_agent.agents.tools.registry" not in imported
        assert "registry" not in imported


def test_command_rules_do_not_import_workspace_handler():
    imported = _imports(AGENTS / "security" / "command_policy.py")
    assert "coding_agent.agents.security.workspace" not in imported
    assert "workspace" not in imported


def test_agent_memory_does_not_import_runtime_or_web_orchestration():
    for path in (AGENTS / "memory").glob("*.py"):
        imported = _imports(path)
        assert not any(
            name.startswith(("coding_agent.agents.runtime", "coding_agent.router"))
            for name in imported
        ), (path, imported)


def test_tables_do_not_depend_on_data_access_or_services():
    for path in (SOURCE / "models").glob("*.py"):
        imported = _imports(path)
        assert not any(
            name.startswith(("coding_agent.repository.service", "coding_agent.services"))
            for name in imported
        ), (path, imported)


def test_api_does_not_import_database_implementation():
    api_files = [SOURCE / "main.py", SOURCE / "dependencies" / "services.py"]
    api_files.extend((SOURCE / "router").glob("*.py"))
    api_files.extend((SOURCE / "schemas").glob("*.py"))
    for path in api_files:
        imported = _imports(path)
        assert not any(name.startswith("sqlalchemy") for name in imported), (path, imported)
