import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from ..agents.receipt_agent import process_receipt
from ..auth import get_current_user
from ..models import User
from ..schemas import ReceiptUploadResponse

router = APIRouter(prefix="/receipts", tags=["receipts"])

ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
}


@router.post("/upload", response_model=ReceiptUploadResponse)
async def upload_receipt(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> ReceiptUploadResponse:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {file.content_type}. Upload an image (PNG/JPEG/GIF/WEBP) or a PDF.",
        )

    contents = await file.read()
    file_base64 = base64.b64encode(contents).decode("ascii")

    try:
        result = await process_receipt(file_base64, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    if result["type"] == "not_a_receipt":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This doesn't look like a receipt or statement - no transactions were saved.",
        )

    return ReceiptUploadResponse(
        filename=file.filename,
        type=result["type"],
        transactions_created=result["transactions_created"],
        extraction_model=result["extraction_model"],
        skipped=result["skipped"],
        summary=result["summary"],
    )
