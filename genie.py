from re import M

from langsmith.run_helpers import R
from utils.logging_config import setup_logging

setup_logging()
from loguru import logger
from datetime import date
import os
import sys
from typing import Annotated, Literal, TypedDict

from langsmith import Client
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState, START, END
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from pydantic import BaseModel, Field

load_dotenv()
MODEL_NAME = os.getenv("MODEL_NAME","gpt-4o-mini")
_tavily = TavilySearch(
    max_results=1,
    topic="general",
    search_depth="basic",   # "advanced" costs more credits, better recall
    include_answer=False,   # let *your* model synthesize, not Tavily's
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
llm =  ChatOpenAI(model=MODEL_NAME,use_responses_api=True)
client = Client()
PLANNER_PROMPT = client.pull_prompt("planner")
RESEARCHER_PROMPT = client.pull_prompt("researcher-1")
WRITER_PROMPT = client.pull_prompt("reporter-writer")

#templated = prompt.format_messages(question=question)
class AgentState(TypedDict):
    question: str
    sub_questions: list[str]
    needs_research: bool
    research_messages: Annotated[list, add_messages]
    notes: str
    answer: str

#Define planer :
class Plan(BaseModel):
    """Structured output forces the planner to commit to a decision."""
 
    needs_research: bool = Field(
        description="True if answering requires current/external facts. "
        "False for timeless, definitional, or reasoning-only questions."
    )
    sub_questions: list[str] = Field(
        default_factory=list,
        description="2-4 specific, independently searchable sub-questions. "
        "Empty if no research is needed.",
    )

def planner_node(state: AgentState) -> dict:
    formatted_prompt = PLANNER_PROMPT.invoke({
        "date": date.today().isoformat(),
        "question": state["question"]
    })
    planer_response = llm.with_structured_output(Plan).invoke(formatted_prompt)

    return {
        "needs_research": planer_response.needs_research,
        "sub_questions": planer_response.sub_questions,
    }

def route_after_plan(state: AgentState) -> Literal["researcher", "writer"]:
    return "researcher" if state["needs_research"] else "writer"
#Define researcher

def researcher_node(state: AgentState) -> dict:
    MAX_SEARCHES = 4
    history = state.get("research_messages", [])
    seed = []
    if not history:
        bullets = "\n".join(f"- {q}" for q in state["sub_questions"])
        seed = RESEARCHER_PROMPT.invoke({
                "date": date.today().isoformat(),
                "MAX_SEARCHES": MAX_SEARCHES,
                "question": state["question"],
                "bullets": bullets
        }).to_messages()
    convo = [*history, *seed]
    used = sum(1 for m in convo if isinstance(m, AIMessage) and m.tool_calls)

    model = (
        llm.bind_tools(TOOLS, parallel_tool_calls=False)
        if used < MAX_SEARCHES
        else llm
    )
    reply = model.invoke(convo)
    out: dict = {"research_messages": [*seed, reply]}

    if not getattr(reply, "tool_calls", None):
        out["notes"] = reply.content
    return out

def route_after_research(state: AgentState) -> Literal["tools", "writer"]:
    last = state["research_messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else "writer"

#Define synthesizer
def writer_node(state: AgentState) -> dict:
    notes = state.get("notes") or "(no research was performed)"
    formatted_prompt = WRITER_PROMPT.invoke({"notes": notes})
    reporter_response = llm.invoke(formatted_prompt)
    return {"answer": reporter_response.content}

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


def main() -> None :
    question = " ".join(sys.argv[1:]) or input("Question: ").strip()
    logger.info("Agent is searching for answers ...")
    


    #Debug
    graph = agent_graph()
    chunks = graph.stream(
            {"question": question},
            config={"recursion_limit": 25},
            stream_mode="updates",
        )
    for chunk in chunks :
        for node, update in chunk.items():
            if node == "planner":
                logger.info("Planning ...")
                if update["needs_research"]:
                    logger.info(f"Deep research mode activated : Sending plan to the agent: {update['sub_questions']}")
                else:
                    logger.info(f"No Deep research mode needed")
            elif node == "researcher":
                last = update["research_messages"][-1]
                for call in getattr(last, "tool_calls", []) or []:
                    logger.info(f"  [tool calling] {call['args']['query']}")
            elif node == "writer":
                logger.debug(update["answer"])
                final_answer = update["answer"][-1]["text"]
                logger.info(f"Final report:\n{final_answer}")
               
if __name__ == "__main__":
    main()