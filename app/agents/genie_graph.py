import json
from datetime import date
from typing import Any, Literal

from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from core.config import Settings
from core.langfuse_client import PromptBundle
from schemas.agent import AgentState, Plan
from utils.logger import setup_logging
from utils.sse import emit_status, extract_text, short

setup_logging()
settings = Settings()

MAX_RESEARCH_TOOL_CALLS = 3

#Default agent's tools
_tavily = TavilySearch(
    max_results=5,
    topic="general",
    search_depth="basic",
    include_answer=False,
)

def _normalize_tavily_response(raw: Any) -> dict[str, Any] | str:
    """Tavily may return a dict, a JSON string, or a plain error string."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(parsed, dict):
            return parsed
        return raw
    return f"Unexpected search response type: {type(raw).__name__}"

@tool(description="Search the web for current information. Use a focused, specific query.")
def web_search(query:str)->str:
    try:
        raw_search_results = _tavily.invoke({"query": query})
    except Exception as exc:
        return f"Search failed: {exc}"

    normalized = _normalize_tavily_response(raw_search_results)
    if isinstance(normalized, str):
        return f"Search failed: {normalized}"

    results = normalized.get("results") or []
    if not isinstance(results, list):
        return f"Search failed: unexpected results payload: {results!r}"

    chunks = []
    for r in results:
        if not isinstance(r, dict):
            continue
        chunks.append(
            f"[{r.get('url', '')}]\n{r.get('title', '')}\n{r.get('content', '')}"
        )
    return "\n\n".join(chunks) if chunks else "No results found."

#MCP tools
_mcp_client = MultiServerMCPClient(
    {
        "deep_search": {
            "transport": "streamable_http",
            "url": settings.mcp_server_url,
        },
    }
)
_mcp_tools_cache: list | None = None
async def get_tools() -> list:
    """Returns the full tool list, lazily fetching MCP tools once and caching them."""
    global _mcp_tools_cache
    if _mcp_tools_cache is None:
        _mcp_tools_cache = await _mcp_client.get_tools()
    return [web_search, *_mcp_tools_cache]

# Define LLM call
llm = ChatOpenAI(model=settings.model_name, use_responses_api=True)

def route_after_plan(state: AgentState) -> Literal["researcher", "writer"]:
    return "researcher" if state.needs_research else "writer"

def route_after_research(state: AgentState) -> Literal["tools", "writer"]:
    last = state.research_messages[-1]
    return "tools" if last.tool_calls else "writer"

async def build_agent_graph(prompts: PromptBundle):
    mcp_client = MultiServerMCPClient(
        {
            "deep_search": {
                "transport": "streamable_http",
                "url": settings.mcp_server_url,
            },
        }
    )
    mcp_tools = await mcp_client.get_tools()
    tools = [web_search, *mcp_tools]

    def planner_node(state: AgentState) -> dict:
        status = get_stream_writer()
        emit_status(status, "🧭 Planning the approach...")
        formatted_prompt = prompts.planner.invoke({
            "date": date.today().isoformat(),
            "chat_history": state.chat_history,
            "question": state.question,
        })
        planer_response = llm.with_structured_output(Plan).invoke(formatted_prompt)

        return {
            "needs_research": planer_response.needs_research,
            "sub_questions": planer_response.sub_questions,
        }

    async def researcher_node(state: AgentState) -> dict:
        status = get_stream_writer()
        history = state.research_messages
        seed = []
        if not history:
            bullets = "\n".join(f"- {q}" for q in state.sub_questions)
            seed = prompts.researcher.invoke({
                "date": date.today().isoformat(),
                # Keep the existing Langfuse variable name while treating it
                # as a total tool-call ceiling in the researcher prompt.
                "MAX_SEARCHES": MAX_RESEARCH_TOOL_CALLS,
                "question": state.question,
                "bullets": bullets,
            }).to_messages()
        convo = [*history, *seed]
        used_tool_calls = sum(
            1
            for message in convo
            if isinstance(message, AIMessage) and message.tool_calls
        )
        model = (
            llm.bind_tools(tools, parallel_tool_calls=False)
            if used_tool_calls < MAX_RESEARCH_TOOL_CALLS
            else llm
        )
        reply = model.invoke(convo)
        out: dict = {"research_messages": [*seed, reply]}

        if reply.tool_calls:
            call = reply.tool_calls[0]
            tool_name = call["name"]
            args = call["args"]
            step = f"{used_tool_calls + 1}/{MAX_RESEARCH_TOOL_CALLS}"

            if tool_name == "web_search":
                label = f"🔍 Research step {step}: Search {short(args.get('query', ''))}"
            elif tool_name == "scrape_link":
                label = f"📄 Research step {step}: Reading {short(args.get('link', ''))}"
            else:
                label = f"🔧 Research step {step}: Calling {tool_name}..."

            emit_status(status, label)
        else:
            emit_status(status, "Synthesizing findings...")
            out["notes"] = extract_text(reply.content)

        return out

    def writer_node(state: AgentState) -> dict:
        status = get_stream_writer()
        emit_status(status, "✍️ Writing the answer...")
        notes = state.notes or "(no research was performed)"
        formatted_prompt = prompts.writer.invoke({
            "notes": notes,
            "question": state.question,
        })
        reporter_response = llm.invoke(formatted_prompt)
        return {"answer": reporter_response.text}

    builder = StateGraph(AgentState)
    builder.add_node("planner", planner_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("tools", ToolNode(tools, messages_key="research_messages"))
    builder.add_node("writer", writer_node)

    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", route_after_plan)
    builder.add_conditional_edges("researcher", route_after_research)
    builder.add_edge("tools", "researcher")
    builder.add_edge("writer", END)

    return builder.compile()
