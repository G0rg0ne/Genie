"""Langfuse client helpers for prompt loading and request tracing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from loguru import logger

from core.config import Settings

PROMPT_NAMES = (
    ("planner", "planner-prompt"),
    ("researcher", "researcher-prompt"),
    ("writer", "writer-synth-prompt"),
)


@dataclass(frozen=True)
class PromptBundle:
    """LangChain chat prompts loaded from Langfuse Prompt Management."""

    planner: ChatPromptTemplate
    researcher: ChatPromptTemplate
    writer: ChatPromptTemplate


class LangfusePromptError(RuntimeError):
    """Raised when a required Langfuse prompt cannot be loaded."""


def init_langfuse(settings: Settings) -> Langfuse:
    """Initialize the Langfuse SDK against the configured self-hosted instance."""
    logger.info(
        "Initializing Langfuse client base_url={}",
        settings.langfuse_base_url,
    )
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
    )


def _to_chat_prompt_template(name: str, langfuse_prompt: Any) -> ChatPromptTemplate:
    """Convert a Langfuse chat prompt into a linked LangChain ChatPromptTemplate."""
    prompt_type = getattr(langfuse_prompt, "type", None)
    if prompt_type is not None and prompt_type != "chat":
        raise LangfusePromptError(
            f"Prompt '{name}' must be type 'chat', got '{prompt_type}'"
        )

    try:
        messages = langfuse_prompt.get_langchain_prompt()
    except Exception as exc:  # noqa: BLE001 — surface clear startup errors
        raise LangfusePromptError(
            f"Failed to convert Langfuse prompt '{name}' to LangChain format: {exc}"
        ) from exc

    return ChatPromptTemplate(
        messages,
        metadata={"langfuse_prompt": langfuse_prompt},
    )


def load_chat_prompt(client: Langfuse, name: str) -> ChatPromptTemplate:
    """Fetch one chat prompt by name and convert it for LangChain use."""
    logger.info("Loading Langfuse chat prompt name={}", name)
    try:
        langfuse_prompt = client.get_prompt(name, type="chat")
    except Exception as exc:  # noqa: BLE001 — fail fast with prompt context
        raise LangfusePromptError(
            f"Failed to load Langfuse prompt '{name}': {exc}"
        ) from exc

    if getattr(langfuse_prompt, "is_fallback", False):
        raise LangfusePromptError(
            f"Langfuse returned a fallback for prompt '{name}'; "
            "create the production chat prompt before starting Genie"
        )

    return _to_chat_prompt_template(name, langfuse_prompt)


def load_prompts(client: Langfuse) -> PromptBundle:
    """Load the three Genie prompts required by the agent graph."""
    loaded: dict[str, ChatPromptTemplate] = {}
    for attr, name in PROMPT_NAMES:
        loaded[attr] = load_chat_prompt(client, name)
    logger.info("Loaded {} Langfuse prompts", len(loaded))
    return PromptBundle(**loaded)


def create_callback_handler() -> CallbackHandler:
    """Create a fresh LangChain callback handler for one HTTP request."""
    return CallbackHandler()


def build_trace_config(
    *,
    cid: str,
    model: str,
    stream: bool,
    user_id: str | None = None,
    session_id: str | None = None,
    run_name: str = "genie-chat-completion",
) -> dict[str, Any]:
    """Build a RunnableConfig that attaches Langfuse tracing to a graph/LLM call."""
    handler = create_callback_handler()
    metadata: dict[str, Any] = {
        "completion_id": cid,
        "requested_model": model,
        "stream": stream,
        "langfuse_tags": ["genie", "langgraph"],
    }
    if user_id:
        metadata["langfuse_user_id"] = user_id
    if session_id:
        metadata["langfuse_session_id"] = session_id

    return {
        "callbacks": [handler],
        "run_name": run_name,
        "metadata": metadata,
    }


def flush_langfuse(client: Langfuse | None = None) -> None:
    """Flush pending Langfuse events. Never raises into the request path."""
    try:
        target = client or Langfuse()
        target.flush()
    except Exception as exc:  # noqa: BLE001 — best-effort export
        logger.warning("Langfuse flush failed: {}", exc)
