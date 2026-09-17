from utils.logging_config import setup_logging

setup_logging()

import langchain
import langgraph
from loguru import logger

logger.info("Everything is ready!")
logger.debug("LangChain and LangGraph are loaded")
