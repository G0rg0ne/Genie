# Genie — Agent Skills

Step-by-step playbooks for recurring tasks in this repository. Each skill lists **when to use it**,
**steps**, and a **done checklist**. Always follow [`RULES.md`](RULES.md) as well; the documentation
step (README + DEVELOPMENT.md) applies to every skill and is not repeated in full each time.

| # | Skill | Use when |
|---|-------|----------|
| 1 | [Orient in the repo](#1-orient-in-the-repo) | Starting any task |
| 2 | [Run & verify locally](#2-run--verify-locally) | Need to test changes end-to-end |
| 3 | [Run the test suite](#3-run-the-test-suite) | **Only if the user explicitly asks** |
| 4 | [Add an agent tool (in-process)](#4-add-an-agent-tool-in-process) | New LangChain tool for the researcher |
| 5 | [Add an MCP tool](#5-add-an-mcp-tool) | New tool served by the `mcp` service |
| 6 | [Add or change a graph node](#6-add-or-change-a-graph-node) | Changing agent flow |
| 7 | [Change a prompt / prompt variables](#7-change-a-prompt--prompt-variables) | Editing Langfuse prompts or their inputs |
| 8 | [Add an environment variable](#8-add-an-environment-variable) | New config / secret |
| 9 | [Add an API endpoint](#9-add-an-api-endpoint) | New HTTP route |
| 10 | [Debug a failing request](#10-debug-a-failing-request) | Errors in the API, stream, or tools |
| 11 | [Add or update a dependency](#11-add-or-update-a-dependency) | Any package change |
| 12 | [Write tests with mocks](#12-write-tests-with-mocks) | **Only if the user explicitly asks** |
| 13 | [Update documentation](#13-update-documentation) | End of every task |
| 14 | [Release](#14-release) | Publishing new images |

---

## 1. Orient in the repo

1. Read `README.md` and the top entries of `DEVELOPMENT.md` (newest first).
2. Read `.cursor/RULES.md`.
3. Locate the relevant module:
   - request handling / SSE → `app/api/routes/completions.py`, `utils/sse.py`
   - agent flow, tools, LLM → `app/agents/genie_graph.py`
   - state & structured output → `app/schemas/agent.py`
   - prompts & tracing → `app/core/langfuse_client.py`
   - settings → `app/core/config.py`
   - startup wiring → `app/main.py`
   - scraping tool → `mcp/search_mcp.py`
4. Check `git status` so you don't overwrite the user's uncommitted work.

---

## 2. Run & verify locally

**Full stack (preferred):**

```bash
docker compose up --build
```

- API: `http://localhost:8000` (docs at `/docs`), LibreChat: `http://localhost:3080`, MCP: `http://localhost:8080/mcp`.
- Requires `.env` (API + LibreChat) and `mcp/.mcp.env` (`FC_KEY`), plus reachable Langfuse with the three chat prompts.

**API only, outside Docker** (MCP must be running and `MCP_SERVER_URL=http://localhost:8080/mcp`):

```bash
cd app
uv sync --group dev
# PYTHONPATH must include the repo root so `utils` is importable
# PowerShell:  $env:PYTHONPATH = ".."
uv run uvicorn main:app --reload --port 8000
```

**Smoke tests:**

```bash
# non-streaming
curl -s http://localhost:8000/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"Genie","messages":[{"role":"user","content":"What is LangGraph?"}]}'

# streaming
curl -N http://localhost:8000/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"Genie","stream":true,"messages":[{"role":"user","content":"Latest Python release?"}]}'
```

Done when: both return successfully, the stream ends with `data: [DONE]`, and one trace per request appears in Langfuse.

---

## 3. Run the test suite

> Tests are **not required** in this project (see `RULES.md` §10). Implement directly; use this
> skill only when the user explicitly asks to run tests.

```bash
cd app
uv sync --group dev
uv run pytest ../tests -v
```

- Run a single file: `uv run pytest ../tests/test_web_search.py -v`.
- If imports fail with `ValidationError` on `Settings`, a required env var is missing from `tests/conftest.py`.
- If `ModuleNotFoundError: utils`, check `pythonpath = app .` in `pytest.ini` and that you run from a path where it applies.

Done when: all tests pass with no network access.

---

## 4. Add an agent tool (in-process)

Use for lightweight tools that live inside the API (like `web_search`).

1. In `app/agents/genie_graph.py`, define the tool:

   ```python
   @tool(description="One clear sentence on when the model should use this tool.")
   def my_tool(arg: str) -> str:
       try:
           raw = client.call(arg)
       except Exception as exc:
           return f"my_tool failed: {exc}"
       # validate raw defensively (dict vs str vs JSON string) before using it
       return formatted_text
   ```

2. Add it to the `tools` list in `build_agent_graph` (and to `get_tools()` if that helper is used).
3. Add a status label branch in `researcher_node` (e.g. `elif tool_name == "my_tool": label = "..."`).
4. If it needs credentials, follow [skill 8](#8-add-an-environment-variable).
5. If the researcher prompt should mention the tool, follow [skill 7](#7-change-a-prompt--prompt-variables).
Done when: the tool never raises for expected failures and README lists the tool.

---

## 5. Add an MCP tool

Use for heavier tools or ones with their own secrets/dependencies.

1. In `mcp/search_mcp.py` add:

   ```python
   class MyResult(BaseModel):
       field: str = Field(description="...")

   @mcp.tool()
   def my_tool(
       param: Annotated[str, Field(description="Precise description, with an example value.")],
   ) -> MyResult:
       """What it does, when to use it, when NOT to use it, Args, Returns, Raises, Example."""
       ...
   ```

2. Reuse SDK clients through an `@lru_cache(maxsize=1)` factory.
3. New deps: `cd mcp && uv add <pkg>`; new env vars go in `mcp/.mcp.env` (document them).
4. The API picks the tool up automatically through `MultiServerMCPClient` at graph build time —
   restart the `api` container after `mcp` changes (tools are fetched once on startup).
5. Add a friendly status label in `researcher_node` for the new tool name.

Done when: `docker compose up --build` shows the tool being called in a streamed request.

---

## 6. Add or change a graph node

1. Add any new state fields to `AgentState` in `app/schemas/agent.py` with `Field(default..., description=...)`.
   Use `Annotated[list[AnyMessage], add_messages]` for message lists.
2. Write the node inside `build_agent_graph` so it can close over `prompts` and `tools`:
   - start with `emit_status(get_stream_writer(), "<emoji> Doing X...")`,
   - return only the fields it updates.
3. Wire it with `builder.add_node` / `add_edge` / `add_conditional_edges`. Routers return `Literal[...]`.
4. If the node produces the final user-visible answer, keep it named `writer` or update `ANSWER_NODE` in `completions.py`.
5. If it needs a new prompt, add it to `PROMPT_NAMES` + `PromptBundle` and create it in Langfuse ([skill 7](#7-change-a-prompt--prompt-variables)).
Done when: streaming still shows status lines in `reasoning_content` and only answer tokens in `content`.

---

## 7. Change a prompt / prompt variables

Prompts are **not** in the repo — they live in Langfuse.

- **Text-only change:** edit the prompt in the Langfuse UI and promote it to the `production` label. No code change; restart the API (prompts load at startup).
- **Variable change:**
  1. Update the dict passed to `prompts.<name>.invoke({...})` in `genie_graph.py`.
  2. Update the prompt in Langfuse to use exactly the same variable names.
  3. Update the variable list in `RULES.md` §8 and the README prerequisites.
  4. Note the coordinated change under **Breaking Changes** in `DEVELOPMENT.md` (deploy order matters).
- **New prompt:** add `(attr, "langfuse-name")` to `PROMPT_NAMES`, a field to `PromptBundle`,
  and create the **chat**-type prompt in Langfuse.

Done when: startup succeeds (no `LangfusePromptError`) and traces show the linked prompt version.

---

## 8. Add an environment variable

1. Add the field to `Settings` (`app/core/config.py`): required → `Field(..., description=...)`, optional → default value.
2. Add a placeholder to `.env.example` (create the file if it doesn't exist; never real values).
3. Add a row to the README "Environment variables" table.
4. For MCP-only variables, use `os.environ.get(...)` in `mcp/search_mcp.py`, fail fast if required, and document in `mcp/.mcp.env` notes.
5. Log it in `DEVELOPMENT.md` (breaking change if required for startup).

---

## 9. Add an API endpoint

1. Request/response models in `app/schemas/<area>.py`.
2. Router in `app/api/routes/<area>.py`:

   ```python
   from fastapi import APIRouter
   router = APIRouter()

   @router.get("/v1/<resource>", response_model=MyResponse)
   async def get_resource() -> MyResponse:
       ...
   ```

3. Register in `app/main.py`: `app.include_router(<area>.router)`.
4. Access shared resources via `req.app.state` (`graph`, `prompts`, `langfuse`) — don't recreate them.
5. If it calls the LLM/graph, pass `config=build_trace_config(...)` with a meaningful `run_name`.
6. Errors: `{"error": {"message": ...}}` with proper status codes.
7. Add to README "API endpoints" table.

---

## 10. Debug a failing request

Follow evidence, don't guess.

1. Reproduce with the curl commands from [skill 2](#2-run--verify-locally) (try both streaming and non-streaming).
2. Read logs: `docker compose logs -f api` (and `mcp`). Errors are logged with the completion id `[chatcmpl-...]`.
3. Open the matching Langfuse trace (filter by `completion_id` metadata) to see which node/tool failed and its inputs.
4. Common causes:
   | Symptom | Likely cause |
   |---------|--------------|
   | API fails at startup with `LangfusePromptError` | Prompt missing, not `chat` type, or Langfuse unreachable / wrong keys |
   | `'str' object has no attribute 'get'` in tools | External API returned an error string; normalize the payload |
   | `Search failed: ...` in research notes | Invalid/missing `TAVILY_API_KEY` |
   | MCP connection errors at startup | `mcp` not running or `MCP_SERVER_URL` wrong (`http://mcp:8080/mcp` in Compose) |
   | `scrape_link` errors | Missing/invalid `FC_KEY`, or page has no content |
   | Stream shows status but no answer | Answer node renamed without updating `ANSWER_NODE` |
   | 400 "No user message found" | Request has no `role: "user"` message |
5. Fix the root cause directly, then re-run the same request to confirm it works.

---

## 11. Add or update a dependency

```bash
cd app   # or: cd mcp
uv add <package>              # runtime
uv add --group dev <package>  # tests/tooling only
uv lock --upgrade-package <package>  # bump a single package
```

- Commit `pyproject.toml` **and** `uv.lock` together.
- Rebuild the image (`docker compose up --build`) to verify `uv sync --locked` succeeds.
- Record it under "Dependencies added/removed" in `DEVELOPMENT.md` and update the README stack table if it's significant.

---

## 12. Write tests with mocks

> Do **not** write tests by default (see `RULES.md` §10). Use this skill only when the user explicitly asks for tests.

- Never call real OpenAI, Tavily, Firecrawl, MCP, or Langfuse.
- Patch at the usage site, e.g. `monkeypatch.setattr("agents.genie_graph._tavily", FakeTavily())`
  or `unittest.mock.patch("api.routes.completions.llm")`.
- For routes, build a minimal app or set `app.state.graph` to a fake with `ainvoke` / `astream`
  so the lifespan (which talks to Langfuse and MCP) isn't triggered.
- For streaming, collect the response body and assert on `data:` lines: opener with `role`, content chunks,
  final `finish_reason: "stop"`, then `[DONE]`.
- Async tests just use `async def test_...` (`asyncio_mode = auto`).
- See existing examples: `tests/test_web_search.py`, `tests/test_langfuse_client.py`, `tests/test_completions_tracing.py`.

---

## 13. Update documentation

At the end of every task:

1. **README.md** — update only the affected sections (structure, env vars, endpoints, testing, stack, deployment).
2. **DEVELOPMENT.md** — add a new entry at the **top** using the template in `RULES.md` §12, with the current date/time.
3. **`.env.example`** — if env vars changed.
4. In the final message to the user: summarize the change, list documentation updated, and suggest a commit message, e.g.

   ```
   feat(agent): add <tool> to researcher

   See DEVELOPMENT.md entry 2026-10-01 23:45.
   ```

---

## 14. Release

1. Ensure `DEVELOPMENT.md` has entries for everything going out.
2. Bump `version` in `app/pyproject.toml` (and `mcp/pyproject.toml` if changed).
3. Tag and push (only with the user's approval):

   ```bash
   git tag v0.x.y
   git push origin v0.x.y
   ```

4. The `Build, Scan, Publish, and Deploy` workflow scans for secrets and pushes `genie-api` and `genie-mcp` images to GHCR.
5. After deploy, run the smoke tests from [skill 2](#2-run--verify-locally) against the deployed URL.
