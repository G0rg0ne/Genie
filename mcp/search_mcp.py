import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

from firecrawl import Firecrawl
from pydantic import BaseModel, Field

from mcp.client import Client
from mcp.server.mcpserver import MCPServer
import os

firecrawl_key = os.environ["FC_KEY"]
# Create server
mcp = MCPServer("Deep search service")

class SearchData(BaseModel):
    """Structured search response"""
    content_md: str = Field(description="the content of the scraped website")

@mcp.tool()
def scrap_link(link: str) -> SearchData:
    """Get"""
    scrap_app = Firecrawl(api_key=firecrawl_key)
    result = scrap_app.scrape(link,formats=["markdown"])
    response = SearchData(content_md=result)
    return response

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)