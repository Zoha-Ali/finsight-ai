from fastapi import APIRouter, Depends, HTTPException, status

from ..agents.supervisor_agent import route_request
from ..auth import get_current_user
from ..models import User
from ..schemas import QARequest, QAResponse

router = APIRouter(prefix="/qa", tags=["qa"])


@router.post("", response_model=QAResponse)
async def ask_question(
    payload: QARequest,
    current_user: User = Depends(get_current_user),
) -> QAResponse:
    try:
        result = await route_request(payload.question, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return QAResponse(
        question=payload.question,
        agent_used=result["agent_used"],
        result=result["result"],
        trace=result["trace"],
    )
