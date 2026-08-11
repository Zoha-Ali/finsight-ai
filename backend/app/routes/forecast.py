from fastapi import APIRouter, Depends

from ..agents.forecasting_agent import generate_forecast
from ..auth import get_current_user
from ..models import User
from ..schemas import ForecastResponse

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("", response_model=ForecastResponse)
async def get_forecast(
    current_user: User = Depends(get_current_user),
) -> ForecastResponse:
    result = await generate_forecast(current_user.id)
    return ForecastResponse(**result)
