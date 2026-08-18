import base64
import io
from unittest.mock import AsyncMock

from pypdf import PdfWriter
from sqlalchemy import select

from app.agents import receipt_agent
from app.models import Trace, Transaction


def _make_pdf_bytes(*, encrypted: bool) -> bytes:
    """A minimal real PDF, self-contained rather than depending on an
    external fixture file - optionally locked with a real user/open
    password (requires a password just to open, not just permission
    restrictions), matching what a locked bank statement looks like.
    """
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if encrypted:
        writer.encrypt(user_password="1234", owner_password="1234")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _fake_categorize_transaction():
    """Matches categorize_transaction's real return shape closely enough
    for process_receipt's entry["date_estimated"] = ... assignment and the
    response schema to work - the real categorization call is mocked out
    here since it makes a real LLM call, same pattern used for
    categorize_transaction mocks in test_transactions_route.py.
    """

    async def fake(transaction_id, owner_id, model=None):
        return {
            "transaction_id": transaction_id,
            "category": "other",
            "category_id": 1,
            "is_anomaly": False,
            "reason": None,
            "model_used": "claude-haiku-4-5",
        }

    return fake


async def test_debit_transactions_are_recorded_and_credit_transactions_are_skipped(
    monkeypatch, db_session, test_user
):
    monkeypatch.setattr(
        receipt_agent,
        "_extract",
        AsyncMock(
            return_value={
                "type": "statement",
                "transactions": [
                    {"merchant": "Raast PTP Transfer", "amount": 50000.0, "date": "2026-07-10", "type": "debit"},
                    {"merchant": "Zong Bill Payment", "amount": 500.0, "date": "2026-07-11", "type": "debit"},
                    {"merchant": "IBFT FROM Someone", "amount": 253594.0, "date": "2026-07-22", "type": "credit"},
                    {"merchant": "BU- Stan No.493841 BPS", "amount": 60.0, "date": "2026-07-07", "type": "credit"},
                ],
            }
        ),
    )
    monkeypatch.setattr(receipt_agent, "categorize_transaction", _fake_categorize_transaction())

    result = await receipt_agent.process_receipt("data:image/png;base64,AAAA", test_user.id)

    assert len(result["transactions_created"]) == 2
    created_merchants = {c["category"] for c in result["transactions_created"]}  # sanity: both categorized
    assert created_merchants == {"other"}

    skip_reasons = {(s["merchant"], s["reason"]) for s in result["skipped"]}
    assert ("IBFT FROM Someone", "deposit, out of scope") in skip_reasons
    assert ("BU- Stan No.493841 BPS", "deposit, out of scope") in skip_reasons

    assert result["summary"] == "4 transactions found, 2 expenses added, 2 deposits skipped (not tracked)."

    # the two debits actually landed in the DB; the two credits did not
    db_transactions = (
        await db_session.execute(select(Transaction).where(Transaction.owner_id == test_user.id))
    ).scalars().all()
    assert {t.merchant for t in db_transactions} == {"Raast PTP Transfer", "Zong Bill Payment"}


async def test_missing_merchant_and_invalid_amount_are_skipped_with_specific_reasons(
    monkeypatch, db_session, test_user
):
    monkeypatch.setattr(
        receipt_agent,
        "_extract",
        AsyncMock(
            return_value={
                "type": "statement",
                "transactions": [
                    {"merchant": "Real Purchase", "amount": 10.0, "date": "2026-07-10", "type": "debit"},
                    {"merchant": None, "amount": 20.0, "date": "2026-07-10", "type": "debit"},
                    {"merchant": "Zero Amount Row", "amount": 0, "date": "2026-07-10", "type": "debit"},
                    {"merchant": "Negative Row", "amount": -5.0, "date": "2026-07-10", "type": "debit"},
                ],
            }
        ),
    )
    monkeypatch.setattr(receipt_agent, "categorize_transaction", _fake_categorize_transaction())

    result = await receipt_agent.process_receipt("data:image/png;base64,AAAA", test_user.id)

    assert len(result["transactions_created"]) == 1
    reasons_by_merchant = {(s["merchant"], s["reason"]) for s in result["skipped"]}
    assert (None, "missing merchant") in reasons_by_merchant
    assert ("Zero Amount Row", "invalid amount") in reasons_by_merchant
    assert ("Negative Row", "invalid amount") in reasons_by_merchant
    assert "3 items skipped (unreadable data)" in result["summary"]


async def test_missing_or_unrecognized_type_is_skipped_not_defaulted_to_debit(
    monkeypatch, db_session, test_user
):
    # Mixed in with one genuinely valid debit so this test isolates the
    # "unrecognized type -> skipped, not silently treated as an expense"
    # behavior from the separate "everything failed -> raise ValueError"
    # case (covered by test_all_data_quality_failures_still_raises_value_error).
    monkeypatch.setattr(
        receipt_agent,
        "_extract",
        AsyncMock(
            return_value={
                "type": "statement",
                "transactions": [
                    {"merchant": "Valid Expense", "amount": 5.0, "date": "2026-07-10", "type": "debit"},
                    {"merchant": "No Type Field", "amount": 10.0, "date": "2026-07-10"},
                    {"merchant": "Weird Type", "amount": 10.0, "date": "2026-07-10", "type": "withdrawal"},
                ],
            }
        ),
    )
    monkeypatch.setattr(receipt_agent, "categorize_transaction", _fake_categorize_transaction())

    result = await receipt_agent.process_receipt("data:image/png;base64,AAAA", test_user.id)

    assert len(result["transactions_created"]) == 1
    skip_reasons = {s["reason"] for s in result["skipped"] if s["merchant"] != "Valid Expense"}
    assert skip_reasons == {"unrecognized transaction type"}
    assert len(result["skipped"]) == 2


async def test_all_deposits_does_not_raise_and_reports_zero_expenses(monkeypatch, db_session, test_user):
    monkeypatch.setattr(
        receipt_agent,
        "_extract",
        AsyncMock(
            return_value={
                "type": "statement",
                "transactions": [
                    {"merchant": "Deposit A", "amount": 100.0, "date": "2026-07-10", "type": "credit"},
                    {"merchant": "Deposit B", "amount": 200.0, "date": "2026-07-11", "type": "credit"},
                ],
            }
        ),
    )
    categorize_mock = AsyncMock()
    monkeypatch.setattr(receipt_agent, "categorize_transaction", categorize_mock)

    # must not raise - an all-deposits statement is a legitimate, valid
    # result under the new intentional-filtering behavior, not an error
    result = await receipt_agent.process_receipt("data:image/png;base64,AAAA", test_user.id)

    assert result["transactions_created"] == []
    assert len(result["skipped"]) == 2
    assert result["summary"] == "2 transactions found, 0 expenses added, 2 deposits skipped (not tracked)."
    categorize_mock.assert_not_awaited()  # nothing was ever created to categorize


async def test_all_data_quality_failures_still_raises_value_error(monkeypatch, db_session, test_user):
    # No legitimate deposit-skips here - every item is genuinely unusable,
    # which should still surface as an error, same as before this fix.
    monkeypatch.setattr(
        receipt_agent,
        "_extract",
        AsyncMock(
            return_value={
                "type": "statement",
                "transactions": [
                    {"merchant": None, "amount": 10.0, "date": "2026-07-10", "type": "debit"},
                    {"merchant": "Bad Amount", "amount": -1.0, "date": "2026-07-10", "type": "debit"},
                ],
            }
        ),
    )

    try:
        await receipt_agent.process_receipt("data:image/png;base64,AAAA", test_user.id)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "missing a merchant or amount" in str(exc)


async def test_raw_extraction_and_skips_are_persisted_to_trace(monkeypatch, db_session, test_user):
    raw_response = {
        "type": "statement",
        "transactions": [
            {"merchant": "Kept Expense", "amount": 10.0, "date": "2026-07-10", "type": "debit"},
            {"merchant": "Dropped Deposit", "amount": 500.0, "date": "2026-07-10", "type": "credit"},
        ],
    }
    monkeypatch.setattr(receipt_agent, "_extract", AsyncMock(return_value=raw_response))
    monkeypatch.setattr(receipt_agent, "categorize_transaction", _fake_categorize_transaction())

    await receipt_agent.process_receipt("data:image/png;base64,AAAA", test_user.id)

    trace = (
        await db_session.execute(
            select(Trace).where(Trace.owner_id == test_user.id, Trace.agent_used == "receipt")
        )
    ).scalar_one()

    step = trace.steps[0]
    # the complete, unfiltered model output must be recoverable from the
    # trace alone - this is the whole point of the observability fix
    assert step["raw_extraction"] == raw_response
    assert any(s["reason"] == "deposit, out of scope" for s in step["result"]["skipped"])


async def test_not_a_receipt_reports_empty_skipped_and_summary(monkeypatch, db_session, test_user):
    monkeypatch.setattr(
        receipt_agent, "_extract", AsyncMock(return_value={"type": "not_a_receipt", "transactions": []})
    )

    result = await receipt_agent.process_receipt("data:image/png;base64,AAAA", test_user.id)

    assert result["type"] == "not_a_receipt"
    assert result["skipped"] == []
    assert result["summary"] == ""


def _fake_transactions(n):
    return [
        {"merchant": f"Merchant {i}", "amount": 10.0 + i, "date": "2026-07-10", "type": "debit"}
        for i in range(n)
    ]


async def test_statement_at_the_cap_processes_normally(monkeypatch, db_session, test_user):
    # Exactly MAX_TRANSACTIONS_PER_UPLOAD items - must NOT be rejected,
    # confirming the cap is "more than N", not "N or more".
    n = receipt_agent.MAX_TRANSACTIONS_PER_UPLOAD
    monkeypatch.setattr(
        receipt_agent,
        "_extract",
        AsyncMock(return_value={"type": "statement", "transactions": _fake_transactions(n)}),
    )
    monkeypatch.setattr(receipt_agent, "categorize_transaction", _fake_categorize_transaction())

    result = await receipt_agent.process_receipt("data:image/png;base64,AAAA", test_user.id)

    assert len(result["transactions_created"]) == n

    db_transactions = (
        await db_session.execute(select(Transaction).where(Transaction.owner_id == test_user.id))
    ).scalars().all()
    assert len(db_transactions) == n


async def test_statement_over_the_cap_is_rejected_with_no_db_writes(monkeypatch, db_session, test_user):
    n = receipt_agent.MAX_TRANSACTIONS_PER_UPLOAD + 1
    monkeypatch.setattr(
        receipt_agent,
        "_extract",
        AsyncMock(return_value={"type": "statement", "transactions": _fake_transactions(n)}),
    )
    categorize_mock = AsyncMock()
    monkeypatch.setattr(receipt_agent, "categorize_transaction", categorize_mock)

    try:
        await receipt_agent.process_receipt("data:image/png;base64,AAAA", test_user.id)
        assert False, "expected ValueError"
    except ValueError as exc:
        message = str(exc)
        assert str(n) in message
        assert str(receipt_agent.MAX_TRANSACTIONS_PER_UPLOAD) in message
        assert "too many" in message

    # rejected before any DB writes or categorization happened - not a
    # partial/garbage result
    categorize_mock.assert_not_awaited()
    db_transactions = (
        await db_session.execute(select(Transaction).where(Transaction.owner_id == test_user.id))
    ).scalars().all()
    assert db_transactions == []


async def test_truncated_response_raises_immediately_without_a_wasted_retry(monkeypatch, db_session, test_user):
    # A response cut off by max_tokens can't be salvaged by retrying the
    # identical request - it will truncate again at the same point - so
    # _extract must raise on the first call, not spend a second API call
    # on a doomed retry.
    call_mock = AsyncMock(
        return_value={
            "stop_reason": "max_tokens",
            "content": [{"type": "text", "text": '{"type": "statement", "transactions": [{"merchant":'}],
        }
    )
    monkeypatch.setattr(receipt_agent, "_call_model", call_mock)

    try:
        await receipt_agent.process_receipt("data:image/png;base64,AAAA", test_user.id)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "too many transactions" in str(exc)

    assert call_mock.await_count == 1


def test_extraction_prompt_instructs_stripping_reference_numbers_from_merchant():
    # Regression guard: this guidance is what fixes the "same merchant
    # extracted as inconsistent name strings" bug (e.g. "Zong" on one row
    # vs "Zong0001 Consumer No 03120408494" on another, because the model
    # had no rule for where reference/consumer/STAN metadata bundled into
    # the statement line should be excluded from the merchant name). If
    # this guidance is ever accidentally removed from the prompt, the
    # inconsistency comes back silently with no other test able to catch
    # it, since every other test mocks _extract() and never exercises the
    # real prompt text.
    prompt = receipt_agent.EXTRACTION_SYSTEM_PROMPT.lower()
    assert "consumer" in prompt
    assert "stan" in prompt
    assert "reference" in prompt
    assert "same clean name" in prompt


def test_is_password_protected_pdf_detects_a_real_locked_pdf():
    assert receipt_agent._is_password_protected_pdf(_make_pdf_bytes(encrypted=True)) is True
    assert receipt_agent._is_password_protected_pdf(_make_pdf_bytes(encrypted=False)) is False


def test_is_password_protected_pdf_does_not_flag_unrelated_parse_failures():
    # A genuinely corrupt/non-PDF file is a different, out-of-scope
    # failure mode - this check must not raise, and must not report it as
    # "password protected" (that would be a misleading error message).
    assert receipt_agent._is_password_protected_pdf(b"not a pdf at all") is False


async def test_password_protected_pdf_is_rejected_before_any_model_call(monkeypatch, db_session, test_user):
    extract_mock = AsyncMock()
    monkeypatch.setattr(receipt_agent, "_extract", extract_mock)

    file_b64 = base64.b64encode(_make_pdf_bytes(encrypted=True)).decode("ascii")

    try:
        await receipt_agent.process_receipt(file_b64, test_user.id)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "password-protected" in str(exc)

    # the whole point: no wasted API call on a file that can't be read
    extract_mock.assert_not_awaited()

    db_transactions = (
        await db_session.execute(select(Transaction).where(Transaction.owner_id == test_user.id))
    ).scalars().all()
    assert db_transactions == []


async def test_unlocked_pdf_still_reaches_the_model_normally(monkeypatch, db_session, test_user):
    # Regression check: a real, non-encrypted PDF must not be caught by
    # the password check and must still flow through to extraction
    # exactly as before this fix.
    monkeypatch.setattr(
        receipt_agent,
        "_extract",
        AsyncMock(
            return_value={
                "type": "receipt",
                "transactions": [
                    {"merchant": "Test Store", "amount": 10.0, "date": "2026-07-10", "type": "debit"}
                ],
            }
        ),
    )
    monkeypatch.setattr(receipt_agent, "categorize_transaction", _fake_categorize_transaction())

    file_b64 = base64.b64encode(_make_pdf_bytes(encrypted=False)).decode("ascii")

    result = await receipt_agent.process_receipt(file_b64, test_user.id)

    assert len(result["transactions_created"]) == 1
