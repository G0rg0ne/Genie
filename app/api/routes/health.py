from fastapi import APIRouter
from schemas.health import HealthStatusResponse

router = APIRouter()

@router.get("/health",response_model=HealthStatusResponse)
async def get_stats():
    return {"status": "healthy"}
