from fastapi import APIRouter, Depends, File, UploadFile

from ..auth import get_current_user
from ..models import User
from ..schemas import ReceiptUploadResponse

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.post("/upload", response_model=ReceiptUploadResponse)
async def upload_receipt(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> ReceiptUploadResponse:
    return ReceiptUploadResponse(
        filename=file.filename,
        status="received",
        transaction=None,
    )
