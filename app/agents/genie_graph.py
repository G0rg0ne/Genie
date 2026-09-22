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

from schemas.agent import AgentState,Plan
from core.config import Settings
from langgraph.config import get_stream_writer
from utils.sse import extract_text
from utils.logger import setup_logging

setup_logging()
settings = Settings()
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

TOOLS = [web_search]

# Define LLM call
llm =  ChatOpenAI(model=settings.model_name,use_responses_api=True)
client = Client()
PLANNER_PROMPT = client.pull_prompt("planner-prompt")
RESEARCHER_PROMPT = client.pull_prompt("researcher-prompt")
WRITER_PROMPT = client.pull_prompt("writer-synth-prompt")

def planner_node(state: AgentState) -> dict:
    status = get_stream_writer()
    status({"status": "🧭 Planning the approach..."})
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
def researcher_node(state: AgentState) -> dict:
    MAX_SEARCHES = 4
    status = get_stream_writer()
    status({"status": "🔍 Search step ..."})

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
    status({"status": f"🔍 Executing search query ... ({used + 1}/{MAX_SEARCHES})"})
    model = (
        llm.bind_tools(TOOLS, parallel_tool_calls=False)
        if used < MAX_SEARCHES
        else llm
    )
    reply = model.invoke(convo)
    out: dict = {"research_messages": [*seed, reply]}

    if reply.tool_calls:
        query = reply.tool_calls[0]["args"].get("query", "")
        status({"status": f"🔎 Looking up: {query}" if query else "Calling tool..."})

    else:
        status({"status": "Synthesizing findings..."})
        out["notes"] = extract_text(reply.content)

    return out

def route_after_research(state: AgentState) -> Literal["tools", "writer"]:
    last = state.research_messages[-1]
    return "tools" if last.tool_calls else "writer"

#Define synthesizer
def writer_node(state: AgentState) -> dict:
    notes = state.notes or "(no research was performed)"
    formatted_prompt = WRITER_PROMPT.invoke({"notes": notes,"question":state.question})
    reporter_response = llm.invoke(formatted_prompt)
    return {"answer": reporter_response.text}

def agent_graph():
    builder = StateGraph(AgentState)
    builder.add_node("planner", planner_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("tools", ToolNode(TOOLS, messages_key="research_messages"))
    builder.add_node("writer", writer_node)
    
    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", route_after_plan)
    builder.add_conditional_edges("researcher", route_after_research)
    builder.add_edge("tools", "researcher")
    builder.add_edge("writer", END)
    
    graph = builder.compile()
    return graph