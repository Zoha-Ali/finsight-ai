import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from ..agents.receipt_agent import process_receipt
from ..auth import get_current_user
from ..models import User
from ..schemas import ReceiptUploadResponse

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.post("/upload", response_model=ReceiptUploadResponse)
async def upload_receipt(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> ReceiptUploadResponse:
    contents = await file.read()
    image_base64 = base64.b64encode(contents).decode("ascii")

    try:
        result = await process_receipt(image_base64, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return ReceiptUploadResponse(
        filename=file.filename,
        type=result["type"],
        transactions_created=result["transactions_created"],
    )
