from re import M
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
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage
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
llm =  ChatOpenAI(model=MODEL_NAME)
client = Client()
PLANNER_PROMPT = client.pull_prompt("planner")
#RESEARCHER_PROMPT = client.pull_prompt(prompt_name)
#WRITER_PROMPT = client.pull_prompt(prompt_name)

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


def main() -> None :
    question = " ".join(sys.argv[1:]) or input("Question: ").strip()
    logger.info("Agent is searching for answers ...")
    debug_input = AgentState(question=question)
    
    debug_result = planner_node(debug_input)
    logger.info(debug_result)

    
if __name__ == "__main__":
    main()