from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..models import User
from ..schemas import QARequest, QAResponse

router = APIRouter(prefix="/qa", tags=["qa"])


@router.post("", response_model=QAResponse)
async def ask_question(
    payload: QARequest,
    current_user: User = Depends(get_current_user),
) -> QAResponse:
    return QAResponse(
        question=payload.question,
        answer="This is a stub response — Q&A agent logic is not implemented yet.",
    )
