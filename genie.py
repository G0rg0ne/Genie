from re import M
from utils.logging_config import setup_logging

setup_logging()
from loguru import logger
import os

from langsmith import Client
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState, START, END
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

load_dotenv()
MODEL_NAME = os.getenv("MODEL_NAME","gpt-4o-mini")

client = Client()

def llm_call(state: dict, prompt_name: str) -> dict:
    prompt = client.pull_prompt(prompt_name)
    question = state["messages"][-1].content
    templated = prompt.format_messages(question=question)
    response = ChatOpenAI(model=MODEL_NAME).invoke(
        [*templated, *state["messages"]]
    )
    return {"messages": [response]}

def plan_step(state: MessagesState) -> MessagesState:
    plan_agent = llm_call(state,"linear_planer")
    return plan_agent

def search_step(state: MessagesState) -> MessagesState:
    search_agent = llm_call(state,"researcher")
    return search_agent

def synth_step(state: MessagesState) -> MessagesState:
    synth_agent = llm_call(state,"synthesizer")
    return synth_agent

def agent_graph() -> StateGraph:
    graph = StateGraph(MessagesState)

    graph.add_node("plan_step", plan_step)
    graph.add_node("search_step", search_step)  
    graph.add_node("synth_step", synth_step)

    graph.add_edge(START, "plan_step")
    graph.add_edge("plan_step", "search_step")
    graph.add_edge("search_step", "synth_step")
    graph.add_edge("synth_step", END)

    return graph.compile()

graph = agent_graph()
# run the graph
response = graph.invoke({"messages": [HumanMessage(content="What is a transformer in machine learning?")]})
logger.info(f"Response: {response}")
