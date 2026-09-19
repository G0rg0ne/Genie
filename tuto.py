from utils.logging_config import setup_logging

setup_logging()
from loguru import logger
import os
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState, START, END
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

load_dotenv()
MODEL_NAME = os.getenv("MODEL_NAME","gpt-4o-mini")

def llm_call(state: MessagesState) -> MessagesState:
    llm = ChatOpenAI(model=MODEL_NAME)
    logger.info(f"Using: {MODEL_NAME} model for LLM call")
    response = llm.invoke(state["messages"])
    return MessagesState(messages=response.content)

def agent_graph() -> StateGraph:
    graph = StateGraph(MessagesState)
    # add nodes to the graph
    graph.add_node("llm_call", llm_call)

    # add edges to the graph
    graph.add_edge(START, "llm_call")
    graph.add_edge("llm_call", END)

    # return the graph
    logger.info("Agent graph created")
    return graph.compile()

# create the graph
graph = agent_graph()

# run the graph
response = graph.invoke({"messages": [HumanMessage(content="Hello, how are you?")]})
logger.info(f"Response: {response}")
