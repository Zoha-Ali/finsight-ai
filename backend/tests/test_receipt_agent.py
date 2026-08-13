from unittest.mock import AsyncMock

from sqlalchemy import select

from app.agents import receipt_agent
from app.models import Trace, Transaction


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
