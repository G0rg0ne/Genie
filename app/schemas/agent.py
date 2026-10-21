from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class AgentState(BaseModel):

    question: str = Field(
        ...,
        description="The user's original question",
    )
    chat_history: Annotated[list[AnyMessage], add_messages] = Field(
        default_factory=list,
        description="Previous turns of the conversation (from LibreChat), excluding the current question",
    )
    standalone_question: str = Field(
        default="",
        description="Latest user message rewritten so it makes sense without the chat history",
    )
    action: Literal["plan", "respond"] = Field(
        default="plan",
        description=(
            "Orchestrator routing: 'plan' sends the rewritten question through "
            "planner/researcher; 'respond' skips research and goes straight to the writer"
        ),
    )
    sub_questions: list[str] = Field(
        default_factory=list,
        description="Question decomposed into smaller, independently answerable parts",
    )
    needs_research: bool = Field(
        default=False,
        description="Whether the planner decided external research is needed",
    )
    research_messages: Annotated[list[AnyMessage], add_messages] = Field(
        default_factory=list,
        description="Message history of the research sub-agent (tool calls + results)",
    )
    notes: str = Field(
        default="",
        description="Condensed findings accumulated during research",
    )
    answer: str = Field(
        default="",
        description="Final answer returned to the user",
    )


class OrchestratorDecision(BaseModel):
    """Structured output from the orchestrator: rewrite + route."""

    standalone_question: str = Field(
        description=(
            "The latest user message rewritten as a self-contained question that "
            "resolves pronouns and references using the chat history. "
            "If the message is already standalone, copy it unchanged."
        ),
    )
    action: Literal["plan", "respond"] = Field(
        description=(
            "Use 'respond' when the request only refers to earlier turns "
            "(e.g. shorten, translate, or reformat the previous answer) and no "
            "new facts are needed. Use 'plan' for anything that may need research "
            "or a fresh answer."
        ),
    )


class Plan(BaseModel):
    """Structured output forces the planner to commit to a decision."""

    needs_research: bool = Field(
        description="True if answering requires current/external facts. "
        "False for timeless, definitional, or reasoning-only questions."
    )
    sub_questions: list[str] = Field(
        default_factory=list,
        description=(
            "The smallest sufficient set of 1-4 distinct, non-overlapping "
            "research questions. Use one for an atomic factual lookup. "
            "Empty if no research is needed."
        ),
    )
