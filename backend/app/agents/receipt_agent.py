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
from .tracing import save_trace

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-sonnet-5"

# Empirically determined, not a guess: with max_tokens=8192 below, a
# synthetic 100-transaction statement extracted cleanly (9512-character
# response, valid JSON) while a 130-transaction one truncated mid-JSON
# around item 80-84 (varies run to run with how verbosely the model
# happens to format its output, so the boundary isn't a precise fixed
# number). 75 leaves a healthy margin below the confirmed-good 100 while
# comfortably covering realistic single-statement uploads.
MAX_TRANSACTIONS_PER_UPLOAD = 75

EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured data from receipt and bank/credit card "
    "statement files - either images or PDFs, including multi-page PDF "
    "statements. Decide whether the file shows a single purchase receipt "
    "or a statement listing multiple transactions, then extract every "
    "transaction you can see across the entire file, including every page "
    "of a multi-page PDF.\n\n"
    "If the file is NOT actually a receipt or bank/credit statement - an "
    "irrelevant image, placeholder or lorem ipsum text, a blank page, or "
    "anything else with no real transaction data on it - do not force "
    "values into the schema below and do not invent a plausible-looking "
    "transaction. Instead respond with exactly "
    '{"type": "not_a_receipt", "transactions": []}.\n\n'
    "This also applies to receipt TEMPLATES or MOCKUPS: judge the merchant "
    "name and the item/line-item descriptions on whether, taken as a "
    "whole, they read as real content a real business or customer would "
    "actually produce. Lorem ipsum / Latin filler text is one example, "
    "but the same applies to any other placeholder, test, or nonsensical "
    "text - random or repeated words, \"test test test\"-style filler "
    "repeated across multiple fields, keyboard mashing, generic "
    "placeholder labels (\"Item 1\", \"Product A\", \"Sample text\"), or "
    "item names that are obviously made up and don't correspond to any "
    "real product or service.\n\n"
    "Base this on the overall pattern, not a single word in isolation: "
    "an otherwise ordinary business or item name is NOT disqualifying "
    "just because it happens to contain a common word (even a word like "
    "\"test\" or \"sample\" used naturally as part of a normal-sounding "
    "name). What matters is whether the merchant name and item "
    "descriptions, taken together, are specific and genuine versus "
    "generic, repeated, or fabricated-sounding - concrete, specific item "
    "descriptions naming real products or services are strong evidence "
    "the receipt is real, even if some other detail seems unusual. Only "
    "treat the file as not_a_receipt if the content as a whole - not one "
    "isolated word - reads as placeholder or fabricated text. Placeholder "
    "or nonsensical text that pervades the merchant or item names is "
    "disqualifying regardless of how convincing the rest of the layout "
    "looks.\n\n"
    "Respond with ONLY a single raw JSON object - no markdown code fences, "
    "no commentary - matching exactly this schema:\n"
    '{"type": "receipt" | "statement" | "not_a_receipt", "transactions": '
    '[{"merchant": string, "amount": number, "date": "YYYY-MM-DD" | null, '
    '"type": "debit" | "credit"}]}\n\n'
    'For a single receipt, "transactions" has exactly one item. For a '
    "statement, include one item per line-item transaction across all "
    "pages - don't omit a transaction just because one field is hard to "
    "read.\n\n"
    'Every transaction also needs a per-item "type" (separate from the '
    'top-level "type" above): "debit" if money left the account (a '
    "purchase, bill payment, withdrawal, or outgoing/sent transfer), or "
    '"credit" if money entered the account (a deposit, incoming '
    "transfer, refund, interest, or profit-share payment). Get this "
    "right even when other fields are uncertain - when a statement has "
    "separate Debit/Withdrawal and Credit/Deposit columns, use whichever "
    "column the row's amount actually appears in; when it's a single "
    "signed amount column, a negative value is normally a debit and a "
    "positive value a credit, but also read the row's own label or "
    "description rather than relying on the sign alone. Regardless of "
    'debit or credit, "amount" itself must always be the positive '
    "magnitude of the transaction - never a negative number. Direction "
    'is expressed only through the "type" field.\n\n'
    'For the "merchant" field specifically: extract only the clean '
    "business/payee name, not the full raw line text. Bank and card "
    "statements often bundle reference numbers, consumer/account IDs, "
    "STAN (System Trace Audit Number) codes, trip/order/transaction IDs, "
    "or phone numbers into the same line as the merchant name - strip "
    "all of that out and keep only the actual business or payee name "
    '(e.g. "Zong0001 Consumer No 03120408494" -> "Zong", "K-Electric '
    'STAN No.493841 BPS" -> "K-Electric", "Careem Trip ID CRM-4471829" '
    '-> "Careem"). This matters most for consistency: when the SAME '
    "merchant appears on multiple rows with reference numbers attached "
    "to some rows but not others, extract the same clean name every "
    "time rather than including the reference info on some rows and "
    "not others - a human reading the statement would recognize these "
    "as the same business, and the extracted merchant name should "
    "reflect that. Do not fabricate or guess a business name that "
    "isn't actually present in the text; only remove clearly incidental "
    'reference/tracking numbers, not genuine parts of the business '
    'name itself (e.g. "7-Eleven" or "K-Electric" are real names, not '
    "reference numbers, and must stay intact).\n\n"
    'For the "date" field specifically: only return a date you can '
    "actually read in the file. If no date is visible, or it's too "
    "blurry, cut off, or ambiguous to read with confidence, return null. "
    "Do NOT infer, estimate, or guess a plausible-sounding date from "
    "context - never assume it's today's date, and never guess a year. "
    "A null date is far better than a fabricated one."
)


def _detect_media_type(raw_bytes: bytes) -> str:
    """Sniff a file's media type from its magic number.

    Anthropic's API rejects a mismatch between declared media_type and
    the file's actual encoding, so a fixed default (e.g. always
    "image/jpeg") breaks for any other format - this has to be detected.
    """
    if raw_bytes.startswith(b"%PDF-"):
        return "application/pdf"
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _split_data_uri(file_base64: str) -> tuple[str, str]:
    """Accept either a raw base64 string or a data:<media_type>;base64,<data>
    URI, and return (media_type, data). When no explicit media_type is
    available, it's sniffed from the decoded file bytes' magic number.
    """
    if file_base64.startswith("data:"):
        header, _, data = file_base64.partition(",")
        media_type = header[len("data:"):].split(";")[0]
        if media_type:
            return media_type, data
    else:
        data = file_base64

    try:
        raw_bytes = base64.b64decode(data[:64])
    except (ValueError, binascii.Error):
        raw_bytes = b""
    return _detect_media_type(raw_bytes), data


def _content_block(media_type: str, data: str) -> dict:
    """Build the right Messages API content block for this file type.

    Claude accepts PDFs natively as "document" blocks (Anthropic's API
    rasterizes and reads every page server-side - including multi-page
    statements - in a single call, so no local PDF-to-image conversion
    library is needed). Anything else goes through as an "image" block,
    same as before.
    """
    block_type = "document" if media_type == "application/pdf" else "image"
    return {"type": block_type, "source": {"type": "base64", "media_type": media_type, "data": data}}


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text[:-3]
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _clean_merchant(value) -> str | None:
    """Return a usable merchant name, or None if it's missing/blank.

    str(None) silently produces the text "None" and str("") produces "",
    neither of which raises - so this has to check explicitly rather than
    rely on a type-coercion try/except to catch a missing merchant.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _is_valid_amount(value) -> bool:
    """True only for a real, positive number - not None, not a bool
    (isinstance(True, int) is True in Python), not zero or negative.
    """
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return value > 0


def _parse_date(value) -> tuple[date, bool]:
    """Parse a receipt-extracted date, falling back to today if it's
    missing or unparseable.

    Returns (date, date_estimated). The model is instructed to return
    null rather than guess a date it can't actually read, but Transaction
    still needs a concrete date - date_estimated flags when today's date
    was substituted rather than actually read off the receipt.
    """
    if value is None:
        return date.today(), True
    try:
        return date.fromisoformat(str(value)), False
    except (TypeError, ValueError):
        return date.today(), True


async def _call_model(messages: list[dict]) -> dict:
    """Returns the raw Messages API response dict, not just the text -
    callers need stop_reason to tell a response that was cut off by the
    token limit (retrying the identical request just truncates again in
    the same place - not recoverable the way a malformed-but-complete
    response is) apart from one that's merely malformed but complete
    (worth the existing reformat-and-retry).
    """
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
                "max_tokens": 8192,
                "system": EXTRACTION_SYSTEM_PROMPT,
                "messages": messages,
            },
        )
        response.raise_for_status()
        return response.json()


def _extract_text(response: dict) -> str:
    return "".join(block["text"] for block in response["content"] if block.get("type") == "text").strip()


async def _extract(media_type: str, data: str) -> dict:
    """Run the extraction call, retrying once if the model's response
    isn't valid JSON - unless the response was cut off by hitting
    max_tokens, in which case it raises immediately instead: a statement
    with too many transactions to fit in the response budget will
    truncate at the same point again on a same-input retry, so retrying
    only wastes an API call and delays telling the user what's actually
    wrong.
    """
    messages: list[dict] = [
        {
            "role": "user",
            "content": [
                _content_block(media_type, data),
                {"type": "text", "text": "Extract the transaction data from this file as instructed."},
            ],
        }
    ]

    last_error: Exception | None = None
    for _ in range(2):
        response = await _call_model(messages)

        if response.get("stop_reason") == "max_tokens":
            raise ValueError(
                "This file has too many transactions to process in one upload. "
                "Please split it into smaller date ranges and upload each part separately."
            )

        raw_text = _extract_text(response)
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


async def process_receipt(file_base64: str, owner_id: int) -> dict:
    """Extract transactions from a receipt/statement file and record them.

    Accepts either an image or a PDF (bank/credit card statements are
    often PDFs) - the file type is sniffed from its magic bytes, same
    pattern as the image media_type detection. PDFs, including
    multi-page statements, go through Claude's native "document" content
    block in a single API call (Anthropic's API reads every page
    server-side), so all pages are extracted and combined into one result
    without any local PDF-to-image conversion step.

    Uses claude-sonnet-5 to classify the file as a single receipt or a
    multi-line statement and extract each transaction (merchant, amount,
    date, debit/credit direction) as strict JSON. Only debit (expense)
    transactions are recorded - this app tracks spending, not income, so
    credit/deposit transactions are deliberately skipped rather than
    inserted. Every skip (a deposit, a missing merchant, an unusable
    amount, or an unrecognized type) is recorded with its reason, and the
    complete unfiltered extraction output is saved to the Trace row
    alongside it - so a bug in this filtering (or in the model's
    extraction itself) is debuggable straight from the Trace table,
    without needing the original file re-uploaded. Each recorded
    transaction is inserted directly (source="receipt") - bypassing the
    MCP record_transaction tool, since that tool hardcodes source="manual"
    and today's date, neither of which fit receipt-extracted data - then
    run through categorize_transaction for categorization and anomaly
    detection.
    """
    media_type, data = _split_data_uri(file_base64)
    extracted = await _extract(media_type, data)

    doc_type = extracted.get("type")

    if doc_type == "not_a_receipt":
        result = {
            "type": "not_a_receipt",
            "transactions_created": [],
            "extraction_model": MODEL,
            "skipped": [],
            "summary": "",
        }
        await save_trace(
            owner_id,
            "Process receipt upload",
            "receipt",
            [
                {
                    "agent": "receipt_agent",
                    "action": "process_receipt",
                    "raw_extraction": extracted,
                    "result": result,
                }
            ],
        )
        return result

    raw_transactions = extracted.get("transactions") or []
    if not raw_transactions:
        raise ValueError("No transactions could be extracted from the file")

    if len(raw_transactions) > MAX_TRANSACTIONS_PER_UPLOAD:
        # Past this point the extraction call itself starts silently
        # truncating mid-JSON (see MAX_TRANSACTIONS_PER_UPLOAD's comment) -
        # reject explicitly here, before touching the DB, rather than
        # letting a huge statement risk a garbled partial result.
        raise ValueError(
            f"This statement has {len(raw_transactions)} transactions, which is too "
            f"many to process in one upload (limit: {MAX_TRANSACTIONS_PER_UPLOAD}). "
            "Please split it into smaller date ranges and upload each part separately."
        )

    if doc_type not in ("receipt", "statement"):
        doc_type = "statement" if len(raw_transactions) > 1 else "receipt"

    created_ids = []
    date_estimated_by_id: dict[int, bool] = {}
    skipped: list[dict] = []

    async with AsyncSessionLocal() as session:
        for item in raw_transactions:
            merchant = _clean_merchant(item.get("merchant"))
            amount = item.get("amount")
            raw_type = item.get("type")
            tx_type = raw_type.strip().lower() if isinstance(raw_type, str) else None

            # Direction is checked first and independently of data quality -
            # a deposit is out of scope regardless of whether its merchant
            # or amount also happen to be usable, and this is the reason
            # the user actually cares about (why wasn't this tracked?),
            # not an extraction-quality detail.
            if tx_type == "credit":
                skipped.append({"merchant": merchant, "amount": amount, "reason": "deposit, out of scope"})
                continue
            if tx_type != "debit":
                # Missing/unrecognized type - deliberately NOT defaulted to
                # debit. Silently assuming a direction we don't actually
                # know is exactly the kind of accidental inclusion this
                # fix exists to prevent; skip and surface it instead.
                skipped.append({"merchant": merchant, "amount": amount, "reason": "unrecognized transaction type"})
                continue
            if merchant is None:
                skipped.append({"merchant": merchant, "amount": amount, "reason": "missing merchant"})
                continue
            if not _is_valid_amount(amount):
                skipped.append({"merchant": merchant, "amount": amount, "reason": "invalid amount"})
                continue

            tx_date, date_estimated = _parse_date(item.get("date"))

            transaction = Transaction(
                owner_id=owner_id,
                merchant=merchant,
                amount=float(amount),
                date=tx_date,
                date_estimated=date_estimated,
                source=TransactionSource.receipt,
            )
            session.add(transaction)
            await session.flush()
            created_ids.append(transaction.id)
            date_estimated_by_id[transaction.id] = date_estimated

        await session.commit()

    deposit_skips = [s for s in skipped if s["reason"] == "deposit, out of scope"]
    other_skips = [s for s in skipped if s["reason"] != "deposit, out of scope"]

    if not created_ids and not deposit_skips:
        # Every extracted item failed for a data-quality reason (not a
        # legitimate, intentional deposit-skip) - nothing usable came out
        # of this file at all.
        raise ValueError("Extracted transactions were all missing a merchant or amount")

    transactions_created = [await categorize_transaction(tx_id, owner_id) for tx_id in created_ids]
    for entry in transactions_created:
        entry["date_estimated"] = date_estimated_by_id.get(entry["transaction_id"], False)

    total_found = len(raw_transactions)
    summary = (
        f"{total_found} transaction{'' if total_found == 1 else 's'} found, "
        f"{len(created_ids)} expense{'' if len(created_ids) == 1 else 's'} added"
    )
    if deposit_skips:
        summary += f", {len(deposit_skips)} deposit{'' if len(deposit_skips) == 1 else 's'} skipped (not tracked)"
    if other_skips:
        summary += f", {len(other_skips)} item{'' if len(other_skips) == 1 else 's'} skipped (unreadable data)"
    summary += "."

    result = {
        "type": doc_type,
        "transactions_created": transactions_created,
        "extraction_model": MODEL,
        "skipped": skipped,
        "summary": summary,
    }

    await save_trace(
        owner_id,
        "Process receipt upload",
        "receipt",
        [
            {
                "agent": "receipt_agent",
                "action": "process_receipt",
                "raw_extraction": extracted,
                "result": result,
            }
        ],
    )

    return result
