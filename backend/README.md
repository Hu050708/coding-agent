# ClearLoop backend

The backend contains the complete Python application: the coding-agent core,
the FastAPI transport, run orchestration, workspace-scoped SQLite memory,
command safety, diagnostics, tests, evaluation fixtures, and supporting
scripts. There is one import namespace: `clearloop`.

## Environment

Run all Python commands from this directory:

```powershell
conda env update -n clearloop-agent -f environment.yml
conda activate clearloop-agent
pip install -e ".[dev,web]"
```

Copy `.env.example` to `.env` if needed. The Web service reads
`DEEPSEEK_API_KEY` from that local file or the process environment; the CLI,
live smoke tests, and demo script read it from the current process environment
only. Never commit the real `.env` file.

## Start

Command-line agent:

```powershell
clearloop --workspace E:\code\your-project "Describe the coding task"
```

Loopback-only Web API:

```powershell
clearloop-web
```

The API listens on `http://127.0.0.1:8000` by default. Interactive API docs
are available at `/api/docs`.

## Project memory

The Web API reads enabled memory once at the start of each run. Writes only
happen through explicit memory CRUD requests or the UI's editable confirmation
flow; the model has no memory-writing tool. The default database is
`%LOCALAPPDATA%\ClearLoop\clearloop.db`, outside agent workspaces. Set
`CLEARLOOP_DATA_DIR` to another absolute local directory when needed; it must
remain outside `CLEARLOOP_ALLOWED_ROOT` so agent tools cannot modify the store.
Memory mutations are rejected while the same workspace has an active run, and
a run cannot start while a mutation for that workspace is in flight. Run-result
provenance is accepted only from a successfully completed retained run.

Memory storage failures degrade a run to `memory.status=unavailable`; they do
not stop the coding-agent loop. API summaries and SSE expose only status,
counts, and entry IDs, never memory content.

## Verify

```powershell
python -m pytest
python -m compileall -q src
python -m clearloop --help
clearloop-web --help
```

The independent demo trial is started with:

```powershell
python scripts/run_demo_trial.py
```
