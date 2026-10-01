from pydantic import Field, field_validator
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
    langfuse_tracing_environment: str = Field(
        "default",
        max_length=40,
        pattern=r"^[a-z0-9_-]+$",
        description="Langfuse environment attached to every trace (e.g. live-prod)",
    )

    @field_validator("langfuse_tracing_environment")
    @classmethod
    def _reject_reserved_environment(cls, value: str) -> str:
        """Langfuse reserves environment names starting with 'langfuse'."""
        if value.startswith("langfuse"):
            raise ValueError("Langfuse environment must not start with 'langfuse'")
        return value
