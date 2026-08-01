import base64
import binascii
import json
import os
from datetime import date

import httpx
from dotenv import load_dotenv

from ..database import AsyncSessionLocal
from ..models import Transaction, TransactionSource
from .categorization_agent import categorize_transaction

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-sonnet-5"

EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured data from images of receipts and bank/credit "
    "card statements. Decide whether the image shows a single purchase "
    "receipt or a statement listing multiple transactions, then extract "
    "every transaction you can see.\n\n"
    "Respond with ONLY a single raw JSON object - no markdown code fences, "
    "no commentary - matching exactly this schema:\n"
    '{"type": "receipt" | "statement", "transactions": '
    '[{"merchant": string, "amount": number, "date": "YYYY-MM-DD"}]}\n\n'
    'For a single receipt, "transactions" has exactly one item. For a '
    "statement, include one item per line-item transaction. If a date "
    "isn't fully legible, make your best guess from context rather than "
    "omitting the transaction."
)


def _detect_media_type(raw_bytes: bytes) -> str:
    """Sniff an image's media type from its magic number.

    Anthropic's vision API rejects a mismatch between declared media_type
    and the image's actual encoding, so a fixed default (e.g. always
    "image/jpeg") breaks for any other format - this has to be detected.
    """
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _split_data_uri(image_base64: str) -> tuple[str, str]:
    """Accept either a raw base64 string or a data:<media_type>;base64,<data>
    URI, and return (media_type, data). When no explicit media_type is
    available, it's sniffed from the decoded image bytes' magic number.
    """
    if image_base64.startswith("data:"):
        header, _, data = image_base64.partition(",")
        media_type = header[len("data:"):].split(";")[0]
        if media_type:
            return media_type, data
    else:
        data = image_base64

    try:
        raw_bytes = base64.b64decode(data[:64])
    except (ValueError, binascii.Error):
        raw_bytes = b""
    return _detect_media_type(raw_bytes), data


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text[:-3]
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _parse_date(value) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return date.today()


async def _call_model(messages: list[dict]) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 2048,
                "system": EXTRACTION_SYSTEM_PROMPT,
                "messages": messages,
            },
        )
        response.raise_for_status()
        data = response.json()

    return "".join(block["text"] for block in data["content"] if block.get("type") == "text").strip()


async def _extract(media_type: str, data: str) -> dict:
    """Run the vision extraction call, retrying once if the model's
    response isn't valid JSON.
    """
    messages: list[dict] = [
        {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                {"type": "text", "text": "Extract the transaction data from this image as instructed."},
            ],
        }
    ]

    last_error: Exception | None = None
    for _ in range(2):
        raw_text = await _call_model(messages)
        try:
            return json.loads(_strip_code_fence(raw_text))
        except json.JSONDecodeError as exc:
            last_error = exc
            messages.append({"role": "assistant", "content": raw_text})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"That was not valid JSON and failed to parse ({exc}). "
                        "Respond again with ONLY the raw JSON object, no "
                        "markdown, no commentary."
                    ),
                }
            )

    raise ValueError(f"Model did not return valid JSON after a retry: {last_error}")


async def process_receipt(image_base64: str, owner_id: int) -> dict:
    """Extract transactions from a receipt/statement image and record them.

    Uses claude-sonnet-5's vision input to classify the image as a single
    receipt or a multi-line statement and extract each transaction (merchant,
    amount, date) as strict JSON. Each extracted transaction is inserted
    directly (source="receipt") - bypassing the MCP record_transaction tool,
    since that tool hardcodes source="manual" and today's date, neither of
    which fit receipt-extracted data - then run through
    categorize_transaction for categorization and anomaly detection.
    """
    media_type, data = _split_data_uri(image_base64)
    extracted = await _extract(media_type, data)

    raw_transactions = extracted.get("transactions") or []
    if not raw_transactions:
        raise ValueError("No transactions could be extracted from the image")

    doc_type = extracted.get("type")
    if doc_type not in ("receipt", "statement"):
        doc_type = "statement" if len(raw_transactions) > 1 else "receipt"

    created_ids = []
    async with AsyncSessionLocal() as session:
        for item in raw_transactions:
            try:
                merchant = str(item["merchant"])
                amount = float(item["amount"])
            except (KeyError, TypeError, ValueError):
                continue

            transaction = Transaction(
                owner_id=owner_id,
                merchant=merchant,
                amount=amount,
                date=_parse_date(item.get("date")),
                source=TransactionSource.receipt,
            )
            session.add(transaction)
            await session.flush()
            created_ids.append(transaction.id)

        await session.commit()

    if not created_ids:
        raise ValueError("Extracted transactions were all missing a merchant or amount")

    transactions_created = [await categorize_transaction(tx_id, owner_id) for tx_id in created_ids]

    return {"type": doc_type, "transactions_created": transactions_created}
