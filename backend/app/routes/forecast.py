from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..models import User
from ..schemas import ForecastPoint, ForecastResponse

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("", response_model=ForecastResponse)
async def get_forecast(
    current_user: User = Depends(get_current_user),
) -> ForecastResponse:
    return ForecastResponse(
        owner_id=current_user.id,
        forecast=[
            ForecastPoint(month="2026-08", predicted_spend=0.0),
        ],
    )
