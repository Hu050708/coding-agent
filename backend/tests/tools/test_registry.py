from __future__ import annotations

import json
import sys
from pathlib import Path

from clearloop.security import Workspace
from clearloop.tools import TOOL_SCHEMAS, ToolError, ToolRegistry
from clearloop.tools.command import ToolError as CommandToolError
from clearloop.tools.contracts import ToolError as ContractToolError
from clearloop.tools.filesystem import ToolError as FilesystemToolError
from clearloop.tools.registry import TOOL_SCHEMAS as RegistrySchemas
from clearloop.tools.registry import ToolError as RegistryToolError
from clearloop.tools.schemas import TOOL_SCHEMAS as SchemaModuleSchemas


def decode(payload: str) -> dict:
    value = json.loads(payload)
    assert isinstance(value, dict)
    return value


def test_registry_exposes_exactly_five_independent_schemas(tmp_path: Path) -> None:
    registry = ToolRegistry(Workspace(tmp_path))
    expected = {"list_files", "read_file", "write_file", "replace_text", "run_command"}
    assert {schema["function"]["name"] for schema in registry.schemas} == expected
    assert {schema["function"]["name"] for schema in TOOL_SCHEMAS} == expected

    first = registry.schemas
    first[0]["function"]["name"] = "mutated"
    assert "mutated" not in {schema["function"]["name"] for schema in registry.schemas}


def test_modular_contracts_keep_compatibility_reexports() -> None:
    assert ToolError is ContractToolError is RegistryToolError
    assert CommandToolError is ContractToolError
    assert FilesystemToolError is ContractToolError
    assert TOOL_SCHEMAS is SchemaModuleSchemas is RegistrySchemas


def test_registry_unknown_tool_and_invalid_argument_shape_are_json_errors(tmp_path: Path) -> None:
    registry = ToolRegistry(Workspace(tmp_path))
    unknown = decode(registry.execute("missing", {}))
    invalid = decode(registry.execute("list_files", []))  # type: ignore[arg-type]
    assert unknown["ok"] is False
    assert unknown["error"]["code"] == "unknown_tool"
    assert invalid["ok"] is False
    assert invalid["error"]["code"] == "invalid_arguments"


def test_registry_rejects_unknown_and_non_json_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry(Workspace(tmp_path))
    extra = decode(registry.execute("list_files", {"path": ".", "surprise": True}))
    nonfinite = decode(registry.execute("list_files", {"path": ".", "max_entries": float("nan")}))
    assert extra["error"]["code"] == "unknown_argument"
    assert nonfinite["error"]["code"] == "invalid_json_value"


def test_registry_returns_unified_success_envelope(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    response = decode(ToolRegistry(Workspace(tmp_path)).execute("list_files", {"path": "."}))
    assert response["ok"] is True
    assert response["data"]["entries"] == [{"path": "a.txt", "type": "file", "size_bytes": 1}]
    assert response["meta"]["returned"] == 1


def test_registry_rejects_exhausted_wall_time_before_handler(tmp_path: Path) -> None:
    registry = ToolRegistry(Workspace(tmp_path))
    response = decode(
        registry.execute(
            "write_file",
            {"path": "must-not-exist.txt", "content": "x"},
            timeout_seconds=0,
        )
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "wall_time_exceeded"
    assert not (tmp_path / "must-not-exist.txt").exists()


def test_registry_rejects_nonfinite_wall_time(tmp_path: Path) -> None:
    response = decode(
        ToolRegistry(Workspace(tmp_path)).execute(
            "list_files", {"path": "."}, timeout_seconds=float("nan")
        )
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_timeout"


def test_registry_passes_pre_start_cancellation_to_command(tmp_path: Path) -> None:
    target = tmp_path / "must-not-exist.txt"
    registry = ToolRegistry(
        Workspace(tmp_path),
        auto_approve=True,
        cancel_check=lambda: True,
    )

    response = decode(
        registry.execute(
            "run_command",
            {
                "argv": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('must-not-exist.txt').write_text('x')",
                ]
            },
        )
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "command_cancelled"
    assert not target.exists()
