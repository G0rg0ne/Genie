from typing import Annotated
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

class Plan(BaseModel):
    """Structured output forces the planner to commit to a decision."""
 
    needs_research: bool = Field(
        description="True if answering requires current/external facts. "
        "False for timeless, definitional, or reasoning-only questions."
    )
    sub_questions: list[str] = Field(
        default_factory=list,
        description="2-4 specific, independently searchable sub-questions. "
        "Empty if no research is needed.",
    )