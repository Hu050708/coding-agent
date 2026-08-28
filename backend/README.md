# Coding Agent backend

The backend contains the self-authored coding-agent loop, DeepSeek adapter,
local tools and policies, the FastAPI transport, application services,
PostgreSQL persistence, run orchestration, tests, evaluation fixtures, and
submission documentation. There is one import namespace: `coding_agent`.

The CLI and Web service share the same core but have different outer
dependencies. The CLI does not require FastAPI, Docker, or a database. The Web
service requires its dedicated PostgreSQL database and fails explicitly when
the database is missing, unavailable, or cannot be migrated.

## Environment

Run Python commands from this directory:

```powershell
conda env create -f environment.yml
conda activate coding-agent
python -m pip install -e ".[dev,web]"
```

For an existing environment, use:

```powershell
conda env update -n coding-agent -f environment.yml
```

Create an untracked `.env` from `.env.example` for Web development. It must
contain the DeepSeek key, the allowed workspace root, a strong local database
password, and a loopback-only `postgresql+psycopg` URL. Never commit `.env` or
show its values in logs, screenshots, or videos.

## CLI

The command-line agent is database-independent:

```powershell
coding-agent --workspace E:\code\your-project "Describe the coding task"
```

It reads `DEEPSEEK_API_KEY` from the current process environment only and does
not load the Web `.env` file.

## Web startup

Start the components in this order.

1. Dedicated PostgreSQL:

```powershell
docker compose --env-file .env -f deploy/compose.yml up -d
```

The Compose project creates only container `coding-agent-postgres`, named
volume `coding_agent_postgres_data`, database/user `coding_agent`, and the
loopback binding `127.0.0.1:5434`.

2. Loopback-only API:

```powershell
conda activate coding-agent
coding-agent-web
```

The API defaults to `http://127.0.0.1:8000`; OpenAPI documentation is at
`/api/docs`. Startup applies Alembic migrations, checks the database, and marks
pre-restart active runs as `interrupted` with a replayable event.

3. Start the Vue frontend from `../frontend` with `npm run dev` and open
`http://127.0.0.1:5173/`.

## Web application boundary

`services/` coordinates the persistent catalog and the in-process
`RunManager`; `models/`, `repository/`, and `database/` separate SQLAlchemy
entities, transaction access, and database lifecycle; `router/`, `schemas/`,
and `dependencies/` form the HTTP boundary. The self-built loop, provider,
tools, permissions, runtime, memory context, and trace code live under
`agents/`.
PostgreSQL stores:

- canonical workspaces and restricted-directory selections;
- conversations and visible user/assistant messages;
- immutable run permission, status, usage, and timing;
- safe allow-listed run events for SSE replay;
- approval records and manually confirmed workspace memory.

The database deliberately has no fields for hidden reasoning, raw provider
responses, environment variables, or complete tool output. SSE first replays
database events after `Last-Event-ID`, then uses an in-memory notification to
avoid polling latency. One workspace may have only one active run; different
workspaces may run concurrently.

## Permission modes

The server freezes one mode for every run:

- `ask`: reads run directly; file changes and commands require one approval;
- `agent`: workspace changes and normal checks run directly; risky commands ask;
- `workspace_full`: every non-denied operation runs automatically in the workspace.

All three modes keep the same workspace boundary and immutable command denials.

## Conversation history and memory

Conversation messages and workspace memory are separate. Before a run starts,
the application atomically creates the run and user message, captures bounded
visible history, and freezes the actual memory set supplied to the model. The
memory snapshot is at most 32 entries and 32,000 content characters. The model
cannot write memory; users create or confirm it through explicit API/UI actions.

Memory mutations lock the workspace and are rejected while it has an active
run. The current release has no embeddings, vector retrieval, cross-workspace
profile, or automatic model-written memory.

`CODING_AGENT_DATA_DIR` now contains only private diagnostic traces. It defaults
to `%LOCALAPPDATA%\Coding Agent` and must stay outside
`CODING_AGENT_ALLOWED_ROOT`; PostgreSQL is the durable Web data store.

## Verify

```powershell
python -m pytest
python -m compileall -q src
python -m coding_agent --help
coding-agent-web --help
```

The independent demo trial is started with:

```powershell
python scripts/run_demo_trial.py
```
