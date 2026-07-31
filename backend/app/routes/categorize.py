from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..models import User
from ..schemas import CategorizeRequest, CategorizeResponse

router = APIRouter(prefix="/categorize", tags=["categorize"])


@router.post("", response_model=CategorizeResponse)
async def categorize_transaction(
    payload: CategorizeRequest,
    current_user: User = Depends(get_current_user),
) -> CategorizeResponse:
    return CategorizeResponse(
        transaction_id=payload.transaction_id,
        predicted_category="uncategorized",
        confidence=0.0,
    )
