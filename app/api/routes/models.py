from fastapi import APIRouter
from core.config import Settings
from schemas.models import ModelsReponse


router = APIRouter()
settings = Settings()

@router.get("/models",response_model=ModelsReponse)
async def get_models():
    return {"accessible_models":settings.accessible_models}
