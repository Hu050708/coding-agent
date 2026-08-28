"""验证数据库表、索引和约束符合持久化模型。"""

from __future__ import annotations

from pathlib import Path

from coding_agent.models import Base


EXPECTED_TABLES = {
    "workspaces",
    "conversations",
    "runs",
    "messages",
    "run_events",
    "approvals",
    "memory_entries",
    "run_memories",
}


def test_metadata_contains_only_the_frozen_durable_entities() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_schema_has_no_hidden_reasoning_or_raw_output_columns() -> None:
    forbidden = {
        "reasoning",
        "chain_of_thought",
        "provider_response",
        "raw_response",
        "tool_output",
        "environment",
        "database_url",
    }
    columns = {
        column.name
        for table in Base.metadata.tables.values()
        for column in table.columns
    }
    assert forbidden.isdisjoint(columns)


def test_run_active_workspace_and_request_id_constraints_exist() -> None:
    runs = Base.metadata.tables["runs"]
    assert any(
        index.name == "uq_runs_one_active_per_workspace" and index.unique
        for index in runs.indexes
    )
    assert any(
        constraint.name == "uq_runs_conversation_client_request"
        for constraint in runs.constraints
    )


def test_compose_uses_isolated_loopback_postgres_without_a_password_default() -> None:
    backend = Path(__file__).resolve().parents[2]
    compose = (backend / "deploy" / "compose.yml").read_text(encoding="utf-8")
    assert "container_name: coding-agent-postgres" in compose
    assert "pgvector/pgvector:0.8.6-pg17-bookworm" in compose
    assert '"127.0.0.1:5434:5432"' in compose
    assert "coding_agent_postgres_data" in compose
    assert (
        "POSTGRES_PASSWORD: ${CODING_AGENT_POSTGRES_PASSWORD:?Set "
        "CODING_AGENT_POSTGRES_PASSWORD in backend/.env}"
    ) in compose
    assert "POSTGRES_PASSWORD: coding_agent" not in compose
