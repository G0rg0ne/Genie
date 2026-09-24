# app/core/mcp_client.py
from contextlib import asynccontextmanager
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_URL = "http://mcp:8080/mcp"  # "mcp" = the Compose service name for Dockerfile-mcp

@asynccontextmanager
async def get_mcp_session():
    async with streamable_http_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session