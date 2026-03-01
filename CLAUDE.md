# CLAUDE.md — Právní Kvalifikátor

## Project Overview

LLM agent system for legal qualification of criminal acts (trestné činy) and misdemeanors (přestupky) in Czech law. Takes a textual description of an act and returns structured legal qualification with confidence scores.

## Architecture

```
Web Browser → FastAPI (:8000) → LangGraph Agents → MCP Client → MCP Server (:8001) → SQLite + sqlite-vec
```

Three main components:
- **MCP Server** (`src/pravni_kvalifikator/mcp/`) — FastMCP server with 9 tools for law database access
- **Agent Pipeline** (`src/pravni_kvalifikator/agents/`) — 5 LangGraph agents (law_identifier → head_classifier → paragraph_selector → qualifier → reviewer)
- **Web App** (`src/pravni_kvalifikator/web/`) — FastAPI with Jinja2 templates and SSE streaming

## Tech Stack

- **Language:** Python 3.12+
- **Package manager:** uv (NOT pip, NOT pipenv)
- **Web:** FastAPI + Uvicorn + Jinja2
- **MCP:** FastMCP (mcp package)
- **Agents:** LangGraph + langchain-openai
- **LLM:** Azure OpenAI (GPT-5.2 for agents, text-embedding-3-large for embeddings)
- **Database:** SQLite + sqlite-vec for vector search
- **Linting:** Ruff (check + format)
- **Testing:** pytest + pytest-asyncio

## Commands

```bash
# Install dependencies
uv sync

# Install dev dependencies
uv sync --group dev

# Run linter
uv run ruff check src/ tests/ scripts/

# Run formatter check
uv run ruff format --check src/ tests/ scripts/

# Run formatter (fix)
uv run ruff format src/ tests/ scripts/

# Run all tests
uv run pytest tests/ -v

# Run specific test
uv run pytest tests/test_parser.py -v

# Load laws into database (scrape + parse)
uv run python scripts/load_laws.py

# Generate embeddings
uv run python scripts/generate_embeddings.py

# Generate LLM metadata (chapter descriptions + paragraph structured metadata)
uv run python scripts/generate_metadata.py

# Start MCP server (STDIO mode)
uv run pq-mcp

# Start MCP server (SSE mode)
uv run uvicorn pravni_kvalifikator.mcp.server:app --port 8001

# Start web app
uv run pq-web
```

## Code Style

- **Language:** Code in English, comments/docstrings in Czech where they describe domain concepts
- **Line length:** 100 characters
- **Imports:** Sorted by Ruff (isort rules)
- **Type hints:** Use everywhere
- **Async:** All I/O operations are async (httpx, SQLite via aiosqlite would be overkill for our use — we use sync sqlite3 in thread pool)
- **Error handling:** Descriptive Czech error messages for user-facing errors
- **Configuration:** Pydantic Settings with `.env` file, singleton getter pattern
- **Constants:** `EMBEDDING_DIMENSIONS = 1536` in `shared/config.py`

## Project Structure

```
src/pravni_kvalifikator/
├── mcp/           # MCP server (FastMCP) — law database access
│   ├── main.py    # FastMCP tools (9 tools) + STDIO entry
│   ├── server.py  # Uvicorn SSE/HTTP transport (create_sse_app factory)
│   ├── db.py      # SQLite + sqlite-vec access layer
│   ├── embedder.py # Azure OpenAI embedding client
│   ├── parser.py  # HTML parser for zakonyprolidi.cz
│   ├── scraper.py # HTTP scraper (shared httpx.AsyncClient)
│   └── indexer.py # Pipeline: scrape → parse → DB + embeddings
├── agents/        # LangGraph agents
│   ├── orchestrator.py  # StateGraph + routing
│   ├── state.py         # QualificationState TypedDict
│   ├── activity.py      # Agent progress logging + SSE broadcast
│   ├── law_identifier.py    # Agent 0 (misdemeanors only)
│   ├── head_classifier.py   # Agent 1
│   ├── paragraph_selector.py # Agent 2
│   ├── qualifier.py         # Agent 3
│   └── reviewer.py          # Agent 4
├── web/           # FastAPI web application
│   ├── main.py    # FastAPI app (create_app factory + lifespan)
│   ├── routes.py  # HTTP + SSE endpoints
│   ├── session.py # Session management (SQLite + UUID)
│   ├── models.py  # Pydantic request/response models
│   ├── templates/ # Jinja2 templates
│   └── static/    # CSS, JS
└── shared/        # Shared utilities
    ├── config.py      # Global Pydantic Settings + constants
    ├── llm.py         # LLM client (retry, semaphore)
    └── mcp_client.py  # MCP SSE client for agents
scripts/
├── load_laws.py          # Scrape + parse + insert laws
├── generate_embeddings.py # Generate vector embeddings
└── generate_metadata.py  # LLM-generated chapter/paragraph metadata
tests/
├── conftest.py           # Shared fixtures (laws_db, session_db)
├── test_parser.py
├── test_db.py
├── test_mcp_tools.py
├── test_mcp_client.py
├── test_llm.py
├── test_agents.py
├── test_web.py
├── test_e2e.py
└── scenarios.py          # 12 real-world test scenarios
```

## Database

Two SQLite databases:
- `data/laws.db` — Laws, chapters, paragraphs, damage thresholds, vector tables (sqlite-vec)
- `data/sessions.db` — Web sessions, qualifications, agent logs

## Key Constants

- `EMBEDDING_DIMENSIONS = 1536` (text-embedding-3-large with explicit dimensions param)
- Damage thresholds per § 138 TZ: nikoli nepatrná (>=10 000 Kč), nikoli malá (>=50 000 Kč), větší (>=100 000 Kč), značná (>=1 000 000 Kč), velkého rozsahu (>=10 000 000 Kč)

## Testing Patterns

- Use pytest with `pytest-asyncio` for async tests
- Test files mirror source structure: `tests/test_parser.py`, `tests/test_mcp_tools.py`, etc.
- Shared fixtures in `tests/conftest.py` — `laws_db`, `session_db`, `mock_llm`, `e2e_laws_db`
- Mock external services (Azure OpenAI, zakonyprolidi.cz HTTP calls)
- E2E tests mock LLM but use real orchestrator routing logic

## Important Notes

- **Never commit `.env`** — use `.env.example` as template
- **Never commit `data/*.db`** — databases are generated from scripts
- **DO commit `uv.lock`** — required for reproducible builds
- Paragraphs use string IDs (e.g., "205a"), NOT integers
- Laws are identified by sbírkové číslo (e.g., "40/2009" for Trestní zákoník)
- MCP server is stateless — reads only from laws.db
- **NEVER name a file `logging.py`** in the agents package — it shadows Python's built-in `logging` module. Use `activity.py` instead.
- Agent nodes must return ONLY changed state keys — LangGraph merges automatically. Never return `{**state, ...}`.
- The `agents` package must NOT import from `web` package (circular dependency). Use callback pattern for DB persistence via `activity.register_db_logger()`.
- Web app uses `create_app()` factory with `lifespan` context manager (NOT deprecated `@app.on_event`).

