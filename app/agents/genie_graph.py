from loguru import logger
from datetime import date
from typing import Literal
from langsmith import Client
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from langchain_mcp_adapters.client import MultiServerMCPClient
from schemas.agent import AgentState,Plan
from core.config import Settings
from langgraph.config import get_stream_writer
from utils.sse import extract_text, short, emit_status
from utils.logger import setup_logging
from functools import partial

setup_logging()
settings = Settings()


#Default agent's tools
_tavily = TavilySearch(
    max_results=1,
    topic="general",
    search_depth="basic",
    include_answer=False,
)

@tool(description="Search the web for current information. Use a focused, specific query.")
def web_search(query:str)->str:
    try : 
        raw_search_results = _tavily.invoke({"query": query})
    except Exception as exc: 
        return f"Search failed: {exc}"
    chunks = [
        f"[{r['url']}]\n{r['title']}\n{r['content']}"
        for r in raw_search_results.get("results", [])
    ]
    final_results = "\n\n".join(chunks) if chunks else "No results found."
    return final_results

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
llm =  ChatOpenAI(model=settings.model_name,use_responses_api=True)
client = Client()
PLANNER_PROMPT = client.pull_prompt("planner-prompt")
RESEARCHER_PROMPT = client.pull_prompt("researcher-prompt")
WRITER_PROMPT = client.pull_prompt("writer-synth-prompt")

def planner_node(state: AgentState) -> dict:
    status = get_stream_writer()
    emit_status(status, "🧭 Planning the approach...")
    formatted_prompt = PLANNER_PROMPT.invoke({
        "date": date.today().isoformat(),
        "chat_history": state.chat_history,
        "question": state.question,
    })
    planer_response = llm.with_structured_output(Plan).invoke(formatted_prompt)

    return {
        "needs_research": planer_response.needs_research,
        "sub_questions": planer_response.sub_questions,
    }

def route_after_plan(state: AgentState) -> Literal["researcher", "writer"]:
    return "researcher" if state.needs_research else "writer"

#Define researcher
async def researcher_node(state: AgentState, tools: list) -> dict:
    MAX_SEARCHES = 6
    status = get_stream_writer()
    history = state.research_messages
    seed = []
    if not history:
        bullets = "\n".join(f"- {q}" for q in state.sub_questions)
        seed = RESEARCHER_PROMPT.invoke({
            "date": date.today().isoformat(),
            "MAX_SEARCHES": MAX_SEARCHES,
            "question": state.question,
            "bullets": bullets,
        }).to_messages()
    convo = [*history, *seed]
    used = sum(1 for m in convo if isinstance(m, AIMessage) and m.tool_calls)
    model = (
        llm.bind_tools(tools, parallel_tool_calls=False)
        if used < MAX_SEARCHES
        else llm
    )
    reply = model.invoke(convo)
    out: dict = {"research_messages": [*seed, reply]}

    if reply.tool_calls:
        call = reply.tool_calls[0]
        tool_name = call["name"]
        args = call["args"]

        if tool_name == "web_search":
            label = f"🔍 Search {used+1}/{MAX_SEARCHES}: {short(args.get('query', ''))}"
        elif tool_name == "scrape_link":
            label = f"📄 Reading {short(args.get('link', ''))}"
        else:
            label = f"🔧 Calling {tool_name}..."

        emit_status(status, label)
    else:
        emit_status(status, "Synthesizing findings...")
        out["notes"] = extract_text(reply.content)

    return out

def route_after_research(state: AgentState) -> Literal["tools", "writer"]:
    last = state.research_messages[-1]
    return "tools" if last.tool_calls else "writer"

#Define synthesizer
def writer_node(state: AgentState) -> dict:
    status = get_stream_writer()
    emit_status(status, "✍️ Writing the answer...")
    notes = state.notes or "(no research was performed)"
    formatted_prompt = WRITER_PROMPT.invoke({"notes": notes,"question":state.question})
    reporter_response = llm.invoke(formatted_prompt)
    return {"answer": reporter_response.text}

async def build_agent_graph():
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

    def make_researcher_node(tools: list):
        async def _researcher_node(state: AgentState) -> dict:
            return await researcher_node(state, tools)
        return _researcher_node

    builder = StateGraph(AgentState)
    builder.add_node("planner", planner_node)
    builder.add_node("researcher", make_researcher_node(tools))
    builder.add_node("tools", ToolNode(tools, messages_key="research_messages"))
    builder.add_node("writer", writer_node)

    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", route_after_plan)
    builder.add_conditional_edges("researcher", route_after_research)
    builder.add_edge("tools", "researcher")
    builder.add_edge("writer", END)

    return builder.compile()