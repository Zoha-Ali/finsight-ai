from fastapi import APIRouter, Depends, HTTPException, status

from ..agents.categorization_agent import categorize_transaction
from ..auth import get_current_user
from ..models import User
from ..schemas import CategorizeRequest, CategorizeResponse

router = APIRouter(prefix="/categorize", tags=["categorize"])


@router.post("", response_model=CategorizeResponse)
async def categorize(
    payload: CategorizeRequest,
    current_user: User = Depends(get_current_user),
) -> CategorizeResponse:
    try:
        result = await categorize_transaction(payload.transaction_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return CategorizeResponse(**result)
