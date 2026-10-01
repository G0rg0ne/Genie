# Genie — Project Rules

Rules for any AI agent (or human) working on this repository. Read this file before
making changes. For step-by-step playbooks for common tasks, see [`SKILLS.md`](SKILLS.md).

---

## 1. What this project is

Genie is a LangGraph research agent (**planner → researcher ⇄ tools → writer**) exposed as an
**OpenAI-compatible** `/v1/chat/completions` API, consumed by **LibreChat** as a custom endpoint.

| Service | Location | Role |
|---------|----------|------|
| `api` | `app/` | FastAPI + LangGraph agent, port `8000` |
| `mcp` | `mcp/` | MCP server exposing `scrape_link` (Firecrawl), port `8080`, streamable HTTP at `/mcp` |
| `librechat` | `librechat/` | Chat UI (Compose service), port `3080` |
| Langfuse | external | Self-hosted prompt management + tracing (NOT started by Compose) |

There is no `backend/`, `frontend/`, or `shared/` directory and no database owned by Genie.
Do not create that structure; follow the layout below.

---

## 2. Repository layout

```
Genie/
├── app/                        # API service (Docker WORKDIR /app)
│   ├── main.py                 # FastAPI app + lifespan (Langfuse init, prompt load, graph build)
│   ├── agents/genie_graph.py   # LangGraph graph, nodes, routers, tools, LLM
│   ├── api/routes/             # health.py, models.py, completions.py
│   ├── core/config.py          # pydantic-settings `Settings`
│   ├── core/langfuse_client.py # prompt loading, PromptBundle, trace config, flush
│   ├── core/mcp_client.py
│   ├── schemas/                # Pydantic models: AgentState, Plan, TitleOutput, ...
│   ├── pyproject.toml          # uv project (deps + `dev` group)
│   └── uv.lock
├── mcp/                        # MCP service (own pyproject/uv.lock)
│   └── search_mcp.py
├── utils/                      # Shared by api + mcp: logger.py, sse.py
├── tests/                      # pytest suite (not maintained by agents, see §10)
├── librechat/librechat.yaml
├── Dockerfile-api, Dockerfile-mcp, docker-compose.yml
├── .github/workflows/build-and-push.yml
├── pytest.ini
├── README.md                   # Living documentation
└── DEVELOPMENT.md              # Changelog / dev log
```

### Import rules (important)

- Code under `app/` imports **relative to `app/`**, without an `app.` prefix:
  `from core.config import Settings`, `from agents.genie_graph import llm`, `from schemas.agent import AgentState`.
- `utils/` is imported as a top-level package: `from utils.sse import emit_status`.
  In Docker, `utils/` is copied into `/app/utils/`; in tests, `pytest.ini` sets `pythonpath = app .`.
- Never add `sys.path` hacks. If a new top-level folder must be importable by the API,
  update **both** `Dockerfile-api` (COPY) and `pytest.ini` (`pythonpath`).
- `app/` and `mcp/` are **separate uv projects**. Do not import `app/` code from `mcp/` or vice versa;
  only `utils/` is shared.

---

## 3. Tech stack & dependencies

- Python **3.12+** (`requires-python = ">=3.12"`, Docker image `python:3.12-slim`).
- FastAPI, Uvicorn, LangGraph, LangChain (`langchain-openai`, `langchain-tavily`, `langchain-mcp-adapters`),
  Langfuse SDK, pydantic-settings, loguru.
- Dependency management is **uv only**. Never add `requirements.txt` or use bare `pip install`.
  - Add a runtime dep: `cd app && uv add <pkg>` (or `cd mcp && uv add <pkg>`).
  - Add a dev dep: `cd app && uv add --group dev <pkg>`.
  - Always commit the updated `uv.lock`; Docker builds use `uv sync --locked` and fail on a stale lock.
- Do not introduce LangSmith usage. `langsmith` exists only as a transitive dependency.
- Log new/removed dependencies in `DEVELOPMENT.md` and the README tech stack table.

---

## 4. Code style

- PEP 8, type hints on all functions; prefer `X | None` over `Optional[X]` and builtin generics (`list[str]`).
- Docstrings on public functions/classes. Comments only for constraints the code cannot show.
- Use **Pydantic** models for structured data (graph state, LLM structured output, MCP tool I/O).
- Use **loguru** (`from loguru import logger`) and call `setup_logging()` from `utils.logger`
  at module import, matching existing modules. No `print()`.
- Prefer `async` for I/O. Graph nodes may be sync or async; anything calling MCP tools or awaiting I/O must be async.
- Keep error messages explicit and actionable (include the prompt/tool/URL name).

---

## 5. Configuration & secrets

- All configuration goes through `core.config.Settings` (pydantic-settings, `extra="ignore"`).
  Field names map to upper-case env vars (`model_name` → `MODEL_NAME`).
- Required settings use `Field(..., description=...)`; optional ones have defaults.
- **Never** hardcode keys, commit `.env`, `mcp/.mcp.env`, or print secrets in logs.
- When adding an env var, update **all** of:
  1. `Settings` in `app/core/config.py` (if the API reads it),
  2. `.env.example` (create it if missing — placeholder values only),
  3. the README "Environment variables" table,
  4. `DEVELOPMENT.md`.
- MCP service config lives in `mcp/.mcp.env` (`FC_KEY`, `MCP_HOST`, `MCP_PORT`, `SERVICE_VERSION`).

---

## 6. API contract (do not break)

The API must stay **OpenAI Chat Completions compatible** because LibreChat depends on it.

- Endpoints: `GET /health`, `GET /v1/models`, `POST /v1/chat/completions`.
- Non-streaming response: `object: "chat.completion"`, `choices[0].message.content`.
- Streaming response (`"stream": true`): `text/event-stream`, each event `data: {json}\n\n`
  with `object: "chat.completion.chunk"`, ending with a `finish_reason: "stop"` chunk then `data: [DONE]\n\n`.
  - First chunk sets `delta.role = "assistant"`.
  - Progress/status updates go in `delta.reasoning_content` (via `emit_status` → `custom` stream mode).
  - Only tokens from the node named by `ANSWER_NODE` (`"writer"`) are streamed as `delta.content`.
  - Errors mid-stream are emitted as a content chunk (`⚠️ Agent error: ...`) and the stream still closes properly.
  - Keep headers `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`.
- Title requests: non-streaming, last message starts with `TITLE_REQUEST::` → short title via `TitleOutput`.
- Error responses use `{"error": {"message": "..."}}` with an appropriate status code (400 for bad input, 500 for agent failure).
- New endpoints: add a router in `app/api/routes/`, include it in `app/main.py`, add schemas in `app/schemas/`,
  document in README "API endpoints". Keep OpenAI-style paths under `/v1/`.

---

## 7. Agent graph rules (`app/agents/genie_graph.py`)

- State is `schemas.agent.AgentState` (Pydantic). Nodes return a **partial dict** of updated fields;
  list fields with `add_messages` are appended, not replaced.
- Routing functions are pure, typed with `Literal[...]` return values.
- The researcher is capped by `MAX_SEARCHES`; once reached, the LLM is invoked **without** tools to force synthesis.
  Keep `parallel_tool_calls=False` unless status labels and the cap logic are updated together.
- Every node should emit a user-facing status with `emit_status(get_stream_writer(), "...")`.
- Tools must **never raise** into the graph for expected failures; return a descriptive string
  (see `web_search` + `_normalize_tavily_response`). External API payloads must be type-checked defensively.
- The graph is built once in the FastAPI lifespan and stored on `app.state.graph`; routes read it from `req.app.state`.
  Do not rebuild the graph per request.
- Renaming the `writer` node requires updating `ANSWER_NODE` in `completions.py`.

---

## 8. Prompts & Langfuse

- Prompts live in **Langfuse Prompt Management**, not in code. Required chat prompts:
  `planner-prompt`, `researcher-prompt`, `writer-synth-prompt` (see `PROMPT_NAMES`).
- Template variables currently used:
  - planner: `date`, `chat_history`, `question`
  - researcher: `date`, `MAX_SEARCHES`, `question`, `bullets`
  - writer: `notes`, `question`
  Changing variables in code requires the matching Langfuse prompt change (and vice versa) — call it out in `DEVELOPMENT.md`.
- Prompts are loaded **once at startup** and fail fast (missing prompt, wrong type, or fallback → `LangfusePromptError`).
  Keep that behavior; do not silently fall back to inline prompts.
- Prompts are converted with `metadata={"langfuse_prompt": ...}` so generations link to prompt versions — preserve this.
- Every LLM/graph invocation in a request must pass a config from `build_trace_config(...)`
  (fresh `CallbackHandler` per request, with `run_name`, user/session ids when provided).
- Tracing is **best-effort**: Langfuse failures must never turn a successful completion into an error.
  `flush_langfuse` runs on shutdown and must not raise.

---

## 9. MCP server (`mcp/`)

- Tools are declared with `@mcp.tool()` and use `Annotated[..., Field(description=...)]` parameters
  and a Pydantic return model. Write rich docstrings — the LLM reads them to decide when to call the tool.
- Reuse clients via `@lru_cache` factories; never create SDK clients per call.
- Adding a tool there makes it available to the agent automatically (via `MultiServerMCPClient`);
  add a matching status label in `researcher_node` if it should show a friendly message.

---

## 10. Testing — NOT required

- **Do not write, update, or run tests in `tests/*`.** Implement features and fixes directly.
- Do not create new test files, test fixtures, or regression tests unless the user explicitly asks.
- Do not block or delay a task on the test suite; existing tests may be left out of date.
- Verify changes instead by: checking lints on touched files, and (when useful) running the app and
  smoke-testing the endpoint as in `SKILLS.md` skill 2.
- If the user explicitly asks for tests: pytest + pytest-asyncio (`asyncio_mode = auto`), config in `pytest.ini`,
  run with `cd app && uv run pytest ../tests -v`, mock all external services.

---

## 11. Docker, Compose & CI

- `docker compose up --build` runs `api`, `mcp`, `librechat`, `librechat-mongo`. Langfuse is external.
- Inside Compose, the API reaches MCP at `http://mcp:8080/mcp` (not `localhost`).
- API image: `uvicorn main:app` from `/app`. Keep `UV_NO_DEV=1`; dev deps must not ship.
- CI (`.github/workflows/build-and-push.yml`) runs on `v*` tags: gitleaks secret scan, build + push
  `genie-api` and `genie-mcp` to GHCR. Do not weaken the secret scan.

---

## 12. Documentation (mandatory)

After **every** completed task:

1. **README.md** — update features, endpoints, env vars, dependencies, setup/run/test instructions as relevant.
2. **DEVELOPMENT.md** — prepend a new entry at the top (newest first), using:

   ```markdown
   ## [YYYY-MM-DD HH:MM] - FEATURE | BUGFIX | REFACTOR | CONFIG | DOCS

   ### Changes
   - ...

   ### Files Modified
   - `path/to/file.py`

   ### Rationale
   ...

   ### Breaking Changes
   None | ...

   ### Next Steps
   - ...
   ```

   Add a `### Dependencies added/removed` section when dependencies change.
3. **`.env.example`** — update when env vars change.
4. Tell the user what docs changed and suggest a commit message, e.g.
   `fix(agent): handle string Tavily responses (see DEVELOPMENT.md 2026-10-01)`.

---

## 13. Git & safety

- Small, focused commits with conventional prefixes (`feat`, `fix`, `refactor`, `docs`, `chore`, `test`).
- Never commit secrets, `.env` files, `.venv/`, `__pycache__/`, or LibreChat runtime data (`librechat/uploads`, `logs`, `images`).
- Don't run destructive git commands (force push, reset --hard, branch deletion) without explicit user approval.
- Don't rewrite unrelated code while fixing something; mention unrelated issues to the user instead.
