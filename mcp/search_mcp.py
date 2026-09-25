import os
from functools import lru_cache
from firecrawl import Firecrawl
from mcp.server.mcpserver import MCPServer, Context
from utils.logger import setup_logging
from pydantic import BaseModel, Field
from loguru import logger
from typing import Annotated
from pydantic import BaseModel, Field

setup_logging()

FC_KEY = os.environ.get("FC_KEY")
if not FC_KEY:
    raise RuntimeError("Missing required environment variable: FC_KEY")
HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8080"))

mcp = MCPServer("Deep search service", version=os.environ.get("SERVICE_VERSION", "0.1.0"))


class SearchData(BaseModel):
    """Structured search response."""

    content_md: str = Field(description="The full page content, converted to markdown.")
    url: str = Field(description="The URL that was scraped, echoed back for reference.")

@lru_cache(maxsize=1)
def get_firecrawl_client() -> Firecrawl:
    """Reuse a single Firecrawl client instead of creating one per call."""
    return Firecrawl(api_key=FC_KEY)


@mcp.tool()
def scrape_link(
    link: Annotated[
        str,
        Field(
            description=(
                "A single, fully-qualified URL to scrape (must include the scheme, "
                "e.g. 'https://example.com/article'). The page is fetched and its "
                "rendered content — including JavaScript-loaded content — is "
                "converted to markdown."
            )
        ),
    ],
) -> SearchData:
    """Fetch a web page by URL and return its content as clean markdown.

    Use this when you already have a specific URL (e.g. from a search result
    or a link the user provided) and need its actual page content — not for
    discovering URLs, which requires a separate search tool.

    Args:
        link: The URL to scrape.

    Returns:
        SearchData containing the page content as markdown and the source URL.

    Raises:
        ValueError: If the page returns no content (e.g. blocked, empty, or
            a non-HTML resource such as a raw binary file).

    Example:
        scrape_link(link="https://example.com/blog/post-1")
        -> SearchData(content_md="# Post Title\\n\\nBody text...", url="https://example.com/blog/post-1")
    """
    client = get_firecrawl_client()

    try:
        result = client.scrape(link, formats=["markdown"])
    except Exception:
        logger.exception("Failed to scrape %s", link)
        raise

    content = getattr(result, "markdown", None)
    if not content:
        raise ValueError(f"No markdown content returned for {link}")

    return SearchData(content_md=content, url=link)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=HOST, port=PORT)