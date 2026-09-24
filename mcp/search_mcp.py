import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

from pydantic import BaseModel, Field

from mcp.client import Client
from mcp.server.mcpserver import MCPServer

# Create server
mcp = MCPServer("Deep search service")

class SearchData(BaseModel):
    """Structured search response"""
    links: str = Field(description="link")

@mcp.tool()
def get_link(topic: str) -> SearchData:
    """Get current weather for a city with full structured data"""
    response = SearchData(links="www.google.com")
    return response


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)