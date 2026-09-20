from pydantic import BaseModel, Field
from typing import List, Optional

class ModelsReponse(BaseModel):
    accessible_models: List[str]