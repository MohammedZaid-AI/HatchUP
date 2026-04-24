from functools import lru_cache

from fastapi import APIRouter, HTTPException

from src.talent_scout_models import TalentScoutRequest
from src.services.talent_scout_service import TalentScoutService

router = APIRouter()


@lru_cache(maxsize=1)
def get_talent_scout_service() -> TalentScoutService:
    return TalentScoutService()


@router.post("/talent-scout")
@router.post("/api/talent-scout")
async def run_talent_scout(payload: TalentScoutRequest):
    try:
        service = get_talent_scout_service()
        return service.discover(payload.role).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Talent scout failed: {exc}") from exc
