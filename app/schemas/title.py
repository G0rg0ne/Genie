from pydantic import BaseModel, Field

class TitleOutput(BaseModel):
    title: str = Field(
        default="Genie Conversation",
        description="A short, 3-6 word title summarizing the user's question",
    )