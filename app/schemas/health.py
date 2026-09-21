from pydantic import BaseModel, Field

class HealthStatusResponse(BaseModel):
    status : str = Field(..., description="Service response")