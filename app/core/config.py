from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    accessible_models: list[str] = Field(default_factory=list)
    model_name: str = Field(..., description="LLM used by the Genie Agent")
    mcp_server_url: str

    langfuse_public_key: str = Field(..., description="Langfuse project public key")
    langfuse_secret_key: str = Field(..., description="Langfuse project secret key")
    langfuse_base_url: str = Field(
        ...,
        description="Self-hosted Langfuse API base URL",
    )
