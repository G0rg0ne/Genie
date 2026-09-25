from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    accessible_models: list[str] = Field(default_factory=list)
    model_name: str = Field(..., description="LLM used by the Genie Agent")
    mcp_server_url: str
    