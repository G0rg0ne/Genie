from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from agents.genie_graph import build_agent_graph
from api.routes import completions, health, models
from core.config import Settings
from core.langfuse_client import flush_langfuse, init_langfuse, load_prompts
from utils.logger import setup_logging

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    langfuse = init_langfuse(settings)
    prompts = load_prompts(langfuse)
    app.state.langfuse = langfuse
    app.state.prompts = prompts
    app.state.graph = await build_agent_graph(prompts)
    logger.info("Genie graph ready")
    try:
        yield
    finally:
        flush_langfuse(langfuse)


app = FastAPI(lifespan=lifespan)

app.include_router(health.router)
app.include_router(models.router)
app.include_router(completions.router)
