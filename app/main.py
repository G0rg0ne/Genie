from contextlib import asynccontextmanager

from fastapi import FastAPI
from utils.logger import setup_logging
from api.routes import health, models, completions
from agents.genie_graph import build_agent_graph

setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.graph = await build_agent_graph()
    yield
    # optional: close mcp_client connections here on shutdown if the adapter exposes a close/aclose

app = FastAPI(lifespan=lifespan)

app.include_router(health.router)
app.include_router(models.router)
app.include_router(completions.router)